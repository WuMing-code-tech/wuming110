"""
ETL 编排器
统一的 ETL 流程编排：Extract → Transform → Load

支持两种模式:
- full: 全量同步（首次使用或补数据）
- incremental: 增量同步（日常定时任务，只拉增量天数）
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# 确保项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connectors import get_all_connectors
from etl.extractors.campaign_performance import CampaignPerformanceExtractor
from etl.extractors.creative_performance import CreativePerformanceExtractor
from etl.extractors.region_performance import RegionPerformanceExtractor
from etl.extractors.attribution_data import AttributionDataExtractor
from etl.transformers.normalizer import DataNormalizer
from etl.transformers.metrics_calculator import MetricsCalculator
from etl.loaders.sqlite_loader import SQLiteLoader
from config.settings import settings

logger = logging.getLogger(__name__)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class ETLOrchestrator:
    """
    ETL 编排器

    管道路径:
    1. Connectors: API 拉取原始数据
    2. Extractors: 按维度抽取
    3. Normalizer: 标准化字段
    4. MetricsCalculator: 计算指标
    5. SQLiteLoader: 写入数据库
    """

    def __init__(self, connectors: dict = None):
        self.connectors = connectors or get_all_connectors()

        # 组件初始化
        self.campaign_extractor = CampaignPerformanceExtractor(self.connectors)
        self.creative_extractor = CreativePerformanceExtractor(self.connectors)
        self.region_extractor = RegionPerformanceExtractor(self.connectors)
        self.attribution_extractor = AttributionDataExtractor(self.connectors)
        self.normalizer = DataNormalizer()
        self.metrics_calculator = MetricsCalculator()
        self.loader = SQLiteLoader()

        # 执行统计
        self.stats = {
            "extracted": 0,
            "normalized": 0,
            "calculated": 0,
            "loaded": 0,
            "errors": [],
        }

    def run(
        self,
        mode: str = "incremental",
        start_date: str = None,
        end_date: str = None,
        days: int = 1,
        platforms: list[str] = None,
        include_attribution: bool = True,
        include_creative: bool = False,
    ) -> dict:
        """
        运行完整 ETL 管道

        Args:
            mode: 'full' | 'incremental'
            start_date: 起始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            days: 增量模式下的天数
            platforms: 限定平台列表 ['meta', 'tiktok', ...]
            include_attribution: 是否包含 MMP 归因数据
            include_creative: 是否包含素材维度

        Returns:
            dict: 执行统计
        """
        # 计算日期范围
        if not start_date or not end_date:
            if mode == "full":
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            else:
                end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        logger.info(f"=" * 60)
        logger.info(f"ETL Pipeline Start: {mode} | {start_date} → {end_date}")
        logger.info(f"Platforms: {platforms or 'all'} | Attribution: {include_attribution}")
        logger.info(f"=" * 60)

        try:
            # ============ Extract ============
            logger.info("\n[STEP 1/5] Extracting data from platforms...")

            # 1.1 Campaign 效果数据
            campaign_data = self._extract_by_platform(
                self.campaign_extractor, start_date, end_date, platforms
            )

            # 1.2 Region 地区数据
            region_data = self._extract_by_platform(
                self.region_extractor, start_date, end_date, platforms
            )

            # 1.3 Creative 素材数据 (可选)
            creative_data = []
            if include_creative:
                creative_data = self._extract_by_platform(
                    self.creative_extractor, start_date, end_date, platforms
                )

            # 1.4 MMP 归因数据 (可选)
            attribution_data = []
            if include_attribution and self.connectors.get("appsflyer"):
                try:
                    attribution_data = self.attribution_extractor.extract(
                        start_date=start_date,
                        end_date=end_date,
                        include_ltv=True,
                    )
                    self.stats["extracted"] += len(attribution_data)
                except Exception as e:
                    logger.error(f"Attribution extraction failed: {e}")
                    self.stats["errors"].append(str(e))

            # 合并所有广告平台数据
            all_ad_data = campaign_data + region_data + creative_data
            self.stats["extracted"] += len(all_ad_data)

            if not all_ad_data:
                logger.warning("No data extracted. Check API configuration.")
                return self.stats

            # ============ Transform ============
            logger.info(f"\n[STEP 2/5] Normalizing {len(all_ad_data)} records...")

            # 2.1 数据标准化
            normalized_data = []
            for platform in set(row["platform_code"] for row in all_ad_data if row.get("platform_code")):
                platform_rows = [r for r in all_ad_data if r.get("platform_code") == platform]
                normalized = self.normalizer.normalize_batch(platform_rows, platform)
                normalized_data.extend(normalized)

            self.stats["normalized"] = len(normalized_data)

            # 2.2 MMP 数据合并
            if attribution_data:
                logger.info(f"Merging MMP attribution data ({len(attribution_data)} rows)...")
                normalized_data = self.normalizer.merge_mmp_data(
                    normalized_data, attribution_data
                )

            # ============ Metrics ============
            logger.info(f"\n[STEP 3/5] Calculating metrics for {len(normalized_data)} records...")

            # 3. 计算核心指标
            data_with_metrics = self.metrics_calculator.calc_batch(normalized_data)
            self.stats["calculated"] = len(data_with_metrics)

            # ============ Load ============
            logger.info(f"\n[STEP 4/5] Loading data into SQLite...")

            # 4.1 提取维度数据
            self._load_dimensions(data_with_metrics)
            self._load_dimensions_from_attribution(attribution_data)

            # 4.2 加载事实表
            self.loader.load_ad_performance(data_with_metrics)

            if attribution_data:
                self.loader.load_attribution(attribution_data)

            self.stats["loaded"] = len(data_with_metrics)

            # ============ Summary ============
            logger.info(f"\n[STEP 5/5] ETL Complete!")
            self._print_summary()
            self._print_kpi_preview()

        except Exception as e:
            logger.error(f"ETL pipeline failed: {e}")
            self.stats["errors"].append(str(e))
            raise

        return self.stats

    def _extract_by_platform(
        self,
        extractor,
        start_date: str,
        end_date: str,
        platforms: list[str] = None,
    ) -> list[dict]:
        """按平台抽取数据"""
        all_data = []
        if platforms:
            for plat in platforms:
                data = extractor.extract(
                    platform=plat,
                    start_date=start_date,
                    end_date=end_date,
                )
                all_data.extend(data)
        else:
            data = extractor.extract(
                start_date=start_date,
                end_date=end_date,
            )
            all_data.extend(data)
        return all_data

    def _load_dimensions(self, data: list[dict]):
        """从数据中提取并加载维度表"""
        # 日期
        dates = set()
        for row in data:
            if row.get("date_id"):
                dates.add(row["date_id"])
        self.loader.load_dates(dates)

        # 国家
        countries = set()
        for row in data:
            cc = row.get("country_code", "")
            if cc and cc.lower() != "unknown":
                countries.add((cc.upper(),))
        self.loader.load_countries(countries)

        # Campaign
        campaigns = self._dedup_by_key(data, "platform_campaign_id")
        if campaigns:
            self.loader.load_campaigns(campaigns)

        # Creatives
        creatives = [r for r in data if r.get("platform_creative_id")]
        if creatives:
            self.loader.load_creatives(creatives)

        # Ads
        ads = [r for r in data if r.get("platform_ad_id")]
        if ads:
            self.loader.load_ads(ads)

    def _load_dimensions_from_attribution(self, attribution_data: list[dict]):
        """从归因数据加载产品维度"""
        if not attribution_data:
            return

        products = []
        seen = set()
        for row in attribution_data:
            app_id = row.get("product_app_id", "")
            if app_id and app_id not in seen:
                seen.add(app_id)
                products.append({
                    "appsflyer_app_id": app_id,
                    "product_name": f"App {app_id}",
                    "platform_os": "",
                })
        if products:
            self.loader.load_products(products)

    @staticmethod
    def _dedup_by_key(data: list[dict], key: str) -> list[dict]:
        """按指定 key 去重"""
        seen = set()
        result = []
        for row in data:
            val = row.get(key)
            if val and val not in seen:
                seen.add(val)
                result.append(row)
        return result

    def _print_summary(self):
        """打印 ETL 摘要"""
        db_stats = self.loader.get_stats()
        logger.info(f"\n{'=' * 60}")
        logger.info(f"ETL SUMMARY")
        logger.info(f"  Extracted:   {self.stats['extracted']} rows")
        logger.info(f"  Normalized:  {self.stats['normalized']} rows")
        logger.info(f"  Calculated:  {self.stats['calculated']} rows")
        logger.info(f"  Loaded:      {self.stats['loaded']} rows")
        logger.info(f"  Errors:      {len(self.stats['errors'])}")
        logger.info(f"")
        logger.info(f"  DB Fact (ad):  {db_stats.get('fact_ad_performance', 0)} rows")
        logger.info(f"  DB Fact (attr):{db_stats.get('fact_attribution', 0)} rows")
        logger.info(f"  DB Campaigns:  {db_stats.get('dim_campaign', 0)}")
        logger.info(f"  DB Ads:        {db_stats.get('dim_ad', 0)}")
        logger.info(f"  DB Creatives:  {db_stats.get('dim_creative', 0)}")
        logger.info(f"  DB Countries:  {db_stats.get('dim_country', 0)}")
        logger.info(f"  DB Dates:      {db_stats.get('dim_date', 0)}")
        logger.info(f"{'=' * 60}")

    def _print_kpi_preview(self):
        """打印 KPI 预览"""
        try:
            kpis = self.loader.db.fetch_all("SELECT * FROM mv_daily_kpi LIMIT 10")
            if kpis:
                logger.info(f"\n📊 KPI Preview (last 10 days):")
                logger.info(f"{'Date':<12} {'Platform':<10} {'Spend':>10} {'Installs':>8} {'CPI':>8} {'ROI':>8} {'CTR':>8}")
                logger.info("-" * 65)
                for k in kpis:
                    logger.info(
                        f"{k['date_id']:<12} {k['platform_code']:<10} "
                        f"${k['total_spend']:>9,.2f} {k['total_installs']:>8,} "
                        f"${k['cpi']:>7.2f} {k['roi']:>7.2f} {k['ctr']:>7.2f}%"
                    )
        except Exception:
            pass


# ==================== CLI 入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ETL Pipeline for Ad Performance")
    parser.add_argument("--mode", choices=["full", "incremental"], default="incremental",
                        help="Sync mode: full or incremental")
    parser.add_argument("--days", type=int, default=1,
                        help="Days to fetch (incremental mode)")
    parser.add_argument("--start-date", type=str,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--platforms", type=str, nargs="+",
                        choices=["meta", "tiktok", "google", "appsflyer"],
                        help="Limit to specific platforms")
    parser.add_argument("--no-attribution", action="store_true",
                        help="Skip MMP attribution data")
    parser.add_argument("--include-creative", action="store_true",
                        help="Include creative dimension extraction")

    args = parser.parse_args()

    orchestrator = ETLOrchestrator()

    try:
        stats = orchestrator.run(
            mode=args.mode,
            start_date=args.start_date,
            end_date=args.end_date,
            days=args.days,
            platforms=args.platforms,
            include_attribution=not args.no_attribution,
            include_creative=args.include_creative,
        )

        if stats["errors"]:
            logger.error(f"Completed with {len(stats['errors'])} errors")
            sys.exit(1)
        else:
            logger.info("ETL completed successfully ✅")

    except KeyboardInterrupt:
        logger.warning("ETL interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"ETL failed: {e}")
        sys.exit(1)
