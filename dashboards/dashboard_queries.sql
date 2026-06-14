-- ============================================================
-- Metabase 看板核心 SQL 查询集合
-- 所有查询均可直接在 Metabase SQL 编辑器中执行
-- ============================================================

-- ============================================================
-- 1. 总览 — 核心 KPI 单值卡片
-- ============================================================

-- 1.1 今日总花费
SELECT ROUND(SUM(spend), 2) AS total_spend
FROM fact_ad_performance
WHERE date_id = (SELECT MAX(date_id) FROM fact_ad_performance);

-- 1.2 今日总安装
SELECT SUM(installs) AS total_installs
FROM fact_ad_performance
WHERE date_id = (SELECT MAX(date_id) FROM fact_ad_performance);

-- 1.3 今日总收入
SELECT ROUND(SUM(revenue), 2) AS total_revenue
FROM fact_ad_performance
WHERE date_id = (SELECT MAX(date_id) FROM fact_ad_performance);

-- 1.4 今日综合 CPI
SELECT ROUND(SUM(spend) * 1.0 / NULLIF(SUM(installs), 0), 2) AS overall_cpi
FROM fact_ad_performance
WHERE date_id = (SELECT MAX(date_id) FROM fact_ad_performance);

-- 1.5 今日综合 CPM
SELECT ROUND(SUM(spend) * 1000.0 / NULLIF(SUM(impressions), 0), 2) AS overall_cpm
FROM fact_ad_performance
WHERE date_id = (SELECT MAX(date_id) FROM fact_ad_performance);

-- 1.6 今日综合 CTR
SELECT ROUND(SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0), 2) AS overall_ctr
FROM fact_ad_performance
WHERE date_id = (SELECT MAX(date_id) FROM fact_ad_performance);

-- 1.7 今日综合 ROI
SELECT ROUND(SUM(revenue) * 1.0 / NULLIF(SUM(spend), 0), 2) AS overall_roi
FROM fact_ad_performance
WHERE date_id = (SELECT MAX(date_id) FROM fact_ad_performance);

-- ============================================================
-- 2. 全维度 KPI 明细表 (近 30 天)
-- ============================================================

SELECT
    f.date_id AS Date,
    p.platform_name AS Platform,
    c.country_code AS Country,
    cr.creative_name AS Creative,
    f.impressions,
    f.clicks,
    f.installs,
    ROUND(f.spend, 2) AS spend,
    ROUND(f.revenue, 2) AS revenue,
    ROUND(f.cpi, 2) AS CPI,
    ROUND(f.cpm, 2) AS CPM,
    ROUND(f.ctr, 2) AS CTR_pct,
    ROUND(f.roi, 2) AS ROI,
    ROUND(f.cvr, 2) AS CVR_pct
FROM fact_ad_performance f
JOIN dim_platform p ON f.platform_id = p.platform_id
LEFT JOIN dim_country c ON f.country_id = c.country_id
LEFT JOIN dim_creative cr ON f.creative_id = cr.creative_id
WHERE f.date_id >= date('now', '-30 days')
ORDER BY f.date_id DESC, p.platform_name;

-- ============================================================
-- 3. 渠道对比 — 近 7 天汇总
-- ============================================================

SELECT
    p.platform_name AS Channel,
    COUNT(DISTINCT f.date_id) AS 'Active Days',
    SUM(f.impressions) AS Impressions,
    SUM(f.clicks) AS Clicks,
    SUM(f.installs) AS Installs,
    ROUND(SUM(f.spend), 2) AS Spend,
    ROUND(SUM(f.revenue), 2) AS Revenue,
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 2) AS CPI,
    ROUND(SUM(f.spend) * 1000.0 / NULLIF(SUM(f.impressions), 0), 2) AS CPM,
    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 2) AS CTR,
    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 2) AS ROI
FROM fact_ad_performance f
JOIN dim_platform p ON f.platform_id = p.platform_id
WHERE f.date_id >= date('now', '-7 days')
GROUP BY p.platform_name
ORDER BY Spend DESC;

-- ============================================================
-- 4. 地区维度 — 大区汇总
-- ============================================================

SELECT
    c.region AS Region,
    COUNT(DISTINCT c.country_code) AS Countries,
    ROUND(SUM(f.spend), 2) AS Spend,
    SUM(f.installs) AS Installs,
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 2) AS CPI,
    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 2) AS ROI
FROM fact_ad_performance f
JOIN dim_country c ON f.country_id = c.country_id
WHERE f.date_id >= date('now', '-30 days')
GROUP BY c.region
ORDER BY Spend DESC;

-- ============================================================
-- 5. 地区维度 — Top 10 国家 (按花费)
-- ============================================================

SELECT
    c.country_code AS Country,
    c.region AS Region,
    CASE c.is_tier1 WHEN 1 THEN 'T1' ELSE 'T2/T3' END AS Tier,
    ROUND(SUM(f.spend), 2) AS Spend,
    SUM(f.installs) AS Installs,
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 2) AS CPI,
    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 2) AS CTR,
    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 2) AS ROI
FROM fact_ad_performance f
JOIN dim_country c ON f.country_id = c.country_id
WHERE f.date_id >= date('now', '-30 days')
GROUP BY c.country_code
ORDER BY Spend DESC
LIMIT 10;

-- ============================================================
-- 6. 素材排行 — Top 10 素材 (按 ROI)
-- ============================================================

SELECT
    cr.creative_name AS Creative,
    cr.creative_type AS Type,
    p.platform_name AS Platform,
    ROUND(SUM(f.spend), 2) AS Spend,
    SUM(f.installs) AS Installs,
    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 2) AS CTR,
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 2) AS CPI,
    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 2) AS ROI
FROM fact_ad_performance f
JOIN dim_creative cr ON f.creative_id = cr.creative_id
JOIN dim_platform p ON f.platform_id = p.platform_id
WHERE f.date_id >= date('now', '-30 days')
  AND cr.creative_name IS NOT NULL
GROUP BY cr.platform_creative_id
ORDER BY ROI DESC
LIMIT 10;

-- ============================================================
-- 7. LTV 分析 — 按媒体来源的 LTV 和留存
-- ============================================================

SELECT
    media_source AS Source,
    COUNT(DISTINCT date_id) AS Days,
    SUM(installs) AS Installs,
    ROUND(AVG(ltv_d0), 4) AS 'LTV D0 ($)',
    ROUND(AVG(ltv_d7), 4) AS 'LTV D7 ($)',
    ROUND(AVG(ltv_d30), 4) AS 'LTV D30 ($)',
    ROUND(AVG(retention_d1), 2) AS 'Ret D1 (%)',
    ROUND(AVG(retention_d7), 2) AS 'Ret D7 (%)',
    ROUND(AVG(retention_d30), 2) AS 'Ret D30 (%)'
FROM fact_attribution
WHERE date_id >= date('now', '-30 days')
GROUP BY media_source
ORDER BY AVG(ltv_d30) DESC;

-- ============================================================
-- 8. 预警 — ROI 低于阈值的 Campaign
-- ============================================================

SELECT
    c.campaign_name AS Campaign,
    p.platform_name AS Platform,
    ROUND(SUM(f.spend), 2) AS Spend,
    ROUND(SUM(f.revenue), 2) AS Revenue,
    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 2) AS ROI,
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 2) AS CPI,
    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 2) AS CTR
FROM fact_ad_performance f
JOIN dim_campaign c ON f.campaign_id = c.campaign_id
JOIN dim_platform p ON f.platform_id = p.platform_id
WHERE f.date_id = (SELECT MAX(date_id) FROM fact_ad_performance)
  AND SUM(f.spend) > 100
GROUP BY c.campaign_name, p.platform_name
HAVING ROI < 1.0
ORDER BY ROI ASC;

-- ============================================================
-- 9. 逐日趋势 — CPI 30 天走势
-- ============================================================

SELECT
    f.date_id AS Date,
    p.platform_name AS Platform,
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 2) AS CPI
FROM fact_ad_performance f
JOIN dim_platform p ON f.platform_id = p.platform_id
WHERE f.date_id >= date('now', '-30 days')
GROUP BY f.date_id, p.platform_name
ORDER BY f.date_id;

-- ============================================================
-- 10. 花费波动 — 今日 vs 昨日对比
-- ============================================================

WITH today AS (
    SELECT p.platform_name, SUM(f.spend) AS spend
    FROM fact_ad_performance f
    JOIN dim_platform p ON f.platform_id = p.platform_id
    WHERE f.date_id = (SELECT MAX(date_id) FROM fact_ad_performance)
    GROUP BY p.platform_name
),
yesterday AS (
    SELECT p.platform_name, SUM(f.spend) AS spend
    FROM fact_ad_performance f
    JOIN dim_platform p ON f.platform_id = p.platform_id
    WHERE f.date_id = (SELECT MAX(date_id) FROM fact_ad_performance WHERE date_id < (SELECT MAX(date_id) FROM fact_ad_performance))
    GROUP BY p.platform_name
)
SELECT
    t.platform_name AS Platform,
    ROUND(t.spend, 0) AS Today_Spend,
    ROUND(y.spend, 0) AS Yesterday_Spend,
    ROUND((t.spend - y.spend) * 100.0 / NULLIF(y.spend, 0), 1) AS Change_Pct
FROM today t
LEFT JOIN yesterday y ON t.platform_name = y.platform_name;

-- ============================================================
-- 11. 素材疲劳度 — CTR 连续下降的素材
-- ============================================================

SELECT
    cr.creative_name,
    p.platform_name,
    COUNT(DISTINCT f.date_id) AS active_days,
    AVG(f.ctr) AS avg_ctr,
    -- 最近 3 天 vs 前 3 天 CTR 对比
    (SELECT AVG(f2.ctr) FROM fact_ad_performance f2
     WHERE f2.creative_id = f.creative_id
       AND f2.date_id IN (SELECT date_id FROM (SELECT DISTINCT date_id FROM fact_ad_performance ORDER BY date_id DESC LIMIT 3))
    ) AS recent_ctr,
    (SELECT AVG(f2.ctr) FROM fact_ad_performance f2
     WHERE f2.creative_id = f.creative_id
       AND f2.date_id IN (SELECT date_id FROM dim_date WHERE date_id NOT IN (SELECT date_id FROM (SELECT DISTINCT date_id FROM fact_ad_performance ORDER BY date_id DESC LIMIT 3)) ORDER BY date_id DESC LIMIT 3)
    ) AS prev_ctr
FROM fact_ad_performance f
JOIN dim_creative cr ON f.creative_id = cr.creative_id
JOIN dim_platform p ON f.platform_id = p.platform_id
WHERE f.date_id >= date('now', '-14 days')
  AND cr.creative_name IS NOT NULL
GROUP BY cr.platform_creative_id
HAVING active_days >= 5 AND recent_ctr < prev_ctr * 0.8
ORDER BY recent_ctr ASC;
