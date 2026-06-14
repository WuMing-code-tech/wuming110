"""
全局配置管理
从环境变量读取各广告平台 API 配置、数据库路径、预警阈值等
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Settings:
    """应用全局配置"""

    # ==================== 项目路径 ====================
    PROJECT_ROOT: Path = PROJECT_ROOT
    DB_DIR: Path = PROJECT_ROOT / "db"
    SQLITE_DB_PATH: str = os.getenv("SQLITE_DB_PATH", str(DB_DIR / "ad_performance.db"))

    # ==================== Meta Ads ====================
    META_APP_ID: str = os.getenv("META_APP_ID", "")
    META_APP_SECRET: str = os.getenv("META_APP_SECRET", "")
    META_ACCESS_TOKEN: str = os.getenv("META_ACCESS_TOKEN", "")
    META_AD_ACCOUNT_ID: str = os.getenv("META_AD_ACCOUNT_ID", "")
    META_API_VERSION: str = os.getenv("META_API_VERSION", "v19.0")
    META_API_BASE_URL: str = f"https://graph.facebook.com/{META_API_VERSION}"

    # ==================== DeepSeek API ====================
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    
    # ==================== TikTok Ads ====================
    TIKTOK_APP_ID: str = os.getenv("TIKTOK_APP_ID", "")
    TIKTOK_APP_SECRET: str = os.getenv("TIKTOK_APP_SECRET", "")
    TIKTOK_ACCESS_TOKEN: str = os.getenv("TIKTOK_ACCESS_TOKEN", "")
    TIKTOK_ADVERTISER_ID: str = os.getenv("TIKTOK_ADVERTISER_ID", "")
    TIKTOK_API_BASE_URL: str = "https://business-api.tiktok.com/open_api/v1.3"

    # ==================== Google Ads ====================
    GOOGLE_ADS_CLIENT_ID: str = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
    GOOGLE_ADS_CLIENT_SECRET: str = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
    GOOGLE_ADS_DEVELOPER_TOKEN: str = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    GOOGLE_ADS_REFRESH_TOKEN: str = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")
    GOOGLE_ADS_CUSTOMER_ID: str = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "")
    GOOGLE_ADS_MANAGER_CUSTOMER_ID: str = os.getenv("GOOGLE_ADS_MANAGER_CUSTOMER_ID", "")

    # ==================== AppsFlyer ====================
    APPSFLYER_API_KEY: str = os.getenv("APPSFLYER_API_KEY", "")
    APPSFLYER_APP_IDS: list = os.getenv("APPSFLYER_APP_IDS", "").split(",") if os.getenv("APPSFLYER_APP_IDS") else []
    APPSFLYER_BASE_URL: str = os.getenv("APPSFLYER_BASE_URL", "https://hq.appsflyer.com")

    # ==================== 数据库 ====================
    SQLITE_ECHO: bool = os.getenv("SQLITE_ECHO", "false").lower() == "true"

    # ==================== 报表配置 ====================
    DEFAULT_CURRENCY: str = os.getenv("DEFAULT_CURRENCY", "USD")
    ALERT_ROI_THRESHOLD: float = float(os.getenv("ALERT_ROI_THRESHOLD", "1.0"))
    ALERT_FLUCTUATION_THRESHOLD: float = float(os.getenv("ALERT_FLUCTUATION_THRESHOLD", "0.30"))
    DAILY_BUDGET_WARNING: float = float(os.getenv("DAILY_BUDGET_WARNING", "0.85"))

    # ==================== Metabase ====================
    METABASE_URL: str = os.getenv("METABASE_URL", "http://localhost:3000")
    METABASE_EMAIL: str = os.getenv("METABASE_EMAIL", "admin@example.com")
    METABASE_PASSWORD: str = os.getenv("METABASE_PASSWORD", "admin123")
    METABASE_DATABASE_NAME: str = os.getenv("METABASE_DATABASE_NAME", "AD Performance DB")


# 全局单例
settings = Settings()
