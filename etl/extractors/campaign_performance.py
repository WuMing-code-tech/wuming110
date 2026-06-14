"""
广告系列效果数据抽取
从各广告平台拉取 Campaign 粒度的效果数据（包含花费、展示、点击、安装、收入）
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from connectors import get_connector

logger = logging.getLogger(__name__)


class CampaignPerformanceExtractor:
    """
    广告系列效果数据抽取器

    从 Meta/TikTok/Google 三大平台抽取 Campaign 粒度的性能数据
    """

    def __init__(self, connectors: dict = None):
        self.connectors = connectors or {}

    def extract(
        self,
        platform: str = None,
        start_date: str = None,
        end_date: str = None,
    ) -> list[dict]:
        """
        抽取指定平台或全部平台的效果数据

        Args:
            platform: 'meta' | 'tiktok' | 'google' | None (all)
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            list[dict]: 标准化广告效果数据
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        all_data = []
        platforms = [platform] if platform else ["meta", "tiktok", "google"]

        for plat in platforms:
            if plat not in self.connectors:
                logger.warning(f"Skipping {plat}: no connector configured")
                continue

            conn = self.connectors[plat]
            logger.info(f"Extracting campaign performance from {plat}: {start_date} ~ {end_date}")

            try:
                data = conn.fetch_ad_performance(
                    start_date=start_date,
                    end_date=end_date,
                )
                logger.info(f"{plat}: extracted {len(data)} campaign performance rows")
                all_data.extend(data)
            except Exception as e:
                logger.error(f"Failed to extract from {plat}: {e}")
                continue

        logger.info(f"Total campaign performance rows extracted: {len(all_data)}")
        return all_data

    def extract_by_date_range(
        self,
        start_date: str,
        end_date: str,
        platform: str = None,
    ) -> list[dict]:
        """便捷方法：按日期范围抽取"""
        return self.extract(platform=platform, start_date=start_date, end_date=end_date)
