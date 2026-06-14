#!/usr/bin/env python3
"""
每日自动取数 Agent

功能：
1. 每日自动触发 ETL 增量同步（拉取近 1 天数据）
2. 数据校验：对比昨日 vs 前日数据波动，>30% 偏差自动预警
3. 写入 SQLite 后输出结果摘要
4. 可通过 Claude Code 定时任务或 cron 触发

调度方式：
- Claude Code: 每日 9:07 AM 自动触发
- Cron: 0 7 9 * * *  (备选)
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.orchestrator import ETLOrchestrator
from config.settings import settings
from db.connection import db as database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("daily_fetch_agent")


class DailyFetchAgent:
    """
    每日自动取数 Agent

    执行流程：
    1. 确定取数日期范围（默认昨天 → 今天）
    2. 运行 ETL 增量同步
    3. 数据波动检测
    4. 输出摘要报告
    """

    def __init__(self):
        self.orchestrator = ETLOrchestrator()
        self.db = database

    def run(
        self,
        days: int = 1,
        dry_run: bool = False,
    ) -> dict:
        """
        执行每日取数任务

        Args:
            days: 拉取天数（默认 1 天）
            dry_run: 仅检查不实际写入

        Returns:
            dict: 执行结果摘要
        """
        today = datetime.now()
        end_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (today - timedelta(days=days + 1)).strftime("%Y-%m-%d")

        logger.info(f"🚀 Daily Fetch Agent Started — {start_date} → {end_date}")

        result = {
            "timestamp": today.isoformat(),
            "date_range": f"{start_date} → {end_date}",
            "status": "success",
            "anomalies": [],
            "kpi_summary": {},
        }

        try:
            if not dry_run:
                # 运行 ETL
                stats = self.orchestrator.run(
                    mode="incremental",
                    start_date=start_date,
                    end_date=end_date,
                    days=days,
                )
                result["etl_stats"] = stats

                # 数据波动检测
                result["anomalies"] = self._detect_fluctuation(start_date, end_date)

                # 生成 KPI 摘要
                result["kpi_summary"] = self._generate_kpi_summary(start_date, end_date)

                # 输出报告
                self._print_report(result)

            else:
                logger.info("[DRY RUN] No data written.")
                result["status"] = "dry_run"

        except Exception as e:
            logger.error(f"Daily fetch failed: {e}")
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _detect_fluctuation(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """
        数据波动检测：对比当前周期 vs 上一周期的指标变化

        超过 ALERT_FLUCTUATION_THRESHOLD (默认 30%) 即标记异常
        """
        anomalies = []
        threshold = settings.ALERT_FLUCTUATION_THRESHOLD

        try:
            # 当前周期 KPI
            current = self.db.fetch_all("""
                SELECT
                    platform_code,
                    SUM(impressions) AS impressions,
                    SUM(clicks) AS clicks,
                    SUM(installs) AS installs,
                    SUM(spend) AS spend,
                    SUM(revenue) AS revenue,
                    ROUND(SUM(spend) * 1.0 / NULLIF(SUM(installs), 0), 4) AS cpi,
                    ROUND(SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0), 4) AS ctr,
                    ROUND(SUM(revenue) * 1.0 / NULLIF(SUM(spend), 0), 4) AS roi
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN ? AND ?
                GROUP BY p.platform_code
            """, (start_date, end_date))

            # 上一周期 KPI (等长周期)
            days_span = (datetime.strptime(end_date, "%Y-%m-%d") -
                         datetime.strptime(start_date, "%Y-%m-%d")).days

            prev_start = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=days_span + 1)).strftime("%Y-%m-%d")
            prev_end = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

            previous = self.db.fetch_all("""
                SELECT
                    platform_code,
                    SUM(impressions) AS impressions,
                    SUM(clicks) AS clicks,
                    SUM(installs) AS installs,
                    SUM(spend) AS spend,
                    SUM(revenue) AS revenue,
                    ROUND(SUM(spend) * 1.0 / NULLIF(SUM(installs), 0), 4) AS cpi,
                    ROUND(SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0), 4) AS ctr,
                    ROUND(SUM(revenue) * 1.0 / NULLIF(SUM(spend), 0), 4) AS roi
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN ? AND ?
                GROUP BY p.platform_code
            """, (prev_start, prev_end))

            if not previous:
                logger.info("No previous period data for comparison")
                return anomalies

            # 建立上一周期索引
            prev_index = {p["platform_code"]: p for p in previous}

            for cur in current:
                platform = cur["platform_code"]
                prev = prev_index.get(platform)
                if not prev:
                    continue

                # 检查关键指标波动
                for metric in ["spend", "impressions", "clicks", "installs", "revenue", "cpi", "ctr", "roi"]:
                    cur_val = cur.get(metric, 0) or 0
                    prev_val = prev.get(metric, 0) or 0
                    if prev_val == 0:
                        continue

                    change_pct = (cur_val - prev_val) / prev_val * 100
                    if abs(change_pct) > threshold * 100:
                        anomalies.append({
                            "platform": platform,
                            "metric": metric,
                            "current": round(cur_val, 4),
                            "previous": round(prev_val, 4),
                            "change_pct": round(change_pct, 2),
                            "severity": "critical" if abs(change_pct) > 50 else "warning",
                            "direction": "up" if change_pct > 0 else "down",
                        })
                        logger.warning(
                            f"⚠️  Anomaly: [{platform}] {metric} "
                            f"{'⬆️' if change_pct > 0 else '⬇️'} {abs(change_pct):.1f}% "
                            f"({prev_val:.2f} → {cur_val:.2f})"
                        )

        except Exception as e:
            logger.error(f"Fluctuation detection failed: {e}")

        return anomalies

    def _generate_kpi_summary(
        self,
        start_date: str,
        end_date: str,
    ) -> dict:
        """
        生成期间 KPI 摘要
        包含各平台 CPM, CPM, CTR, ROI, LTV
        """
        try:
            # 广告平台指标
            ad_kpis = self.db.fetch_all(f"""
                SELECT * FROM mv_daily_kpi
                WHERE date_id BETWEEN '{start_date}' AND '{end_date}'
                ORDER BY date_id DESC, platform_code
            """)

            # LTV 指标 (来自 AppsFlyer)
            ltv_kpis = self.db.fetch_all(f"""
                SELECT
                    date_id,
                    media_source,
                    ROUND(AVG(ltv_d7), 4) AS avg_ltv_d7,
                    ROUND(AVG(ltv_d30), 4) AS avg_ltv_d30,
                    ROUND(AVG(retention_d7), 4) AS avg_retention_d7
                FROM fact_attribution
                WHERE date_id BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY date_id, media_source
                ORDER BY date_id DESC
            """)

            return {
                "ad_kpis": [dict(k) for k in (ad_kpis or [])],
                "ltv_kpis": [dict(k) for k in (ltv_kpis or [])],
            }
        except Exception as e:
            logger.error(f"KPI summary generation failed: {e}")
            return {}

    def _print_report(self, result: dict):
        """打印取数报告到终端"""
        print(f"\n{'=' * 70}")
        print(f"  📊 每日广告投流数据报告")
        print(f"  🕐 执行时间: {result['timestamp']}")
        print(f"  📅 数据周期: {result['date_range']}")
        print(f"  ✅ 状态: {result['status']}")
        print(f"{'=' * 70}")

        # ETL 统计
        stats = result.get("etl_stats", {})
        if stats:
            print(f"\n  📥 数据拉取:")
            print(f"     - 提取:   {stats.get('extracted', 0)} 行")
            print(f"     - 标准化: {stats.get('normalized', 0)} 行")
            print(f"     - 加载:   {stats.get('loaded', 0)} 行")

        # 异常检测
        anomalies = result.get("anomalies", [])
        if anomalies:
            print(f"\n  ⚠️  异常检测: {len(anomalies)} 项异常")
            for a in anomalies[:5]:  # Top 5
                direction = "⬆️" if a["direction"] == "up" else "⬇️"
                print(f"     [{a['severity'].upper()}] {a['platform']} {a['metric']} "
                      f"{direction} {abs(a['change_pct']):.1f}% "
                      f"(${a['previous']:.2f} → ${a['current']:.2f})")
        else:
            print(f"\n  ✅ 异常检测: 无异常 (指标波动在正常范围内)")

        # KPI 快照
        kpi_summary = result.get("kpi_summary", {})
        ad_kpis = kpi_summary.get("ad_kpis", [])
        if ad_kpis:
            print(f"\n  📈 KPI 快照 (最近一天):")
            latest_date = ad_kpis[0]["date_id"] if ad_kpis else "N/A"
            for k in ad_kpis:
                if k["date_id"] == latest_date:
                    print(f"     {k['platform_code']:<8} "
                          f"CPI:${k['cpi']:.2f} | "
                          f"CPM:${k['cpm']:.2f} | "
                          f"CTR:{k['ctr']:.2f}% | "
                          f"ROI:{k['roi']:.2f} | "
                          f"Spend:${k['total_spend']:.0f}")

        ltv_kpis = kpi_summary.get("ltv_kpis", [])
        if ltv_kpis:
            print(f"\n  📈 LTV 快照:")
            for k in ltv_kpis[:3]:
                print(f"     {k['media_source']:<12} "
                      f"LTV D7:${k['avg_ltv_d7']:.4f} | "
                      f"LTV D30:${k['avg_ltv_d30']:.4f} | "
                      f"Ret D7:{k['avg_retention_d7']:.1f}%")

        print(f"\n{'=' * 70}\n")

        # ROI 预警
        if ad_kpis:
            for k in ad_kpis:
                if k["roi"] and k["roi"] < settings.ALERT_ROI_THRESHOLD:
                    logger.warning(
                        f"🚨 ROI ALERT: {k['platform_code']} ROI = {k['roi']:.2f} "
                        f"(< threshold {settings.ALERT_ROI_THRESHOLD})"
                    )


# ==================== CLI 入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Daily Fetch Agent")
    parser.add_argument("--days", type=int, default=1, help="Days to fetch")
    parser.add_argument("--dry-run", action="store_true", help="Check only, no write")
    args = parser.parse_args()

    agent = DailyFetchAgent()
    result = agent.run(days=args.days, dry_run=args.dry_run)

    if result["status"] == "error":
        sys.exit(1)
