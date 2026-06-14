-- ============================================================
-- 海外广告投流数据分析 — SQLite 数据库 Schema
-- 星型模型：事实表 + 维度表 + 物化视图
-- ============================================================

-- ==================== 维度表 ====================

-- 日期维度表
CREATE TABLE IF NOT EXISTS dim_date (
    date_id TEXT PRIMARY KEY,              -- YYYY-MM-DD
    date_date TEXT NOT NULL,               -- 日期
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,              -- 1-4
    month INTEGER NOT NULL,                -- 1-12
    week_of_year INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,          -- 0=Sunday, 6=Saturday
    day_of_month INTEGER NOT NULL,
    is_weekend INTEGER NOT NULL DEFAULT 0, -- 1=周末
    is_holiday INTEGER NOT NULL DEFAULT 0, -- 1=节假日
    week_start_date TEXT,                  -- 所属周周一日期
    month_start_date TEXT                  -- 所属月1日
);

-- 广告平台维度表
CREATE TABLE IF NOT EXISTS dim_platform (
    platform_id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_code TEXT NOT NULL UNIQUE,    -- meta / tiktok / google
    platform_name TEXT NOT NULL,           -- Meta Ads / TikTok Ads / Google Ads
    api_base_url TEXT,
    data_retention_days INTEGER DEFAULT 365
);

INSERT OR IGNORE INTO dim_platform (platform_code, platform_name, data_retention_days)
VALUES
    ('meta', 'Meta Ads', 365),
    ('tiktok', 'TikTok Ads', 365),
    ('google', 'Google Ads', 365);

-- 广告系列维度表
CREATE TABLE IF NOT EXISTS dim_campaign (
    campaign_id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_campaign_id TEXT NOT NULL,    -- 平台侧 Campaign ID
    platform_id INTEGER NOT NULL,          -- FK dim_platform
    campaign_name TEXT NOT NULL,
    objective TEXT,                        -- APP_INSTALLS / LINK_CLICKS / CONVERSIONS
    status TEXT,                           -- ACTIVE / PAUSED / DELETED
    budget_daily REAL,                     -- 日预算 (USD)
    budget_lifetime REAL,                  -- 生命周期预算 (USD)
    bidding_strategy TEXT,                 -- LOWEST_COST / COST_CAP
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (platform_id) REFERENCES dim_platform(platform_id),
    UNIQUE(platform_campaign_id, platform_id)
);

-- 广告维度表
CREATE TABLE IF NOT EXISTS dim_ad (
    ad_id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_ad_id TEXT NOT NULL,          -- 平台侧 Ad ID
    platform_campaign_id TEXT NOT NULL,    -- 平台侧 Campaign ID
    platform_id INTEGER NOT NULL,
    ad_name TEXT NOT NULL,
    creative_id INTEGER,                   -- FK dim_creative (nullable: 先拉数据再关联)
    status TEXT,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (platform_id) REFERENCES dim_platform(platform_id),
    UNIQUE(platform_ad_id, platform_id)
);

-- 素材维度表
CREATE TABLE IF NOT EXISTS dim_creative (
    creative_id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_creative_id TEXT NOT NULL,
    platform_id INTEGER NOT NULL,
    creative_name TEXT,
    creative_type TEXT,                    -- IMAGE / VIDEO / CAROUSEL
    image_url TEXT,
    video_url TEXT,
    headline TEXT,
    body_text TEXT,
    cta_text TEXT,                         -- Call to Action
    aspect_ratio TEXT,                     -- 1:1 / 9:16 / 16:9
    duration_seconds REAL,                 -- 视频时长 (秒)
    created_at TEXT,
    FOREIGN KEY (platform_id) REFERENCES dim_platform(platform_id),
    UNIQUE(platform_creative_id, platform_id)
);

-- 国家/地区维度表
CREATE TABLE IF NOT EXISTS dim_country (
    country_id INTEGER PRIMARY KEY AUTOINCREMENT,
    country_code TEXT NOT NULL UNIQUE,     -- ISO 3166-1 alpha-2 (US, CN, JP...)
    country_name TEXT NOT NULL,
    region TEXT,                           -- APAC / EMEA / LATAM / NA
    timezone TEXT,                         -- America/New_York, Asia/Shanghai...
    currency_code TEXT DEFAULT 'USD',      -- 本地货币
    currency_to_usd_rate REAL DEFAULT 1.0, -- 兑 USD 汇率
    is_tier1 INTEGER DEFAULT 0            -- T1 国家标记
);

-- 产品/应用维度表
CREATE TABLE IF NOT EXISTS dim_product (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    appsflyer_app_id TEXT UNIQUE,          -- AppsFlyer 上的 App ID
    product_name TEXT NOT NULL,
    platform_os TEXT,                      -- iOS / Android
    bundle_id TEXT,                        -- com.example.app
    category TEXT,                         -- Game / Social / Utility
    current_version TEXT
);

-- ==================== 事实表 ====================

-- 广告效果事实表 (按 日期 × 广告 × 国家 × 平台 粒度)
CREATE TABLE IF NOT EXISTS fact_ad_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id TEXT NOT NULL,                 -- FK dim_date YYYY-MM-DD
    platform_id INTEGER NOT NULL,          -- FK dim_platform
    campaign_id INTEGER,                   -- FK dim_campaign (本地方便查询)
    ad_id INTEGER,                         -- FK dim_ad
    creative_id INTEGER,                   -- FK dim_creative
    country_id INTEGER,                    -- FK dim_country
    product_id INTEGER,                    -- FK dim_product

    -- 效果指标 (原始值)
    impressions INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    spend REAL DEFAULT 0.0,               -- USD
    installs INTEGER DEFAULT 0,           -- 平台侧归因安装 (非 MMP)
    revenue REAL DEFAULT 0.0,             -- 平台侧归因收入 (USD)
    video_views INTEGER DEFAULT 0,
    video_views_25pct INTEGER DEFAULT 0,
    video_views_50pct INTEGER DEFAULT 0,
    video_views_75pct INTEGER DEFAULT 0,
    video_views_100pct INTEGER DEFAULT 0,

    -- 计算指标 (冗余存储，加速查询)
    cpi REAL DEFAULT 0.0,
    cpm REAL DEFAULT 0.0,
    ctr REAL DEFAULT 0.0,
    roi REAL DEFAULT 0.0,
    cvr REAL DEFAULT 0.0,

    -- 元数据
    data_source TEXT DEFAULT 'api',        -- api / csv / manual
    fetched_at TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
    FOREIGN KEY (platform_id) REFERENCES dim_platform(platform_id),
    FOREIGN KEY (campaign_id) REFERENCES dim_campaign(campaign_id),
    FOREIGN KEY (ad_id) REFERENCES dim_ad(ad_id),
    FOREIGN KEY (creative_id) REFERENCES dim_creative(creative_id),
    FOREIGN KEY (country_id) REFERENCES dim_country(country_id),
    FOREIGN KEY (product_id) REFERENCES dim_product(product_id),

    UNIQUE(date_id, platform_id, ad_id, country_id, product_id)
);

-- 归因事实表 (AppsFlyer 数据，按 日期 × 媒体来源 × 国家 × 产品 粒度)
CREATE TABLE IF NOT EXISTS fact_attribution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_id TEXT NOT NULL,                 -- FK dim_date YYYY-MM-DD
    platform_id INTEGER,                   -- FK dim_platform (media_source 映射)
    campaign_id INTEGER,                   -- FK dim_campaign
    ad_id INTEGER,                         -- FK dim_ad
    country_id INTEGER,                    -- FK dim_country
    product_id INTEGER,                    -- FK dim_product

    -- 原始归因指标
    installs INTEGER DEFAULT 0,            -- MMP 归因安装
    uninstalls INTEGER DEFAULT 0,          -- 卸载量
    events INTEGER DEFAULT 0,              -- 自定义事件总次数
    attributed_revenue REAL DEFAULT 0.0,   -- 归因收入 (USD)
    ad_revenue REAL DEFAULT 0.0,           -- 广告变现收入 (USD)
    iap_revenue REAL DEFAULT 0.0,          -- 内购收入 (USD)
    sessions INTEGER DEFAULT 0,            -- 会话数
    retention_d1 REAL DEFAULT 0.0,         -- D1 留存率
    retention_d3 REAL DEFAULT 0.0,         -- D3 留存率
    retention_d7 REAL DEFAULT 0.0,         -- D7 留存率
    retention_d30 REAL DEFAULT 0.0,        -- D30 留存率

    -- LTV 指标 (USD，人均)
    ltv_d0 REAL DEFAULT 0.0,
    ltv_d7 REAL DEFAULT 0.0,
    ltv_d30 REAL DEFAULT 0.0,
    ltv_d90 REAL DEFAULT 0.0,

    -- 媒体来源
    media_source TEXT,                     -- facebook / tiktok / google / organic
    campaign_name TEXT,                    -- 广告系列名称
    adset_name TEXT,                       -- 广告组名称

    -- 元数据
    fetched_at TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
    FOREIGN KEY (platform_id) REFERENCES dim_platform(platform_id),
    FOREIGN KEY (campaign_id) REFERENCES dim_campaign(campaign_id),
    FOREIGN KEY (ad_id) REFERENCES dim_ad(ad_id),
    FOREIGN KEY (country_id) REFERENCES dim_country(country_id),
    FOREIGN KEY (product_id) REFERENCES dim_product(product_id),

    UNIQUE(date_id, media_source, campaign_name, adset_name, country_id, product_id)
);

-- ==================== 索引 ====================

CREATE INDEX IF NOT EXISTS idx_fact_ad_date ON fact_ad_performance(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_ad_platform ON fact_ad_performance(platform_id);
CREATE INDEX IF NOT EXISTS idx_fact_ad_campaign ON fact_ad_performance(campaign_id);
CREATE INDEX IF NOT EXISTS idx_fact_ad_country ON fact_ad_performance(country_id);
CREATE INDEX IF NOT EXISTS idx_fact_ad_date_platform ON fact_ad_performance(date_id, platform_id);

CREATE INDEX IF NOT EXISTS idx_fact_attr_date ON fact_attribution(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_attr_platform ON fact_attribution(platform_id);
CREATE INDEX IF NOT EXISTS idx_fact_attr_source ON fact_attribution(media_source);
CREATE INDEX IF NOT EXISTS idx_fact_attr_date_source ON fact_attribution(date_id, media_source);

-- ==================== 物化视图 ====================

-- 每日核心 KPI 汇总视图
CREATE VIEW IF NOT EXISTS mv_daily_kpi AS
SELECT
    f.date_id,
    p.platform_code,
    p.platform_name,
    SUM(f.impressions) AS total_impressions,
    SUM(f.clicks) AS total_clicks,
    SUM(f.installs) AS total_installs,
    ROUND(SUM(f.spend), 2) AS total_spend,
    ROUND(SUM(f.revenue), 2) AS total_revenue,
    -- CPI
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 4) AS cpi,
    -- CPM
    ROUND(SUM(f.spend) * 1000.0 / NULLIF(SUM(f.impressions), 0), 4) AS cpm,
    -- CTR (%)
    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 4) AS ctr,
    -- ROI
    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi,
    -- CVR (%)
    ROUND(SUM(f.installs) * 100.0 / NULLIF(SUM(f.clicks), 0), 4) AS cvr,
    -- eCPM
    ROUND(SUM(f.revenue) * 1000.0 / NULLIF(SUM(f.impressions), 0), 4) AS ecpm
FROM fact_ad_performance f
JOIN dim_platform p ON f.platform_id = p.platform_id
GROUP BY f.date_id, p.platform_code, p.platform_name
ORDER BY f.date_id DESC, p.platform_code;

-- 渠道对比视图
CREATE VIEW IF NOT EXISTS mv_channel_compare AS
SELECT
    p.platform_code,
    p.platform_name,
    COUNT(DISTINCT f.date_id) AS active_days,
    SUM(f.impressions) AS total_impressions,
    SUM(f.clicks) AS total_clicks,
    SUM(f.installs) AS total_installs,
    ROUND(SUM(f.spend), 2) AS total_spend,
    ROUND(SUM(f.revenue), 2) AS total_revenue,
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 4) AS avg_cpi,
    ROUND(SUM(f.spend) * 1000.0 / NULLIF(SUM(f.impressions), 0), 4) AS avg_cpm,
    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 4) AS avg_ctr,
    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS avg_roi,
    ROUND(SUM(f.installs) * 100.0 / NULLIF(SUM(f.clicks), 0), 4) AS avg_cvr
FROM fact_ad_performance f
JOIN dim_platform p ON f.platform_id = p.platform_id
GROUP BY p.platform_code, p.platform_name;

-- 素材效果排行视图
CREATE VIEW IF NOT EXISTS mv_creative_top AS
SELECT
    c.creative_name,
    c.creative_type,
    p.platform_name,
    SUM(f.impressions) AS total_impressions,
    SUM(f.clicks) AS total_clicks,
    SUM(f.installs) AS total_installs,
    ROUND(SUM(f.spend), 2) AS total_spend,
    ROUND(SUM(f.revenue), 2) AS total_revenue,
    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 4) AS ctr,
    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 4) AS cpi,
    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi
FROM fact_ad_performance f
JOIN dim_creative c ON f.creative_id = c.creative_id
JOIN dim_platform p ON f.platform_id = p.platform_id
GROUP BY c.creative_name, c.creative_type, p.platform_name
ORDER BY total_spend DESC;
