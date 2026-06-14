#!/usr/bin/env python3
"""
异常检测 Agent — 主动监控数据质量与投放效果

检测项目：
1. CPI 突增/突降 (> 2σ 偏离 7 日均值)
2. CTR 异常 (下降 > 30%)
3. 花费超预算 (单日花费超过设定的日预算 85%)
4. ROI 跌破阈值 (ROI < 1.0 或自定义阈值)

执行策略：
- 每日取数完成后自动运行
- 每 4 小时检查一次（大预算重点 Campaign）
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import db as database
from config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("anomaly_detector")


class AnomalyDetector:
    """
    异常检测 Agent

    使用统计方法 + 阈值规则检测广告投放数据异常：
    - 标准差检测（Statistical）
    - 同比环比检测（Period-over-Period）
    - 绝对值阈值检测（Threshold-based）
    """

    def __init__(self):
        self.db = database
        self.alerts = []

    def run(
        self,
        lookback_days: int = 7,
        date: str = None,
    ) -> list[dict]:
        """
        执行全量异常检测

        Args:
            lookback_days: 回溯天数（计算均值/标准差用）
            date: 检测日期 (None = 昨天)

        Returns:
            list[dict]: 所有异常的列表
        """
        if date is None:
            date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"🔍 Anomaly Detection for {date} (lookback: {lookback_days}d)")

        self.alerts = []

        # 1. Statistical: CPI 异常 (标准差检测)
        self.alerts.extend(self._detect_cpi_spike(date, lookback_days))

        # 2. Statistical: CTR 异常
        self.alerts.extend(self._detect_ctr_anomaly(date, lookback_days))

        # 3. Threshold: 花费超预算
        self.alerts.extend(self._detect_spend_budget_exceed(date))

        # 4. Threshold: ROI 跌破阈值
        self.alerts.extend(self._detect_roi_below_threshold(date))

        # 5. Pattern: 素材疲劳度检测
        self.alerts.extend(self._detect_creative_fatigue(date, lookback_days))

        # 6. Completeness: 数据缺失检测
        self.alerts.extend(self._detect_data_gap(date, lookback_days))

        # 分类汇总
        self._print_alert_report()

        return self.alerts

    def _detect_cpi_spike(self, date: str, lookback_days: int) -> list[dict]:
        """
        CPI 突增/突降检测 (2σ 法)

        规则：当日 CPI 偏离 7 日均值超过 2 个标准差即报警
        """
        alerts = []

        date_range_start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        date_range_end = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            # 查询各平台 CPI 历史序列
            history = self.db.fetch_all("""
                SELECT platform_code,
                       AVG(cpi) AS avg_cpi,
                       (SUM(cpi * cpi) / COUNT(cpi) - AVG(cpi) * AVG(cpi)) AS variance
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE date_id BETWEEN ? AND ?
                  AND installs > 0
                GROUP BY platform_code
            """, (date_range_start, date_range_end))

            today_data = self.db.fetch_all("""
                SELECT platform_code,
                       ROUND(SUM(spend) * 1.0 / NULLIF(SUM(installs), 0), 4) AS cpi,
                       SUM(spend) AS spend,
                       SUM(installs) AS installs
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE date_id = ?
                  AND installs > 0
                GROUP BY platform_code
            """, (date,))

            for today in today_data:
                platform = today["platform_code"]
                hist = next((h for h in history if h["platform_code"] == platform), None)

                if not hist or not hist["avg_cpi"]:
                    continue

                import math
                stddev = math.sqrt(max(hist["variance"], 0.0001))
                avg_cpi = hist["avg_cpi"]
                today_cpi = today["cpi"]

                if today_cpi and avg_cpi:
                    deviation = (today_cpi - avg_cpi) / stddev if stddev > 0 else 0

                    if abs(deviation) > 2.0:
                        direction = "spike" if today_cpi > avg_cpi else "drop"
                        severity = "critical" if abs(deviation) > 3.0 else "warning"

                        alerts.append({
                            "type": "cpi_anomaly",
                            "severity": severity,
                            "platform": platform,
                            "date": date,
                            "metric": "CPI",
                            "current_value": round(today_cpi, 4),
                            "avg_7d": round(avg_cpi, 4),
                            "stddev": round(stddev, 4),
                            "deviation_sigma": round(deviation, 2),
                            "direction": direction,
                            "message": f"[{direction.upper()}] {platform} CPI ${today_cpi:.4f} (σ={deviation:.1f})",
                        })
                        logger.warning(
                            f"⚠️  CPI {direction.upper()}: {platform} "
                            f"${today_cpi:.4f} (avg: ${avg_cpi:.4f}, σ={deviation:.1f})"
                        )

        except Exception as e:
            logger.error(f"CPI spike detection failed: {e}")

        return alerts

    def _detect_ctr_anomaly(self, date: str, lookback_days: int) -> list[dict]:
        """
        CTR 异常检测

        规则：当日 CTR 低于 7 日均值 30% 以上即报警
        """
        alerts = []

        date_range_start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        date_range_end = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            # 历史均值
            history = self.db.fetch_all("""
                SELECT platform_code,
                       AVG(ctr) AS avg_ctr
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE date_id BETWEEN ? AND ? AND impressions > 0
                GROUP BY platform_code
            """, (date_range_start, date_range_end))

            # 当日 CTR
            today_data = self.db.fetch_all("""
                SELECT platform_code,
                       ROUND(SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0), 4) AS ctr
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE date_id = ? AND impressions > 0
                GROUP BY platform_code
            """, (date,))

            for today in today_data:
                platform = today["platform_code"]
                hist = next((h for h in history if h["platform_code"] == platform), None)

                if not hist or not hist["avg_ctr"]:
                    continue

                today_ctr = today["ctr"]
                avg_ctr = hist["avg_ctr"]

                if today_ctr and avg_ctr:
                    drop_pct = (avg_ctr - today_ctr) / avg_ctr * 100

                    if drop_pct > 30:
                        alerts.append({
                            "type": "ctr_drop",
                            "severity": "critical" if drop_pct > 50 else "warning",
                            "platform": platform,
                            "date": date,
                            "metric": "CTR",
                            "current_value": round(today_ctr, 4),
                            "avg_7d": round(avg_ctr, 4),
                            "drop_pct": round(drop_pct, 1),
                            "message": f"CTR DROP: {platform} {today_ctr:.2f}% (-{drop_pct:.1f}% vs avg {avg_ctr:.2f}%)",
                        })
                        logger.warning(f"⚠️  CTR Drop: {platform} {today_ctr:.2f}% (-{drop_pct:.1f}%)")

        except Exception as e:
            logger.error(f"CTR anomaly detection failed: {e}")

        return alerts

    def _detect_spend_budget_exceed(self, date: str) -> list[dict]:
        """
        花费超预算检测

        规则：单 Campaign 当日花费超过其日预算的 85%
        """
        alerts = []

        try:
            campaigns = self.db.fetch_all("""
                SELECT
                    c.campaign_name,
                    p.platform_code,
                    c.budget_daily,
                    SUM(f.spend) AS today_spend,
                    ROUND(SUM(f.spend) * 100.0 / NULLIF(c.budget_daily, 0), 1) AS spend_pct
                FROM fact_ad_performance f
                JOIN dim_campaign c ON f.campaign_id = c.campaign_id
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id = ?
                  AND c.budget_daily > 0
                GROUP BY c.campaign_id
                HAVING today_spend > c.budget_daily * ?
                ORDER BY spend_pct DESC
            """, (date, settings.DAILY_BUDGET_WARNING))

            for camp in campaigns:
                alerts.append({
                    "type": "budget_exceed",
                    "severity": "critical" if camp["spend_pct"] > 100 else "warning",
                    "platform": camp["platform_code"],
                    "campaign": camp["campaign_name"],
                    "date": date,
                    "metric": "Spend vs Budget",
                    "budget_daily": round(camp["budget_daily"], 2),
                    "today_spend": round(camp["today_spend"], 2),
                    "spend_pct": round(camp["spend_pct"], 1),
                    "message": f"BUDGET: {camp['campaign_name']} spent ${camp['today_spend']:.0f} "
                              f"({camp['spend_pct']:.0f}% of ${camp['budget_daily']:.0f})",
                })
                logger.warning(
                    f"⚠️  Budget Warning: {camp['campaign_name']} "
                    f"${camp['today_spend']:.0f} / ${camp['budget_daily']:.0f} ({camp['spend_pct']:.0f}%)"
                )

        except Exception as e:
            logger.error(f"Budget detection failed: {e}")

        return alerts

    def _detect_roi_below_threshold(self, date: str) -> list[dict]:
        """
        ROI 跌破阈值检测

        规则：ROI < ALERT_ROI_THRESHOLD 即报警
        """
        alerts = []
        threshold = settings.ALERT_ROI_THRESHOLD

        try:
            low_roi = self.db.fetch_all("""
                SELECT
                    p.platform_code,
                    c.campaign_name,
                    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi,
                    ROUND(SUM(f.spend), 2) AS spend,
                    ROUND(SUM(f.revenue), 2) AS revenue
                FROM fact_ad_performance f
                JOIN dim_campaign c ON f.campaign_id = c.campaign_id
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id = ?
                GROUP BY f.platform_id, f.campaign_id
                HAVING roi < ? AND spend > 100  -- 花费 > $100 才会报警
                ORDER BY roi ASC
            """, (date, threshold))

            for row in low_roi:
                level = "critical" if row["roi"] < threshold * 0.5 else "warning"
                alerts.append({
                    "type": "roi_low",
                    "severity": level,
                    "platform": row["platform_code"],
                    "campaign": row["campaign_name"],
                    "date": date,
                    "metric": "ROI",
                    "current_value": round(row["roi"], 4),
                    "spend": round(row["spend"], 2),
                    "revenue": round(row["revenue"], 2),
                    "threshold": threshold,
                    "message": f"ROI LOW: {row['campaign_name']} ROI={row['roi']:.2f} "
                              f"(spend=${row['spend']:.0f}, rev=${row['revenue']:.0f})",
                })
                logger.warning(f"🚨 ROI Alert: {row['campaign_name']} ROI={row['roi']:.2f}")

        except Exception as e:
            logger.error(f"ROI threshold detection failed: {e}")

        return alerts

    def _detect_creative_fatigue(self, date: str, lookback_days: int) -> list[dict]:
        """
        素材疲劳度检测

        规则：过去 7 天 CTR 持续下降的素材
        """
        alerts = []

        try:
            date_range_start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

            # 每个素材过去 7 天的 CTR 序列
            creative_ctr = self.db.fetch_all("""
                SELECT
                    c.creative_name,
                    c.platform_creative_id,
                    p.platform_code,
                    f.date_id,
                    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 4) AS ctr
                FROM fact_ad_performance f
                JOIN dim_creative c ON f.creative_id = c.creative_id
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN ? AND ?
                  AND f.impressions > 1000
                GROUP BY c.platform_creative_id, f.date_id
                ORDER BY c.platform_creative_id, f.date_id
            """, (date_range_start, date))

            # 按素材分组检测下降趋势
            from collections import defaultdict
            creative_groups = defaultdict(list)
            for row in creative_ctr:
                creative_groups[row["platform_creative_id"]].append(row)

            for creative_id, ctr_rows in creative_groups.items():
                if len(ctr_rows) < 3:
                    continue

                ctr_series = [r["ctr"] for r in ctr_rows]
                # 简单线性趋势判断
                n = len(ctr_series)
                x_mean = (n - 1) / 2
                y_mean = sum(ctr_series) / n
                numerator = sum((i - x_mean) * (ctr_series[i] - y_mean) for i in range(n))
                denominator = sum((i - x_mean) ** 2 for i in range(n))

                if denominator > 0:
                    slope = numerator / denominator
                    avg_ctr = max(y_mean, 0.01)
                    decay_rate = abs(slope) / avg_ctr

                    if slope < 0 and decay_rate > 0.05:  # 5% daily decay
                        name = ctr_rows[0]["creative_name"] or f"Creative#{creative_id}"
                        alerts.append({
                            "type": "creative_fatigue",
                            "severity": "critical" if decay_rate > 0.1 else "warning",
                            "platform": ctr_rows[0]["platform_code"],
                            "creative_name": name,
                            "date": date,
                            "metric": "CTR Trend",
                            "slope": round(slope, 6),
                            "decay_rate": round(decay_rate * 100, 1),
                            "message": f"FATIGUE: {name} CTR trending down ({ctr_series[-1]:.2f}% ↓)",
                        })

        except Exception as e:
            logger.error(f"Creative fatigue detection failed: {e}")

        return alerts

    def _detect_data_gap(self, date: str, lookback_days: int) -> list[dict]:
        """
        数据缺失检测

        规则：检查过去 N 天是否有平台数据缺失
        """
        alerts = []

        try:
            for days_ago in range(1, lookback_days + 1):
                check_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=days_ago)).strftime("%Y-%m-%d")

                platforms = self.db.fetch_all("""
                    SELECT p.platform_code, p.platform_name
                    FROM dim_platform p
                    WHERE p.platform_id NOT IN (
                        SELECT DISTINCT f.platform_id
                        FROM fact_ad_performance f
                        WHERE f.date_id = ?
                    )
                """, (check_date,))

                for plat in platforms:
                    alerts.append({
                        "type": "data_gap",
                        "severity": "warning",
                        "platform": plat["platform_code"],
                        "date": check_date,
                        "metric": "Data Completeness",
                        "message": f"DATA GAP: No data for {plat['platform_name']} on {check_date}",
                    })

        except Exception as e:
            logger.error(f"Data gap detection failed: {e}")

        return alerts

    def _print_alert_report(self):
        """打印异常检测报告"""
        print(f"\n{'=' * 70}")
        print(f"  🔔 异常检测报告 — {len(self.alerts)} 项异常")
        print(f"{'=' * 70}")

        if not self.alerts:
            print(f"\n  ✅ 所有指标正常，无异常发现")
            return

        # 按严重程度分组
        critical = [a for a in self.alerts if a["severity"] == "critical"]
        warnings = [a for a in self.alerts if a["severity"] == "warning"]

        if critical:
            print(f"\n  🚨 CRITICAL ({len(critical)}):")
            for a in critical:
                print(f"     [{a['type']}] {a['message']}")

        if warnings:
            print(f"\n  ⚠️  WARNING ({len(warnings)}):")
            for a in warnings[:10]:
                print(f"     [{a['type']}] {a['message']}")

        # 按类型统计
        from collections import Counter
        type_counts = Counter(a["type"] for a in self.alerts)
        print(f"\n  📊 按类型统计:")
        for alert_type, count in type_counts.most_common():
            print(f"     {alert_type}: {count}")

        print(f"\n{'=' * 70}\n")

    def get_alert_summary(self) -> dict:
        """
        返回异常摘要，供下游 Agent 消费

        Returns: {
            total: int,
            critical: int,
            warning: int,
            by_type: dict,
            by_platform: dict,
        }
        """
        from collections import Counter
        return {
            "total": len(self.alerts),
            "critical": len([a for a in self.alerts if a["severity"] == "critical"]),
            "warning": len([a for a in self.alerts if a["severity"] == "warning"]),
            "by_type": dict(Counter(a["type"] for a in self.alerts)),
            "by_platform": dict(Counter(a.get("platform", "unknown") for a in self.alerts)),
        }


# ==================== CLI 入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Anomaly Detector Agent")
    parser.add_argument("--date", type=str, help="Date to check (YYYY-MM-DD)")
    parser.add_argument("--lookback", type=int, default=7, help="Lookback days")
    args = parser.parse_args()

    detector = AnomalyDetector()
    alerts = detector.run(lookback_days=args.lookback, date=args.date)

    if any(a["severity"] == "critical" for a in alerts):
        sys.exit(2)  # Critical exit code
    elif alerts:
        sys.exit(1)  # Warning exit code
    else:
        sys.exit(0)  # All clear
