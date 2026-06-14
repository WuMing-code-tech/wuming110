"""
SQLite 数据批量写入器
将 ETL 管道处理完的数据写入 SQLite 事实表和维度表
"""

import logging
from datetime import datetime
from typing import Optional
from db.connection import db as database

logger = logging.getLogger(__name__)


class SQLiteLoader:
    """
    SQLite 数据加载器

    - 维表 UPSERT（先查后插）
    - 事实表 BATCH INSERT（REPLACE 去重）
    - 事务控制，出错回滚
    """

    def __init__(self):
        self.db = database

    # ==================== 维度表加载 ====================

    def load_dates(self, dates: set[str]):
        """
        批量加载日期维度

        Args:
            dates: set of 'YYYY-MM-DD'
        """
        if not dates:
            return

        records = []
        for date_str in sorted(dates):
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                week_start = (dt - __import__('datetime').timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
                month_start = dt.strftime("%Y-%m-01")

                records.append((
                    date_str,
                    date_str,
                    dt.year,
                    (dt.month - 1) // 3 + 1,
                    dt.month,
                    dt.isocalendar()[1],
                    (dt.weekday() + 1) % 7,  # 0=Sun
                    dt.day,
                    1 if dt.weekday() >= 5 else 0,  # weekend
                    0,  # is_holiday
                    week_start,
                    month_start,
                ))
            except ValueError:
                continue

        if records:
            self.db.insert_many(
                """INSERT OR REPLACE INTO dim_date
                   (date_id, date_date, year, quarter, month, week_of_year,
                    day_of_week, day_of_month, is_weekend, is_holiday,
                    week_start_date, month_start_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                records,
            )
            logger.info(f"Loaded {len(records)} dates into dim_date")

    def load_countries(self, countries: set[tuple]):
        """
        批量加载国家维度

        Args:
            countries: set of (country_code,)
        """
        if not countries:
            return

        from etl.transformers.normalizer import CURRENCY_TO_USD
        from etl.extractors.region_performance import RegionPerformanceExtractor

        region_extractor = RegionPerformanceExtractor()

        records = []
        for (country_code,) in countries:
            if not country_code or country_code.lower() == "unknown":
                continue
            cc = country_code.upper()
            records.append((
                cc,
                cc,  # country_name 先用 code
                region_extractor.get_region(cc),
                "",  # timezone
                CURRENCY_TO_USD.get(cc, "USD"),
                CURRENCY_TO_USD.get(cc, 1.0),
                1 if region_extractor.get_country_tier(cc) == 1 else 0,
            ))

        if records:
            self.db.insert_many(
                """INSERT OR REPLACE INTO dim_country
                   (country_code, country_name, region, timezone, currency_code, currency_to_usd_rate, is_tier1)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                records,
            )
            logger.info(f"Loaded {len(records)} countries into dim_country")

    def load_campaigns(self, campaigns: list[dict]):
        """加载广告系列维度"""
        if not campaigns:
            return

        records = []
        for c in campaigns:
            platform_code = c.get("platform_code", "unknown")
            platform_id = self._resolve_platform_id(platform_code)

            records.append((
                str(c.get("platform_campaign_id", "")),
                platform_id,
                c.get("campaign_name", ""),
                c.get("objective", ""),
                c.get("status", ""),
                c.get("daily_budget", 0),
                c.get("lifetime_budget", 0),
                c.get("bidding_strategy", ""),
            ))

        if records:
            self.db.insert_many(
                """INSERT OR REPLACE INTO dim_campaign
                   (platform_campaign_id, platform_id, campaign_name, objective,
                    status, budget_daily, budget_lifetime, bidding_strategy)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                records,
            )
            logger.info(f"Loaded {len(records)} campaigns into dim_campaign")

    def load_creatives(self, creatives: list[dict]):
        """加载素材维度"""
        if not creatives:
            return

        records = []
        for c in creatives:
            platform_id = self._resolve_platform_id(c.get("platform_code", "unknown"))

            records.append((
                str(c.get("platform_creative_id", "")),
                platform_id,
                c.get("creative_name", ""),
                c.get("creative_type", ""),
                c.get("image_url", ""),
                c.get("video_url", ""),
                c.get("headline", ""),
                c.get("body_text", ""),
                c.get("cta_text", ""),
            ))

        if records:
            self.db.insert_many(
                """INSERT OR REPLACE INTO dim_creative
                   (platform_creative_id, platform_id, creative_name, creative_type,
                    image_url, video_url, headline, body_text, cta_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                records,
            )
            logger.info(f"Loaded {len(records)} creatives into dim_creative")

    def load_ads(self, ads: list[dict]):
        """加载广告维度"""
        if not ads:
            return

        records = []
        for ad in ads:
            platform_id = self._resolve_platform_id(ad.get("platform_code", "unknown"))

            records.append((
                str(ad.get("platform_ad_id", "")),
                str(ad.get("platform_campaign_id", "")),
                platform_id,
                ad.get("ad_name", ""),
                str(ad.get("platform_creative_id", "")),
            ))

        if records:
            self.db.insert_many(
                """INSERT OR REPLACE INTO dim_ad
                   (platform_ad_id, platform_campaign_id, platform_id, ad_name, creative_id)
                   VALUES (?, ?, ?, ?, ?)""",
                records,
            )
            logger.info(f"Loaded {len(records)} ads into dim_ad")

    def load_products(self, products: list[dict]):
        """加载产品维度"""
        if not products:
            return

        records = []
        for p in products:
            records.append((
                p.get("appsflyer_app_id", ""),
                p.get("product_name", ""),
                p.get("platform_os", ""),
                p.get("bundle_id", ""),
                p.get("category", ""),
            ))

        if records:
            self.db.insert_many(
                """INSERT OR REPLACE INTO dim_product
                   (appsflyer_app_id, product_name, platform_os, bundle_id, category)
                   VALUES (?, ?, ?, ?, ?)""",
                records,
            )
            logger.info(f"Loaded {len(records)} products into dim_product")

    # ==================== 事实表加载 ====================

    def load_ad_performance(self, rows: list[dict]):
        """
        批量加载广告效果事实数据

        Args:
            rows: 标准化+计算指标后的数据列表
        """
        if not rows:
            logger.warning("No data to load into fact_ad_performance")
            return

        records = []
        for row in rows:
            platform_id = self._resolve_platform_id(row.get("platform_code", "unknown"))
            country_id = self._resolve_country_id(row.get("country_code", ""))
            product_id = self._resolve_product_id(row.get("product_app_id", ""))
            campaign_id = self._resolve_campaign_id(
                row.get("platform_campaign_id", ""), platform_id
            )
            ad_id = self._resolve_ad_id(
                row.get("platform_ad_id", ""), platform_id
            )
            creative_id = self._resolve_creative_id(
                row.get("platform_creative_id", ""), platform_id
            )

            records.append((
                row.get("date_id", ""),
                platform_id,
                campaign_id,
                ad_id,
                creative_id,
                country_id,
                product_id,
                int(row.get("impressions", 0)),
                int(row.get("clicks", 0)),
                float(row.get("spend", 0)),
                int(row.get("installs", 0)),
                float(row.get("revenue", 0)),
                int(row.get("video_views", 0)),
                int(row.get("video_views_25pct", 0)),
                int(row.get("video_views_50pct", 0)),
                int(row.get("video_views_75pct", 0)),
                int(row.get("video_views_100pct", 0)),
                float(row.get("cpi", 0)),
                float(row.get("cpm", 0)),
                float(row.get("ctr", 0)),
                float(row.get("roi", 0)),
                float(row.get("cvr", 0)),
                row.get("data_source", "api"),
            ))

        self.db.insert_many(
            """INSERT OR REPLACE INTO fact_ad_performance
               (date_id, platform_id, campaign_id, ad_id, creative_id,
                country_id, product_id,
                impressions, clicks, spend, installs, revenue,
                video_views, video_views_25pct, video_views_50pct,
                video_views_75pct, video_views_100pct,
                cpi, cpm, ctr, roi, cvr,
                data_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
        logger.info(f"Loaded {len(records)} rows into fact_ad_performance")

    def load_attribution(self, rows: list[dict]):
        """
        批量加载归因事实数据 (AppsFlyer)
        """
        if not rows:
            return

        records = []
        for row in rows:
            platform_id = self._resolve_platform_id(row.get("platform_code", "unknown"))
            country_id = self._resolve_country_id(row.get("country_code", ""))
            product_id = self._resolve_product_id(row.get("product_app_id", ""))

            records.append((
                row.get("date_id", ""),
                platform_id,
                None,  # campaign_id
                None,  # ad_id
                country_id,
                product_id,
                int(row.get("installs", 0)),
                int(row.get("uninstalls", 0)),
                int(row.get("events", 0)),
                float(row.get("attributed_revenue", 0)),
                float(row.get("ad_revenue", 0)),
                float(row.get("iap_revenue", 0)),
                int(row.get("sessions", 0)),
                float(row.get("retention_d1", 0)),
                float(row.get("retention_d3", 0)),
                float(row.get("retention_d7", 0)),
                float(row.get("retention_d30", 0)),
                float(row.get("ltv_d0", 0)),
                float(row.get("ltv_d7", 0)),
                float(row.get("ltv_d30", 0)),
                float(row.get("ltv_d90", 0)),
                row.get("media_source", ""),
                row.get("campaign_name", ""),
                row.get("adset_name", ""),
            ))

        self.db.insert_many(
            """INSERT OR REPLACE INTO fact_attribution
               (date_id, platform_id, campaign_id, ad_id,
                country_id, product_id,
                installs, uninstalls, events, attributed_revenue,
                ad_revenue, iap_revenue, sessions,
                retention_d1, retention_d3, retention_d7, retention_d30,
                ltv_d0, ltv_d7, ltv_d30, ltv_d90,
                media_source, campaign_name, adset_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
        logger.info(f"Loaded {len(records)} rows into fact_attribution")

    # ==================== 维度解析辅助方法 ====================

    def _resolve_platform_id(self, platform_code: str) -> int:
        """根据平台代码获取 platform_id"""
        if not platform_code:
            return 1
        mapping = {
            "meta": 1,
            "tiktok": 2,
            "google": 3,
        }
        return mapping.get(platform_code.lower(), 1)

    def _resolve_country_id(self, country_code: str) -> int:
        """获取或创建 country_id"""
        if not country_code or country_code.lower() == "unknown":
            return None
        result = self.db.fetch_one(
            "SELECT country_id FROM dim_country WHERE country_code = ?",
            (country_code.upper(),)
        )
        return result["country_id"] if result else None

    def _resolve_product_id(self, appsflyer_app_id: str) -> int:
        """获取 product_id"""
        if not appsflyer_app_id:
            return None
        result = self.db.fetch_one(
            "SELECT product_id FROM dim_product WHERE appsflyer_app_id = ?",
            (appsflyer_app_id,)
        )
        return result["product_id"] if result else None

    def _resolve_campaign_id(self, platform_campaign_id: str, platform_id: int) -> int:
        """获取 campaign_id"""
        if not platform_campaign_id:
            return None
        result = self.db.fetch_one(
            "SELECT campaign_id FROM dim_campaign WHERE platform_campaign_id = ? AND platform_id = ?",
            (str(platform_campaign_id), platform_id)
        )
        return result["campaign_id"] if result else None

    def _resolve_ad_id(self, platform_ad_id: str, platform_id: int) -> int:
        """获取 ad_id"""
        if not platform_ad_id:
            return None
        result = self.db.fetch_one(
            "SELECT ad_id FROM dim_ad WHERE platform_ad_id = ? AND platform_id = ?",
            (str(platform_ad_id), platform_id)
        )
        return result["ad_id"] if result else None

    def _resolve_creative_id(self, platform_creative_id: str, platform_id: int) -> int:
        """获取 creative_id"""
        if not platform_creative_id:
            return None
        result = self.db.fetch_one(
            "SELECT creative_id FROM dim_creative WHERE platform_creative_id = ? AND platform_id = ?",
            (str(platform_creative_id), platform_id)
        )
        return result["creative_id"] if result else None

    # ==================== 工具方法 ====================

    def get_stats(self) -> dict:
        """获取当前数据库统计信息"""
        tables = ["fact_ad_performance", "fact_attribution",
                  "dim_platform", "dim_campaign", "dim_ad", "dim_creative",
                  "dim_country", "dim_date", "dim_product"]

        stats = {}
        for table in tables:
            count = self.db.table_row_count(table)
            stats[table] = count

        return stats

    def clear_data(self, table: str = None):
        """清空表数据（调试用）"""
        with self.db.get_connection() as conn:
            if table:
                conn.execute(f"DELETE FROM {table}")
            else:
                conn.execute("DELETE FROM fact_ad_performance")
                conn.execute("DELETE FROM fact_attribution")
        logger.warning(f"Cleared data from table(s): {table or 'all fact tables'}")
