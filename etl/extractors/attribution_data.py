"""
MMP 归因数据抽取
从 AppsFlyer 拉取归因数据（安装、LTV、留率、事件收入）
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class AttributionDataExtractor:
    """
    AppsFlyer 归因数据抽取器

    抽取：
    - 按渠道/广告系列/广告组的安装量
    - LTV (D0/D7/D30/D90)
    - 留存率 (D1/D3/D7/D30)
    - 内购 & 广告变现收入
    """

    def __init__(self, connectors: dict = None):
        self.connectors = connectors or {}
        self.appsflyer = self.connectors.get("appsflyer")

    def extract(
        self,
        start_date: str = None,
        end_date: str = None,
        include_ltv: bool = True,
    ) -> list[dict]:
        """
        从 AppsFlyer 抽取归因数据

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            include_ltv: 是否包含 LTV 数据

        Returns:
            list[dict]: 归因数据
        """
        if not self.appsflyer:
            logger.warning("AppsFlyer connector not configured")
            return []

        if start_date is None:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"Extracting attribution data: {start_date} ~ {end_date}")

        try:
            data = self.appsflyer.fetch_attribution_data(
                start_date=start_date,
                end_date=end_date,
                include_ltv=include_ltv,
            )
            logger.info(f"Extracted {len(data)} attribution rows")
            return data
        except Exception as e:
            logger.error(f"Failed to extract attribution data: {e}")
            return []

    def extract_ltv_only(
        self,
        start_date: str = None,
        end_date: str = None,
    ) -> list[dict]:
        """
        仅抽取 LTV 相关数据（群组报告）
        适合用于 LTV 趋势分析
        """
        if not self.appsflyer:
            logger.warning("AppsFlyer connector not configured")
            return []

        if start_date is None:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        all_data = []
        for app_id in self.appsflyer.app_ids:
            try:
                cohort_data = self.appsflyer.get_cohort_report(
                    app_id=app_id,
                    start_date=start_date,
                    end_date=end_date,
                    kpis=[
                        "retention_day_1", "retention_day_3",
                        "retention_day_7", "retention_day_30",
                        "revenue_ltv_d0", "revenue_ltv_d7",
                        "revenue_ltv_d30", "revenue_ltv_d90",
                        "arpu_d0", "arpu_d7", "arpu_d30",
                    ],
                    group_by=["media_source", "country_code", "app_id"],
                )
                all_data.extend(cohort_data)
            except Exception as e:
                logger.error(f"Failed to extract LTV for app {app_id}: {e}")

        logger.info(f"Extracted {len(all_data)} LTV cohort rows")
        return all_data
