"""
数据源连接器包初始化
提供统一的数据源工厂函数
"""

from connectors.base import BaseConnector, APIError, APIAuthError, APIRateLimitError, DataSourceError
from connectors.meta_ads import MetaAdsConnector
from connectors.tiktok_ads import TikTokAdsConnector
from connectors.google_ads import GoogleAdsConnector
from connectors.appsflyer import AppsFlyerConnector
from config.settings import settings


__all__ = [
    "BaseConnector",
    "MetaAdsConnector",
    "TikTokAdsConnector",
    "GoogleAdsConnector",
    "AppsFlyerConnector",
    "APIError",
    "APIAuthError",
    "APIRateLimitError",
    "DataSourceError",
    "get_connector",
    "get_all_connectors",
]


def get_connector(platform: str, **kwargs):
    """
    平台连接器工厂函数

    Args:
        platform: 'meta' | 'tiktok' | 'google' | 'appsflyer'
        **kwargs: 覆盖默认配置的参数

    Returns:
        BaseConnector 子类实例

    Raises:
        ValueError: 未知平台
    """
    connectors_map = {
        "meta": MetaAdsConnector,
        "tiktok": TikTokAdsConnector,
        "google": GoogleAdsConnector,
        "appsflyer": AppsFlyerConnector,
    }

    connector_class = connectors_map.get(platform.lower())
    if not connector_class:
        raise ValueError(f"Unknown platform: {platform}. Available: {list(connectors_map.keys())}")

    return connector_class(**kwargs)


def get_all_connectors(authenticate: bool = False) -> dict:
    """
    获取所有已配置的连接器

    Args:
        authenticate: 是否立即验证认证

    Returns:
        dict: {platform_code: connector_instance}
    """
    connectors = {}

    # Meta Ads
    if settings.META_ACCESS_TOKEN:
        connectors["meta"] = MetaAdsConnector()

    # TikTok Ads
    if settings.TIKTOK_ACCESS_TOKEN:
        connectors["tiktok"] = TikTokAdsConnector()

    # Google Ads
    if settings.GOOGLE_ADS_REFRESH_TOKEN:
        connectors["google"] = GoogleAdsConnector()

    # AppsFlyer
    if settings.APPSFLYER_API_KEY:
        connectors["appsflyer"] = AppsFlyerConnector()

    if authenticate:
        for name, conn in connectors.items():
            try:
                conn.authenticate()
                print(f"[OK] {name} authenticated")
            except Exception as e:
                print(f"[FAIL] {name} authentication failed: {e}")

    return connectors
