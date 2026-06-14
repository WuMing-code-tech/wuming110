"""
数据标准化转换器
统一不同广告平台的数据格式、字段名、币种、时区
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 币种兑 USD 汇率参考表（2025-2026 基准值，定期更新）
CURRENCY_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "JPY": 0.0065,
    "KRW": 0.00074,
    "AUD": 0.64,
    "CAD": 0.72,
    "BRL": 0.18,
    "INR": 0.011,
    "IDR": 0.000064,
    "THB": 0.028,
    "VND": 0.000039,
    "MYR": 0.21,
    "SGD": 0.74,
    "PHP": 0.017,
    "TRY": 0.028,
    "SAR": 0.27,
    "AED": 0.27,
    "MXN": 0.049,
    "ARS": 0.0011,
    "COP": 0.00025,
    "PLN": 0.24,
    "RUB": 0.010,
    "ZAR": 0.053,
    "NGN": 0.0006,
    "EGP": 0.020,
    "CNY": 0.14,
    "TWD": 0.031,
    "HKD": 0.13,
    "NOK": 0.091,
    "SEK": 0.092,
    "DKK": 0.15,
    "CHF": 1.12,
    "NZD": 0.60,
    "CZK": 0.044,
    "HUF": 0.0028,
}


class DataNormalizer:
    """
    数据标准化器

    处理：
    - 字段名统一映射
    - 币种转换 (→ USD)
    - 时区处理
    - 缺失值填充
    - 国家代码标准化
    """

    def __init__(self, currency_to_usd: dict = None):
        self.currency_to_usd = currency_to_usd or CURRENCY_TO_USD

    def normalize_record(
        self,
        record: dict,
        platform: str,
    ) -> dict:
        """
        标准化单条广告效果记录

        Args:
            record: 原始记录
            platform: 来源平台 (meta/tiktok/google)

        Returns:
            dict: 标准化记录
        """
        normalized = {
            "date_id": self._normalize_date(record.get("date_id")),
            "platform_code": platform,
            "platform_campaign_id": str(record.get("platform_campaign_id", "")),
            "campaign_name": record.get("campaign_name", ""),
            "platform_adset_id": str(record.get("platform_adset_id", "")),
            "adset_name": record.get("adset_name", ""),
            "platform_ad_id": str(record.get("platform_ad_id", "")),
            "ad_name": record.get("ad_name", ""),
            "platform_creative_id": str(record.get("platform_creative_id", "")) if record.get("platform_creative_id") else None,
            "creative_name": record.get("creative_name", ""),
            "creative_type": record.get("creative_type", ""),
            "headline": record.get("headline", ""),
            "body_text": record.get("body_text", ""),
            "cta_text": record.get("cta_text", ""),
            "country_code": self._normalize_country_code(record.get("country_code", "unknown")),
            "impressions": self._safe_int(record.get("impressions", 0)),
            "clicks": self._safe_int(record.get("clicks", 0)),
            "spend": self._convert_to_usd(
                record.get("spend", 0),
                record.get("currency", "USD")
            ),
            "installs": self._safe_int(record.get("installs", 0)),
            "revenue": self._convert_to_usd(
                record.get("revenue", 0),
                record.get("currency", "USD")
            ),
            "video_views": self._safe_int(record.get("video_views", 0)),
            "video_views_25pct": self._safe_int(record.get("video_views_25pct", 0)),
            "video_views_50pct": self._safe_int(record.get("video_views_50pct", 0)),
            "video_views_75pct": self._safe_int(record.get("video_views_75pct", 0)),
            "video_views_100pct": self._safe_int(record.get("video_views_100pct", 0)),
            "reach": self._safe_int(record.get("reach", 0)),
            "frequency": self._safe_float(record.get("frequency", 0)),
            "data_source": "api",
            "fetched_at": datetime.now().isoformat(),
        }

        return normalized

    def normalize_batch(
        self,
        records: list[dict],
        platform: str,
    ) -> list[dict]:
        """批量标准化"""
        return [self.normalize_record(r, platform) for r in records]

    def merge_mmp_data(
        self,
        ad_platform_data: list[dict],
        appsflyer_data: list[dict],
    ) -> list[dict]:
        """
        将广告平台数据和 MMP 归因数据合并

        合并逻辑：按 date + platform + campaign_name + country_code 匹配
        - 广告平台提供：impressions, clicks, spend
        - AppsFlyer 提供：installs, revenue, LTV, retention（归因口径）

        注意：广告平台侧也有 installs/revenue，但以 MMP 为准
        """
        import hashlib

        # 建立 MMP 索引
        mmp_index = {}
        for row in appsflyer_data:
            key = self._make_match_key(
                date=row.get("date_id", ""),
                platform=row.get("platform_code", ""),
                campaign=row.get("campaign_name", ""),
                country=row.get("country_code", ""),
            )
            mmp_index[key] = row

        merged = []
        for ad_row in ad_platform_data:
            key = self._make_match_key(
                date=ad_row.get("date_id", ""),
                platform=ad_row.get("platform_code", ""),
                campaign=ad_row.get("campaign_name", ""),
                country=ad_row.get("country_code", ""),
            )

            mmp_row = mmp_index.get(key, {})

            merged.append({
                **ad_row,
                # MMP 归因数据
                "mmp_installs": self._safe_int(mmp_row.get("installs", 0)),
                "mmp_revenue": self._safe_float(mmp_row.get("attributed_revenue", 0)),
                "iap_revenue": self._safe_float(mmp_row.get("iap_revenue", 0)),
                "ad_revenue_mmp": self._safe_float(mmp_row.get("ad_revenue", 0)),
                "ltv_d0": self._safe_float(mmp_row.get("ltv_d0", 0)),
                "ltv_d7": self._safe_float(mmp_row.get("ltv_d7", 0)),
                "ltv_d30": self._safe_float(mmp_row.get("ltv_d30", 0)),
                "ltv_d90": self._safe_float(mmp_row.get("ltv_d90", 0)),
                "retention_d1": self._safe_float(mmp_row.get("retention_d1", 0)),
                "retention_d3": self._safe_float(mmp_row.get("retention_d3", 0)),
                "retention_d7": self._safe_float(mmp_row.get("retention_d7", 0)),
                "retention_d30": self._safe_float(mmp_row.get("retention_d30", 0)),
            })

        logger.info(f"Merged {len(merged)} records (ad: {len(ad_platform_data)}, mmp: {len(appsflyer_data)})")
        return merged

    @staticmethod
    def _make_match_key(
        date: str = "",
        platform: str = "",
        campaign: str = "",
        country: str = "",
        app_id: str = "",
    ) -> str:
        """生成匹配键"""
        raw = f"{date}|{platform}|{campaign}|{country}|{app_id}"
        return raw.lower().strip()

    @staticmethod
    def _normalize_date(date_str) -> str:
        """标准化日期为 YYYY-MM-DD"""
        if not date_str:
            return datetime.now().strftime("%Y-%m-%d")
        date_str = str(date_str).strip()
        # 尝试多种格式
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d", "%b %d, %Y", "%B %d, %Y"]:
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return date_str

    @staticmethod
    def _normalize_country_code(code) -> str:
        """标准化国家代码为 ISO 3166-1 alpha-2 大写"""
        if not code:
            return "unknown"
        code = str(code).strip().upper()
        if len(code) == 2:
            return code
        # 常见变体映射
        mapping = {
            "UNITED STATES": "US",
            "UNITED KINGDOM": "GB",
            "GERMANY": "DE",
            "FRANCE": "FR",
            "JAPAN": "JP",
            "SOUTH KOREA": "KR",
            "BRAZIL": "BR",
            "INDIA": "IN",
        }
        return mapping.get(code, code[:2])

    def _convert_to_usd(self, amount, currency: str = "USD") -> float:
        """将金额转换为 USD"""
        try:
            amount = float(amount) if amount else 0.0
        except (ValueError, TypeError):
            amount = 0.0

        currency = (currency or "USD").upper()
        rate = self.currency_to_usd.get(currency, 1.0)
        return round(amount * rate, 6)

    @staticmethod
    def _safe_int(value) -> int:
        try:
            return int(float(value)) if value else 0
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(value) -> float:
        try:
            return float(value) if value else 0.0
        except (ValueError, TypeError):
            return 0.0
