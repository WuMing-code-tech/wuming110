"""
AppsFlyer API 连接器

API 文档: https://support.appsflyer.com/hc/en-us/articles/207034346-Pull-APIs-Pulling-AppsFlyer-Reports-by-APIs
Master API: https://hq.appsflyer.com

数据维度:
- Media Source (媒体来源 → 对应广告平台)
- Campaign / Adset / Ad (需通过 raw_data 或 cohort 报告)
- Country / Region
- App / Product
- LTV (D0/D7/D30/D90)
- Retention (D1/D3/D7/D30)
- Events / Revenue
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from connectors.base import BaseConnector, APIError
from config.settings import settings

logger = logging.getLogger(__name__)


class AppsFlyerConnector(BaseConnector):
    """
    AppsFlyer Master API 连接器

    认证方式: API Key (REST API)
    """

    platform_name = "appsflyer"
    base_url = settings.APPSFLYER_BASE_URL
    rate_limit_cps = 2.0

    def __init__(self, api_key: str = None, app_ids: list[str] = None):
        super().__init__()
        self.api_key = api_key or settings.APPSFLYER_API_KEY
        self.app_ids = app_ids or settings.APPSFLYER_APP_IDS

    def authenticate(self) -> bool:
        """验证 API Key"""
        if not self.app_ids:
            logger.warning("AppsFlyer: No app_ids configured")
            return False
        try:
            # 尝试拉取昨日数据作为验证
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            resp = self._get(
                f"/export/{self.app_ids[0]}/installs_report/v5",
                params={
                    "api_token": self.api_key,
                    "from": yesterday,
                    "to": yesterday,
                }
            )
            logger.info(f"AppsFlyer: Authenticated successfully")
            return True
        except Exception as e:
            logger.error(f"AppsFlyer auth failed: {e}")
            return False

    def get_headers(self) -> dict:
        return {
            "Accept": "application/json",
        }

    # ==================== Raw Data Report (原始数据) ====================

    def get_raw_data(
        self,
        app_id: str,
        start_date: str,
        end_date: str,
        reattr_included: bool = True,
    ) -> list[dict]:
        """
        拉取原始事件数据

        Raw Data Report 包含每条安装/事件的详细信息：
        - 媒体来源 (media_source)
        - 广告系列名称 (campaign)
        - 归因时间
        - 是否来自重归因

        Args:
            app_id: AppsFlyer App ID
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            reattr_included: 是否包含重归因数据

        Returns:
            list[dict]: 逐行原始数据
        """
        endpoint = f"/export/{app_id}/raw_data/v5"

        params = {
            "api_token": self.api_key,
            "from": start_date,
            "to": end_date,
            "reattr": "true" if reattr_included else "false",
        }

        # 原始数据为 CSV 格式（带 header），需要手动解析
        response = self.session.get(
            f"{self.base_url}{endpoint}",
            params=params,
            headers=self.get_headers(),
            timeout=120,  # 大数据量可能较慢
        )
        response.raise_for_status()

        # CSV → list[dict]
        import csv
        import io
        reader = csv.DictReader(io.StringIO(response.text))
        return list(reader)

    # ==================== Aggregate Report (聚合报告) ====================

    def get_installs_report(
        self,
        app_id: str,
        start_date: str,
        end_date: str,
        group_by: list[str] = None,
    ) -> list[dict]:
        """
        安装量聚合报告 (Installs Report)

        Args:
            app_id: App ID
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            group_by: 分组维度 ['media_source', 'campaign', 'country_code', 'app_id']

        Returns:
            list[dict]: 聚合后的安装数据
        """
        endpoint = f"/export/{app_id}/installs_report/v5"

        params = {
            "api_token": self.api_key,
            "from": start_date,
            "to": end_date,
        }
        if group_by:
            params["groupings"] = ",".join(group_by)

        resp = self._get(endpoint, params=params)
        results = resp.get("results", resp.get("data", []))
        return results if isinstance(results, list) else [results]

    def get_ad_revenue_report(
        self,
        app_id: str,
        start_date: str,
        end_date: str,
        group_by: list[str] = None,
    ) -> list[dict]:
        """
        广告变现收入报告 (Ad Revenue Report)

        用于获取应用内广告产生的收入（如 Unity Ads / AdMob 回传）
        """
        endpoint = f"/export/{app_id}/ad_revenue_raw_data/v5"

        params = {
            "api_token": self.api_key,
            "from": start_date,
            "to": end_date,
        }
        if group_by:
            params["groupings"] = ",".join(group_by)

        resp = self._get(endpoint, params=params)
        return resp.get("results", resp.get("data", []))

    def get_in_app_events_report(
        self,
        app_id: str,
        start_date: str,
        end_date: str,
        event_name: str = None,
        group_by: list[str] = None,
    ) -> list[dict]:
        """
        自定义事件报告 (In-App Events Report)

        Args:
            event_name: 事件名称过滤 (如 'af_purchase' 购买事件)
        """
        endpoint = f"/export/{app_id}/in_app_events_report/v5"

        params = {
            "api_token": self.api_key,
            "from": start_date,
            "to": end_date,
        }
        if event_name:
            params["event_name"] = event_name
        if group_by:
            params["groupings"] = ",".join(group_by)

        resp = self._get(endpoint, params=params)
        return resp.get("results", resp.get("data", []))

    # ==================== Cohort Report (群组分析 / LTV) ====================

    def get_cohort_report(
        self,
        app_id: str,
        start_date: str,
        end_date: str,
        kpis: list[str] = None,
        group_by: list[str] = None,
    ) -> list[dict]:
        """
        群组报告 (Cohort Report) — 获取留率和 LTV

        KPIs 可选:
        - retention_day_1 / retention_day_3 / retention_day_7 / retention_day_30
        - revenue_ltv_d0 / revenue_ltv_d7 / revenue_ltv_d30 / revenue_ltv_d90
        - arpu_d0 / arpu_d7 / arpu_d30 / arpu_d90

        Args:
            app_id: App ID
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            kpis: KPI 列表
            group_by: 分组维度

        Returns:
            list[dict]: 群组数据（含 LTV 和 留率）
        """
        endpoint = f"/export/{app_id}/cohort_report/v5"

        params = {
            "api_token": self.api_key,
            "from": start_date,
            "to": end_date,
        }
        if kpis:
            params["kpis"] = ",".join(kpis)
        if group_by:
            params["groupings"] = ",".join(group_by)

        resp = self._get(endpoint, params=params)
        return resp.get("results", resp.get("data", []))

    def get_uninstall_report(
        self,
        app_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """
        卸载报告 (Uninstall Report)
        """
        endpoint = f"/export/{app_id}/uninstall_events_report/v5"

        params = {
            "api_token": self.api_key,
            "from": start_date,
            "to": end_date,
        }

        resp = self._get(endpoint, params=params)
        return resp.get("results", resp.get("data", []))

    # ==================== 统一数据拉取入口 ====================

    def fetch_attribution_data(
        self,
        start_date: str,
        end_date: str,
        include_ltv: bool = True,
    ) -> list[dict]:
        """
        拉取归因数据和 LTV

        为每个 App 拉取安装报告 + 群组报告，合并为统一格式

        Returns:
            list[dict]: 标准化归因数据
        """
        all_data = []

        for app_id in self.app_ids:
            # 1. 安装聚合报告
            installs_data = self.get_installs_report(
                app_id=app_id,
                start_date=start_date,
                end_date=end_date,
                group_by=["media_source", "campaign_name", "adset_name", "country_code", "app_id"],
            )

            # 2. 群组报告 (LTV + Retention)
            cohort_data = []
            if include_ltv:
                try:
                    cohort_data = self.get_cohort_report(
                        app_id=app_id,
                        start_date=start_date,
                        end_date=end_date,
                        kpis=[
                            "retention_day_1", "retention_day_3",
                            "retention_day_7", "retention_day_30",
                            "revenue_ltv_d0", "revenue_ltv_d7",
                            "revenue_ltv_d30", "revenue_ltv_d90",
                        ],
                        group_by=["media_source", "campaign_name", "adset_name", "country_code", "app_id"],
                    )
                except Exception as e:
                    logger.warning(f"AppsFlyer cohort report failed for {app_id}: {e}")

            # 3. 内购事件报告
            iap_data = []
            try:
                iap_data = self.get_in_app_events_report(
                    app_id=app_id,
                    start_date=start_date,
                    end_date=end_date,
                    event_name="af_purchase",
                    group_by=["media_source", "campaign_name", "adset_name", "country_code", "app_id"],
                )
            except Exception as e:
                logger.warning(f"AppsFlyer IAP report failed for {app_id}: {e}")

            # 合并标准化
            for row in installs_data:
                parsed = {
                    "date_id": start_date,
                    "platform_code": self._map_media_source_to_platform(row.get("media_source", "")),
                    "media_source": row.get("media_source", "unknown"),
                    "campaign_name": row.get("campaign_name", ""),
                    "adset_name": row.get("adset_name", ""),
                    "country_code": row.get("country_code", "unknown"),
                    "product_app_id": app_id,
                    "installs": int(row.get("installs", 0) or 0),
                    "uninstalls": int(row.get("uninstalls", 0) or 0),
                    "events": int(row.get("event_count", 0) or 0),
                    "sessions": int(row.get("sessions", 0) or 0),
                    "attributed_revenue": 0.0,
                    "ad_revenue": 0.0,
                    "iap_revenue": 0.0,
                    "retention_d1": 0.0,
                    "retention_d3": 0.0,
                    "retention_d7": 0.0,
                    "retention_d30": 0.0,
                    "ltv_d0": 0.0,
                    "ltv_d7": 0.0,
                    "ltv_d30": 0.0,
                    "ltv_d90": 0.0,
                }

                # 填充 Cohort LTV 数据
                for c_row in cohort_data:
                    if (c_row.get("media_source") == row.get("media_source") and
                        c_row.get("campaign_name") == row.get("campaign_name")):
                        parsed["retention_d1"] = self._safe_float(c_row.get("retention_day_1", 0))
                        parsed["retention_d3"] = self._safe_float(c_row.get("retention_day_3", 0))
                        parsed["retention_d7"] = self._safe_float(c_row.get("retention_day_7", 0))
                        parsed["retention_d30"] = self._safe_float(c_row.get("retention_day_30", 0))
                        parsed["ltv_d0"] = self._safe_float(c_row.get("revenue_ltv_d0", 0))
                        parsed["ltv_d7"] = self._safe_float(c_row.get("revenue_ltv_d7", 0))
                        parsed["ltv_d30"] = self._safe_float(c_row.get("revenue_ltv_d30", 0))
                        parsed["ltv_d90"] = self._safe_float(c_row.get("revenue_ltv_d90", 0))
                        break

                # 填充 IAP 收入
                for iap_row in iap_data:
                    if (iap_row.get("media_source") == row.get("media_source") and
                        iap_row.get("campaign_name") == row.get("campaign_name")):
                        parsed["iap_revenue"] += self._safe_float(iap_row.get("revenue", 0))

                # 汇总归因收入
                parsed["attributed_revenue"] = parsed["ad_revenue"] + parsed["iap_revenue"]

                all_data.append(parsed)

        logger.info(f"AppsFlyer: fetched {len(all_data)} attribution records")
        return all_data

    def _safe_float(self, value) -> float:
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _map_media_source_to_platform(self, media_source: str) -> str:
        """将 AppsFlyer 媒体来源映射到统一平台代码"""
        mapping = {
            "Facebook Ads": "meta",
            "Facebook": "meta",
            "Instagram": "meta",
            "TikTok": "tiktok",
            "TikTok for Business": "tiktok",
            "Google Ads": "google",
            "Google": "google",
            "AdMob": "google",
            "YouTube": "google",
        }
        return mapping.get(media_source, media_source.lower().replace(" ", "_"))
