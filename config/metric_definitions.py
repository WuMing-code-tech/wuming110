"""
指标口径定义
CPI / CPM / CTR / ROI (ROAS) / LTV 的标准计算公式

所有指标计算均采用统一口径，货币单位统一为 USD。
"""

import math
from typing import Optional


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    安全除法，避免 ZeroDivisionError
    分母为 0 或 NaN 时返回 default
    """
    if denominator == 0 or math.isnan(denominator) or numerator is None or denominator is None:
        return default
    result = numerator / denominator
    return 0.0 if math.isnan(result) else result


def cpi(spend: float, installs: int) -> float:
    """
    Cost Per Install — 单次安装成本
    计算公式: SUM(spend) / SUM(installs)

    Args:
        spend: 广告花费 (USD)
        installs: 安装量

    Returns:
        CPI (USD)，若 installs=0 返回 0
    """
    return safe_divide(spend, installs)


def cpm(spend: float, impressions: int) -> float:
    """
    Cost Per Mille — 千次展示成本
    计算公式: SUM(spend) / SUM(impressions) × 1000

    Args:
        spend: 广告花费 (USD)
        impressions: 展示量

    Returns:
        CPM (USD)，若 impressions=0 返回 0
    """
    if impressions == 0:
        return 0.0
    return safe_divide(spend, impressions) * 1000


def ctr(clicks: int, impressions: int) -> float:
    """
    Click-Through Rate — 点击率
    计算公式: SUM(clicks) / SUM(impressions) × 100%

    Args:
        clicks: 点击量
        impressions: 展示量

    Returns:
        CTR (%)，若 impressions=0 返回 0.0
    """
    if impressions == 0:
        return 0.0
    return safe_divide(clicks, impressions) * 100


def roi_roas(revenue: float, spend: float) -> float:
    """
    Return on Investment (ROAS) — 广告支出回报率
    计算公式: SUM(revenue) / SUM(spend)

    Args:
        revenue: 广告带来的收入 (USD)
        spend: 广告花费 (USD)

    Returns:
        ROAS (倍数)，若 spend=0 返回 0.0
    """
    return safe_divide(revenue, spend)


def ltv_d0(day0_revenue: float, day0_installs: int) -> float:
    """
    LTV D0 — 安装当日人均收入
    计算公式: SUM(day0_revenue) / SUM(day0_installs)
    """
    return safe_divide(day0_revenue, day0_installs)


def ltv_d7(total_revenue_d7: float, installs: int) -> float:
    """
    LTV D7 — 安装后 7 日内人均收入
    计算公式: SUM(total_revenue_d7) / SUM(installs)
    """
    return safe_divide(total_revenue_d7, installs)


def ltv_d30(total_revenue_d30: float, installs: int) -> float:
    """
    LTV D30 — 安装后 30 日内人均收入
    计算公式: SUM(total_revenue_d30) / SUM(installs)
    """
    return safe_divide(total_revenue_d30, installs)


def ecpm(revenue: float, impressions: int) -> float:
    """
    Effective CPM — 有效千次展示收入
    计算公式: SUM(revenue) / SUM(impressions) × 1000
    """
    if impressions == 0:
        return 0.0
    return safe_divide(revenue, impressions) * 1000


def cvr(installs: int, clicks: int) -> float:
    """
    Conversion Rate — 转化率 (点击 → 安装)
    计算公式: SUM(installs) / SUM(clicks) × 100%
    """
    if clicks == 0:
        return 0.0
    return safe_divide(installs, clicks) * 100


def ipm(installs: int, impressions: int) -> float:
    """
    Installs Per Mille — 千次展示安装量
    计算公式: SUM(installs) / SUM(impressions) × 1000
    """
    if impressions == 0:
        return 0.0
    return safe_divide(installs, impressions) * 1000


# ==================== 聚合计算便捷函数 ====================


def calculate_all_metrics(
    spend: float,
    impressions: int,
    clicks: int,
    installs: int,
    revenue: float,
    revenue_d7: Optional[float] = None,
    revenue_d30: Optional[float] = None,
) -> dict:
    """
    一次性计算所有核心指标

    Returns:
        dict with keys: cpi, cpm, ctr, roi, cvr, ipm, ecpm, ltv_d0, ltv_d7, ltv_d30
    """
    metrics = {
        "cpi": cpi(spend, installs),
        "cpm": cpm(spend, impressions),
        "ctr": ctr(clicks, impressions),
        "roi": roi_roas(revenue, spend),
        "cvr": cvr(installs, clicks),
        "ipm": ipm(installs, impressions),
        "ecpm": ecpm(revenue, impressions),
    }

    if revenue_d7 is not None:
        metrics["ltv_d7"] = ltv_d7(revenue_d7, installs)
    if revenue_d30 is not None:
        metrics["ltv_d30"] = ltv_d30(revenue_d30, installs)

    return metrics
