"""
地区维度数据抽取
从各广告平台拉取按国家/地区拆分的效果数据
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class RegionPerformanceExtractor:
    """
    地区维度数据抽取器

    负责：
    - 按国家拆分数据
    - 关联汇率、时区等维度信息
    - 识别 T1/T2/T3 市场
    """

    # 常用国家代码列表（覆盖主要海外投放市场）
    TIER1_COUNTRIES = {
        "US", "CA", "GB", "UK", "AU", "NZ",
        "DE", "FR", "IT", "ES", "NL", "BE", "SE", "NO", "DK", "FI",
        "CH", "AT", "IE", "LU", "JP", "KR", "SG", "HK",
    }

    TIER2_COUNTRIES = {
        "BR", "MX", "AR", "CL", "CO", "PE",           # LATAM
        "IN", "ID", "PH", "TH", "VN", "MY",             # SEA
        "TR", "SA", "AE", "QA", "KW",                    # MENA
        "PL", "CZ", "HU", "RO", "PT", "GR",              # CEE
        "ZA", "NG", "EG",                                 # Africa
        "TW",                                              # 台湾
    }

    def __init__(self, connectors: dict = None):
        self.connectors = connectors or {}

    def extract(
        self,
        platform: str = None,
        start_date: str = None,
        end_date: str = None,
    ) -> list[dict]:
        """
        抽取按国家拆分的效果数据

        Returns:
            list[dict]: 含 country_code, country_tier, 地区标签的数据
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        all_data = []
        platforms = [platform] if platform else ["meta", "tiktok", "google"]

        for plat in platforms:
            if plat not in self.connectors:
                continue

            conn = self.connectors[plat]
            logger.info(f"Extracting region data from {plat}: {start_date} ~ {end_date}")

            try:
                if plat == "meta":
                    # Meta 支持 country breakdown
                    data = conn.fetch_ad_performance(
                        start_date=start_date,
                        end_date=end_date,
                        breakdown="country",
                    )
                else:
                    # TikTok & Google 默认已包含 country_code
                    data = conn.fetch_ad_performance(
                        start_date=start_date,
                        end_date=end_date,
                    )

                # 添加地区分层标签
                for row in data:
                    country_code = row.get("country_code", "").upper()
                    row["country_code"] = country_code
                    row["country_tier"] = self.get_country_tier(country_code)
                    row["region"] = self.get_region(country_code)

                all_data.extend(data)

            except Exception as e:
                logger.error(f"Failed to extract region data from {plat}: {e}")
                continue

        logger.info(f"Total region performance rows extracted: {len(all_data)}")
        return all_data

    def get_country_tier(self, country_code: str) -> int:
        """
        根据国家代码返回市场分层

        Returns:
            1=Tier1, 2=Tier2, 3=Tier3
        """
        cc = country_code.upper()
        if cc in self.TIER1_COUNTRIES:
            return 1
        elif cc in self.TIER2_COUNTRIES:
            return 2
        else:
            return 3

    def get_region(self, country_code: str) -> str:
        """
        根据国家代码返回大区

        Returns:
            NA / LATAM / EMEA / APAC
        """
        cc = country_code.upper()

        # North America
        if cc in ("US", "CA", "MX"):
            return "NA"

        # Latin America
        if cc in ("BR", "AR", "CL", "CO", "PE", "UY", "PY", "BO", "EC", "VE"):
            return "LATAM"

        # Asia Pacific
        if cc in ("JP", "KR", "CN", "TW", "HK", "SG", "IN", "ID", "PH", "TH",
                  "VN", "MY", "AU", "NZ", "PK", "BD", "LK", "KH", "MM"):
            return "APAC"

        # Default EMEA
        return "EMEA"

    def aggregate_by_region(
        self,
        data: list[dict],
    ) -> list[dict]:
        """
        按大区聚合数据

        Returns:
            list[dict]: [{region: "NA", total_spend: ..., total_installs: ..., ...}, ...]
        """
        from collections import defaultdict

        region_agg = defaultdict(lambda: {
            "region": "",
            "total_spend": 0.0,
            "total_impressions": 0,
            "total_clicks": 0,
            "total_installs": 0,
            "total_revenue": 0.0,
            "countries": set(),
        })

        for row in data:
            region = row.get("region", "EMEA")
            agg = region_agg[region]
            agg["region"] = region
            agg["total_spend"] += row.get("spend", 0)
            agg["total_impressions"] += row.get("impressions", 0)
            agg["total_clicks"] += row.get("clicks", 0)
            agg["total_installs"] += row.get("installs", 0)
            agg["total_revenue"] += row.get("revenue", 0)
            agg["countries"].add(row.get("country_code", ""))

        result = []
        for region, agg in region_agg.items():
            from config.metric_definitions import cpi, cpm, ctr, roi_roas
            agg["country_count"] = len(agg["countries"])
            agg["countries"] = list(agg["countries"])
            agg["cpi"] = cpi(agg["total_spend"], agg["total_installs"])
            agg["cpm"] = cpm(agg["total_spend"], agg["total_impressions"])
            agg["ctr"] = ctr(agg["total_clicks"], agg["total_impressions"])
            agg["roi"] = roi_roas(agg["total_revenue"], agg["total_spend"])
            result.append(dict(agg))

        return result
