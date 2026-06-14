#!/usr/bin/env python3
"""
业务洞察挖掘 Agent

功能：
1. 多维度交叉分析：素材疲劳度 × ROI、渠道效能 × 地区、时间趋势 × 预算
2. 预算分配优化建议（基于历史 ROI）
3. 异常根因分析（结合多方数据源交叉验证）
4. 素材效果归因（找出 CTR/CVR 关键驱动因素）
5. 输出可指导投放决策的分析结论

触发方式：
- 每周周报生成后自动运行
- 按需手动触发深度分析
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
logger = logging.getLogger("insight_miner")


class InsightMiner:
    """
    业务洞察挖掘 Agent

    分析方法：
    - 交叉分析 (Cross Analysis)
    - 趋势分解 (Decomposition)
    - 相关性分析 (Correlation)
    - 预算优化 (Budget Optimization)
    """

    def __init__(self):
        self.db = database
        self.insights = []

    def run(
        self,
        start_date: str = None,
        end_date: str = None,
        deep_analysis: bool = False,
    ) -> dict:
        """
        执行全维度洞察挖掘

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            deep_analysis: 是否执行深度分析（更耗时）

        Returns:
            dict: 结构化洞察结果
        """
        if end_date is None:
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        logger.info(f"🔬 Insight Mining: {start_date} → {end_date}")

        self.insights = []

        # 1. 渠道效能评分
        channel_insights = self._analyze_channel_efficiency(start_date, end_date)
        self.insights.extend(channel_insights)

        # 2. 素材疲劳度分析
        creative_insights = self._analyze_creative_lifecycle(start_date, end_date)
        self.insights.extend(creative_insights)

        # 3. 地区潜力挖掘
        region_insights = self._analyze_region_potential(start_date, end_date)
        self.insights.extend(region_insights)

        # 4. 预算分配优化
        budget_advice = self._analyze_budget_optimization(start_date, end_date)
        self.insights.extend(budget_advice)

        # 5. 深度分析（可选）
        if deep_analysis:
            deep_insights = self._deep_analysis(start_date, end_date)
            self.insights.extend(deep_insights)

        # 构建结构化输出
        result = {
            "period": f"{start_date} → {end_date}",
            "total_insights": len(self.insights),
            "insights": self.insights,
            "executive_summary": self._build_executive_summary(),
            "recommendations": self._build_recommendations(),
        }

        self._print_insight_report(result)

        return result

    def _analyze_channel_efficiency(self, start_date: str, end_date: str) -> list[dict]:
        """
        渠道效能分析

        综合 ROI / CPI / CTR / CVR 评分渠道效率
        """
        insights = []

        try:
            channels = self.db.fetch_all(f"""
                SELECT
                    p.platform_code,
                    p.platform_name,
                    SUM(f.spend) AS total_spend,
                    SUM(f.impressions) AS total_impressions,
                    SUM(f.clicks) AS total_clicks,
                    SUM(f.installs) AS total_installs,
                    SUM(f.revenue) AS total_revenue,
                    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 4) AS cpi,
                    ROUND(SUM(f.spend) * 1000.0 / NULLIF(SUM(f.impressions), 0), 4) AS cpm,
                    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 4) AS ctr,
                    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi,
                    ROUND(SUM(f.installs) * 100.0 / NULLIF(SUM(f.clicks), 0), 4) AS cvr
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY p.platform_code, p.platform_name
            """)

            for ch in channels:
                # 综合效能评分
                score = self._channel_score(ch)
                ch["efficiency_score"] = score

                # 判断状态
                if score >= 80:
                    insights.append({
                        "category": "channel_efficiency",
                        "severity": "positive",
                        "platform": ch["platform_name"],
                        "metric": "综合效能",
                        "value": score,
                        "message": f"✅ {ch['platform_name']} 表现优异 (评分: {score}/100)，ROI={ch['roi']:.2f}，CPI=${ch['cpi']:.2f}",
                        "action": "考虑加大预算投入，扩展受众定向",
                    })
                elif score < 50:
                    insights.append({
                        "category": "channel_efficiency",
                        "severity": "negative",
                        "platform": ch["platform_name"],
                        "metric": "综合效能",
                        "value": score,
                        "message": f"⚠️ {ch['platform_name']} 效率偏低 (评分: {score}/100)，ROI={ch['roi']:.2f}",
                        "action": "建议优化受众定向或素材策略，或削减预算",
                    })

            # 渠道预算占比 vs ROI 匹配度分析
            if len(channels) >= 2:
                total_spend = sum(c["total_spend"] for c in channels) or 1
                for ch in channels:
                    spend_pct = ch["total_spend"] / total_spend * 100
                    avg_roi = sum(c["roi"] for c in channels) / len(channels) if channels else 1
                    roi_contribution = ch["roi"] / avg_roi if avg_roi > 0 else 1

                    # 如果预算占比高但 ROI 低
                    if spend_pct > 40 and roi_contribution < 0.8:
                        insights.append({
                            "category": "budget_allocation",
                            "severity": "warning",
                            "platform": ch["platform_name"],
                            "metric": "预算匹配度",
                            "value": roi_contribution,
                            "message": f"🔔 {ch['platform_name']} 消耗 {spend_pct:.0f}% 预算但 ROI 仅为均值的 {roi_contribution:.0%}",
                            "action": f"建议将 {ch['platform_name']} 预算降至 30% 以下，转投高 ROI 渠道",
                        })

        except Exception as e:
            logger.error(f"Channel efficiency analysis failed: {e}")

        return insights

    def _analyze_creative_lifecycle(self, start_date: str, end_date: str) -> list[dict]:
        """
        素材生命周期分析

        - 素材疲劳度（CTR 衰减速度）
        - 素材最佳生命周期（首次上线 → 效果下降的时间窗口）
        - 新素材 vs 旧素材效果对比
        """
        insights = []

        try:
            # 素材最近 30 天表现
            creatives = self.db.fetch_all(f"""
                SELECT
                    c.platform_creative_id,
                    c.creative_name,
                    c.creative_type,
                    p.platform_name,
                    COUNT(DISTINCT f.date_id) AS active_days,
                    SUM(f.spend) AS total_spend,
                    SUM(f.installs) AS total_installs,
                    AVG(f.ctr) AS avg_ctr,
                    AVG(f.cvr) AS avg_cvr,
                    AVG(f.roi) AS avg_roi
                FROM fact_ad_performance f
                JOIN dim_creative c ON f.creative_id = c.creative_id
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY c.platform_creative_id
                HAVING SUM(f.impressions) > 5000
                ORDER BY total_spend DESC
            """)

            if not creatives:
                return insights

            # Top 素材
            best_creative = max(creatives, key=lambda c: c["avg_roi"] or 0)
            insights.append({
                "category": "creative_performance",
                "severity": "positive",
                "creative": best_creative["creative_name"] or best_creative["platform_creative_id"],
                "platform": best_creative["platform_name"],
                "metric": "最佳 ROI 素材",
                "value": best_creative["avg_roi"],
                "message": f"🏆 最佳素材: {best_creative['creative_name']} (ROI={best_creative['avg_roi']:.2f}, CTR={best_creative['avg_ctr']:.2f}%)",
                "action": "建议作为模板素材，复制类似创意风格",
            })

            # 疲劳素材检测
            for c in creatives:
                if c["active_days"] >= 7 and c["avg_ctr"] and c["avg_ctr"] < 1.0:
                    insights.append({
                        "category": "creative_fatigue",
                        "severity": "warning",
                        "creative": c["creative_name"] or c["platform_creative_id"],
                        "platform": c["platform_name"],
                        "metric": "素材疲劳",
                        "value": c["avg_ctr"],
                        "message": f"💤 素材疲劳: {c['creative_name'] or c['platform_creative_id']} CTR 降至 {c['avg_ctr']:.2f}% (已投放 {c['active_days']} 天)",
                        "action": "建议暂停该素材，创建新变体 A/B 测试",
                    })

        except Exception as e:
            logger.error(f"Creative lifecycle analysis failed: {e}")

        return insights

    def _analyze_region_potential(self, start_date: str, end_date: str) -> list[dict]:
        """
        地区潜力挖掘

        - 找出 CPI 低但规模小的潜力市场
        - ROI 高但投放量不足的市场
        """
        insights = []

        try:
            regions = self.db.fetch_all(f"""
                SELECT
                    c.country_code,
                    c.region,
                    c.is_tier1,
                    SUM(f.spend) AS total_spend,
                    SUM(f.installs) AS total_installs,
                    SUM(f.revenue) AS total_revenue,
                    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 4) AS cpi,
                    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi
                FROM fact_ad_performance f
                JOIN dim_country c ON f.country_id = c.country_id
                WHERE f.date_id BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY c.country_code
                HAVING total_spend > 100
                ORDER BY roi DESC
            """)

            if not regions:
                return insights

            # 平均 CPI 和 ROI
            avg_cpi = sum(r["cpi"] for r in regions) / len(regions) if regions else 1
            avg_roi = sum(r["roi"] for r in regions) / len(regions) if regions else 1
            total_spend = sum(r["total_spend"] for r in regions) or 1

            for r in regions:
                spend_pct = r["total_spend"] / total_spend * 100

                # 潜力市场: ROI > 均值 但 预算占比 < 5%
                if r["roi"] > avg_roi * 1.3 and spend_pct < 5 and r["total_spend"] > 50:
                    tier_label = "T1" if r["is_tier1"] else "T2/T3"
                    insights.append({
                        "category": "region_potential",
                        "severity": "positive",
                        "country": r["country_code"],
                        "region": r["region"],
                        "tier": tier_label,
                        "metric": "潜力市场",
                        "value": r["roi"],
                        "message": f"🌟 潜力市场: {r['country_code']} ROI={r['roi']:.2f}, CPI=${r['cpi']:.2f} (仅占预算 {spend_pct:.1f}%)",
                        "action": f"建议将 {r['country_code']} 日预算提高 2-3 倍测试放量",
                    })

                # 低效市场: 预算高但 ROI 低
                if r["roi"] < avg_roi * 0.5 and spend_pct > 15:
                    insights.append({
                        "category": "region_inefficiency",
                        "severity": "warning",
                        "country": r["country_code"],
                        "metric": "低效市场",
                        "value": r["roi"],
                        "message": f"🔻 低效市场: {r['country_code']} ROI={r['roi']:.2f} (仅 {avg_roi * 0.5:.2f})，消耗 {spend_pct:.0f}% 预算",
                        "action": f"建议削减 {r['country_code']} 预算或调整出价策略",
                    })

        except Exception as e:
            logger.error(f"Region potential analysis failed: {e}")

        return insights

    def _analyze_budget_optimization(self, start_date: str, end_date: str) -> list[dict]:
        """
        预算分配优化建议

        基于各渠道/地区的边际 ROI，给出预算调整建议
        """
        insights = []

        try:
            total_spend = self.db.fetch_one(f"""
                SELECT SUM(spend) AS total
                FROM fact_ad_performance
                WHERE date_id BETWEEN '{start_date}' AND '{end_date}'
            """)

            total = (total_spend["total"] or 0) if total_spend else 0
            if total < 1000:
                return insights

            # 模拟：如果按 ROI 比例重新分配预算
            channels = self.db.fetch_all(f"""
                SELECT p.platform_name, SUM(f.spend) AS spend, SUM(f.revenue) AS revenue,
                       ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY p.platform_code
            """)

            if len(channels) >= 2:
                total_roi_weight = sum(max(c["roi"], 0.1) for c in channels)
                optimized = []
                for c in channels:
                    weight = max(c["roi"], 0.1) / total_roi_weight
                    optimized_spend = total * weight
                    optimized.append({
                        "platform": c["platform_name"],
                        "current_spend": c["spend"],
                        "current_pct": c["spend"] / total * 100 if total > 0 else 0,
                        "suggested_spend": optimized_spend,
                        "suggested_pct": weight * 100,
                        "current_roi": c["roi"],
                    })

                # 找出调整最大的渠道
                for opt in optimized:
                    diff_pct = opt["suggested_pct"] - opt["current_pct"]
                    if abs(diff_pct) > 10 and opt["current_roi"] > 0:
                        direction = "加大" if diff_pct > 0 else "减少"
                        insights.append({
                            "category": "budget_optimization",
                            "severity": "suggestion",
                            "platform": opt["platform"],
                            "metric": "预算优化",
                            "value": diff_pct,
                            "message": f"💡 预算优化: {opt['platform']} — 建议{direction}预算占比 "
                                      f"{abs(diff_pct):.1f}个百分点 "
                                      f"(当前 {opt['current_pct']:.0f}% → 建议 {opt['suggested_pct']:.0f}%) "
                                      f"ROI={opt['current_roi']:.2f}",
                            "action": f"调整 {opt['platform']} 日预算至约 ${opt['suggested_spend']:,.0f}",
                        })

        except Exception as e:
            logger.error(f"Budget optimization failed: {e}")

        return insights

    def _deep_analysis(self, start_date: str, end_date: str) -> list[dict]:
        """
        深度分析（耗时操作）

        - 日维度 × 小时维度 趋势分解
        - 素材 A/B 测试效果统计
        - 归因窗口对比（7d click vs 1d view）
        """
        insights = []

        # 周内效应分析
        try:
            dow_perf = self.db.fetch_all(f"""
                SELECT
                    d.day_of_week,
                    AVG(f.ctr) AS avg_ctr,
                    AVG(f.roi) AS avg_roi,
                    AVG(f.cpi) AS avg_cpi,
                    SUM(f.spend) AS total_spend
                FROM fact_ad_performance f
                JOIN dim_date d ON f.date_id = d.date_id
                WHERE f.date_id BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY d.day_of_week
                ORDER BY d.day_of_week
            """)

            if dow_perf:
                # 找出最佳/最差投放日
                best_day = max(dow_perf, key=lambda d: d["avg_roi"] or 0)
                worst_day = min(dow_perf, key=lambda d: d["avg_roi"] or float("inf"))

                day_names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]

                if best_day["avg_roi"] > worst_day["avg_roi"] * 1.3:
                    insights.append({
                        "category": "weekly_pattern",
                        "severity": "suggestion",
                        "metric": "周内效应",
                        "value": best_day["avg_roi"],
                        "message": f"📅 周内效应: {day_names[best_day['day_of_week']]} ROI 最高 ({best_day['avg_roi']:.2f})，"
                                  f"{day_names[worst_day['day_of_week']]} 最低 ({worst_day['avg_roi']:.2f})",
                        "action": f"建议在 {day_names[best_day['day_of_week']]} 加大预算，{day_names[worst_day['day_of_week']]} 缩减",
                    })

        except Exception as e:
            logger.error(f"Deep analysis failed: {e}")

        return insights

    def _channel_score(self, channel: dict) -> float:
        """
        渠道综合效能评分 (0-100)

        权重：ROI 40%, CTR 20%, CVR 20%, CPI Inverse 20%
        """
        roi_score = min(channel.get("roi", 0) / 5.0, 1.0) * 40
        ctr_score = min(channel.get("ctr", 0) / 5.0, 1.0) * 20
        cvr_score = min(channel.get("cvr", 0) / 20.0, 1.0) * 20

        cpi_val = channel.get("cpi", 5)
        cpi_score = min(3.0 / max(cpi_val, 0.01), 1.0) * 20

        return round(roi_score + ctr_score + cvr_score + cpi_score, 1)

    def _build_executive_summary(self) -> str:
        """生成执行摘要"""
        positive = len([i for i in self.insights if i.get("severity") == "positive"])
        negative = len([i for i in self.insights if i.get("severity") == "negative"])
        warnings = len([i for i in self.insights if i.get("severity") == "warning"])
        suggestions = len([i for i in self.insights if i.get("severity") == "suggestion"])

        if not self.insights:
            return "未发现显著洞察。建议检查数据源连接是否正常。"

        parts = []
        if positive:
            parts.append(f"发现 {positive} 个正面信号，")
        if negative + warnings:
            parts.append(f"{negative + warnings} 个需关注的问题，")
        if suggestions:
            parts.append(f"{suggestions} 条优化建议。")
        else:
            parts.append("整体表现平稳。")

        return "".join(parts)

    def _build_recommendations(self) -> list[dict]:
        """收集所有行动建议"""
        return [
            {
                "priority": i + 1,
                "action": insight.get("action", ""),
                "related_metric": insight.get("metric", ""),
            }
            for i, insight in enumerate(self.insights)
            if insight.get("action")
        ][:5]  # Top 5

    def _print_insight_report(self, result: dict):
        """打印洞察报告"""
        print(f"\n{'=' * 70}")
        print(f"  🔬 业务洞察报告")
        print(f"  📅 分析周期: {result['period']}")
        print(f"  💡 发现洞察: {result['total_insights']} 条")
        print(f"{'=' * 70}")

        print(f"\n  📋 执行摘要:")
        print(f"  {result['executive_summary']}")

        # 分类展示
        categories = {}
        for insight in result["insights"]:
            cat = insight.get("category", "other")
            categories.setdefault(cat, []).append(insight)

        icons = {"positive": "✅", "negative": "❌", "warning": "⚠️", "suggestion": "💡"}

        for cat, items in categories.items():
            print(f"\n  [{cat.upper()}]")
            for item in items:
                icon = icons.get(item.get("severity", ""), "•")
                print(f"    {icon} {item['message']}")
                if item.get("action"):
                    print(f"       ↳ {item['action']}")

        # 行动建议
        recs = result.get("recommendations", [])
        if recs:
            print(f"\n  🎯 TOP 行动建议:")
            for rec in recs:
                print(f"    {rec['priority']}. [{rec['related_metric']}] {rec['action']}")

        print(f"\n{'=' * 70}\n")


# ==================== CLI 入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Insight Miner Agent")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--deep", action="store_true", help="Run deep analysis")
    args = parser.parse_args()

    miner = InsightMiner()
    result = miner.run(
        start_date=args.start_date,
        end_date=args.end_date,
        deep_analysis=args.deep,
    )

    sys.exit(0)
