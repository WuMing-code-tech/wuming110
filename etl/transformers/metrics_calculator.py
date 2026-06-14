"""
指标计算引擎
CPI / CPM / CTR / ROI / LTV 自动计算 & 衍生指标
"""

import logging
from typing import Optional
from config.metric_definitions import (
    cpi, cpm, ctr, roi_roas, cvr, ipm, ecpm,
    calculate_all_metrics,
    safe_divide,
)

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """
    指标计算器

    - 计算单行核心指标
    - 计算聚合指标（汇总维度后）
    - 计算趋势指标（环比、同比变化）
    - 渠道效率评分
    - 素材效果评分
    """

    def calc_row_metrics(self, row: dict) -> dict:
        """
        计算单行数据的核心指标

        Args:
            row: 标准化后的数据行（含 spend, impressions, clicks, installs, revenue）

        Returns:
            dict: 追加了 cpi, cpm, ctr, roi, cvr, ipm, ecpm
        """
        spend = row.get("spend", 0)
        impressions = row.get("impressions", 0)
        clicks = row.get("clicks", 0)
        installs = row.get("installs", 0)
        revenue = row.get("revenue", 0)

        metrics = calculate_all_metrics(
            spend=spend,
            impressions=impressions,
            clicks=clicks,
            installs=installs,
            revenue=revenue,
            revenue_d7=row.get("ltv_d7"),
            revenue_d30=row.get("ltv_d30"),
        )

        return {**row, **metrics}

    def calc_batch(self, rows: list[dict]) -> list[dict]:
        """批量计算所有行的指标"""
        return [self.calc_row_metrics(row) for row in rows]

    def aggregate(
        self,
        rows: list[dict],
        group_by: list[str],
    ) -> list[dict]:
        """
        按维度聚合计算指标

        Args:
            rows: 数据列表
            group_by: 聚合维度 ['platform_code'] / ['date_id'] / ['country_code'] / ...

        Returns:
            list[dict]: 聚合后的汇总指标
        """
        from collections import defaultdict

        agg = defaultdict(lambda: {
            "spend": 0.0,
            "impressions": 0,
            "clicks": 0,
            "installs": 0,
            "revenue": 0.0,
            "row_count": 0,
        })

        for row in rows:
            key = tuple(row.get(dim, "unknown") for dim in group_by)
            bucket = agg[key]
            bucket["spend"] += row.get("spend", 0)
            bucket["impressions"] += row.get("impressions", 0)
            bucket["clicks"] += row.get("clicks", 0)
            bucket["installs"] += row.get("installs", 0)
            bucket["revenue"] += row.get("revenue", 0)
            bucket["row_count"] += 1

        results = []
        for key, bucket in agg.items():
            dims = dict(zip(group_by, key))
            results.append({
                **dims,
                "spend": round(bucket["spend"], 2),
                "impressions": bucket["impressions"],
                "clicks": bucket["clicks"],
                "installs": bucket["installs"],
                "revenue": round(bucket["revenue"], 2),
                "cpi": cpi(bucket["spend"], bucket["installs"]),
                "cpm": cpm(bucket["spend"], bucket["impressions"]),
                "ctr": ctr(bucket["clicks"], bucket["impressions"]),
                "roi": roi_roas(bucket["revenue"], bucket["spend"]),
                "cvr": cvr(bucket["installs"], bucket["clicks"]),
                "ipm": ipm(bucket["installs"], bucket["impressions"]),
                "ecpm": ecpm(bucket["revenue"], bucket["impressions"]),
                "row_count": bucket["row_count"],
            })

        return results

    def calc_trend(
        self,
        current_metrics: dict,
        previous_metrics: dict,
    ) -> dict:
        """
        计算指标趋势（环比变化）

        Args:
            current_metrics: 当前周期指标 {'cpi': 1.5, 'roi': 2.3, ...}
            previous_metrics: 上周期指标

        Returns:
            dict: 每个指标的变化百分比
        """
        trends = {}
        for key in current_metrics:
            cur = current_metrics.get(key, 0)
            prev = previous_metrics.get(key, 0)
            if prev and prev != 0:
                trends[f"{key}_change_pct"] = round((cur - prev) / prev * 100, 2)
            else:
                trends[f"{key}_change_pct"] = 0.0
        return trends

    def channel_efficiency_score(
        self,
        channel_metrics: dict,
    ) -> float:
        """
        渠道效能综合评分（0-100）

        综合考虑 ROI、CPI、CTR、CVR，加权计算效率分

        Args:
            channel_metrics: {'roi': 2.5, 'cpi': 1.2, 'ctr': 3.5, 'cvr': 8.2}

        Returns:
            float: 综合评分 (0-100)
        """
        scores = {
            "roi": min(channel_metrics.get("roi", 0) / 5.0, 1.0) * 40,   # ROI 权重 40%
            "ctr": min(channel_metrics.get("ctr", 0) / 10.0, 1.0) * 20,  # CTR 权重 20%
            "cvr": min(channel_metrics.get("cvr", 0) / 20.0, 1.0) * 20,  # CVR 权重 20%
            "cpi_inverse": min(3.0 / max(channel_metrics.get("cpi", 1), 0.01), 1.0) * 20,  # CPI 倒数 权重 20%
        }
        return round(sum(scores.values()), 1)

    def creative_fatigue_score(
        self,
        ctr_trend: list[float],
    ) -> float:
        """
        素材疲劳度评分

        通过最近 N 天 CTR 趋势判断素材是否疲劳

        Args:
            ctr_trend: [day1_ctr, day2_ctr, ...] 最近 N 天 CTR 序列

        Returns:
            float: 疲劳度 0-100，越高越疲劳
        """
        if len(ctr_trend) < 3:
            return 0.0

        # 线性回归斜率
        n = len(ctr_trend)
        x_mean = (n - 1) / 2
        y_mean = sum(ctr_trend) / n

        numerator = sum((i - x_mean) * (ctr_trend[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0

        slope = numerator / denominator

        # 斜率越负越疲劳（CTR 下降趋势）
        if slope >= 0:
            return 0.0

        # 归一化到 0-100
        avg_ctr = max(y_mean, 0.01)
        # Normalize against a reference CTR of 5%
        fatigue_rate = min(abs(slope) / 0.05 * 100, 100)
        return round(fatigue_rate, 1)

    def roi_alert_level(self, roi: float, threshold: float = 1.0) -> str:
        """
        ROI 预警等级

        Returns:
            'critical' | 'warning' | 'normal'
        """
        if roi < threshold * 0.5:
            return "critical"
        elif roi < threshold:
            return "warning"
        else:
            return "normal"
