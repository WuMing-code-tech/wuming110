"""
Google Ads API 连接器

API 文档: https://developers.google.com/google-ads/api/docs/overview

Google Ads API 基于 gRPC，但本连接器也支持通过 REST 接口
使用场景: 拉取搜索广告、展示广告、YouTube 广告的效果数据

NOTE: Google Ads API 需要开发者令牌(developer_token)和 OAuth2 认证
      首次使用需完成 OAuth 流程获取 refresh_token
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Any
from connectors.base import BaseConnector, APIError, APIAuthError
from config.settings import settings

logger = logging.getLogger(__name__)


class GoogleAdsConnector(BaseConnector):
    """
    Google Ads API 连接器

    认证方式: OAuth 2.0 (Client ID + Client Secret + Developer Token + Refresh Token)
    使用 Google Ads API v17 (REST 桥接)

    由于 Google Ads API 基于 gRPC，完整支持需 google-ads 库。
    此处提供两种实现路径：
    1. gRPC 客户端（推荐生产使用）
    2. HTTP REST 桥接（轻量部署场景）
    """

    platform_name = "google"
    base_url = "https://googleads.googleapis.com/v17"
    oauth_url = "https://www.googleapis.com/oauth2/v4/token"
    rate_limit_cps = 2.0  # Google Ads 限制较严

    def __init__(
        self,
        developer_token: str = None,
        customer_id: str = None,
        manager_customer_id: str = None,
        client_id: str = None,
        client_secret: str = None,
        refresh_token: str = None,
    ):
        super().__init__()
        self.developer_token = developer_token or settings.GOOGLE_ADS_DEVELOPER_TOKEN
        self.customer_id = customer_id or settings.GOOGLE_ADS_CUSTOMER_ID
        self.manager_customer_id = manager_customer_id or settings.GOOGLE_ADS_MANAGER_CUSTOMER_ID
        self.client_id = client_id or settings.GOOGLE_ADS_CLIENT_ID
        self.client_secret = client_secret or settings.GOOGLE_ADS_CLIENT_SECRET
        self.refresh_token = refresh_token or settings.GOOGLE_ADS_REFRESH_TOKEN

        # 规范化 customer_id: 去除横线
        self.customer_id = self.customer_id.replace("-", "") if self.customer_id else ""

        # Access token 缓存
        self._access_token: str = ""
        self._token_expiry: datetime = None

    def authenticate(self) -> bool:
        """获取 OAuth Access Token"""
        try:
            self._refresh_access_token()
            logger.info(f"Google Ads: Authenticated for customer {self.customer_id}")
            return True
        except Exception as e:
            logger.error(f"Google Ads auth failed: {e}")
            return False

    def _refresh_access_token(self):
        """使用 Refresh Token 刷新 Access Token"""
        resp = self.session.post(
            self.oauth_url,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            }
        )
        resp.raise_for_status()
        token_data = resp.json()

        self._access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)
        self._token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)

    def get_headers(self) -> dict:
        # 自动刷新过期 token
        if not self._access_token or (
            self._token_expiry and datetime.now() >= self._token_expiry
        ):
            self._refresh_access_token()

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "developer-token": self.developer_token,
            "Content-Type": "application/json",
        }

        # 如果是管理账户，添加 login-customer-id 头
        if self.manager_customer_id:
            headers["login-customer-id"] = self.manager_customer_id

        return headers

    # ==================== Google Ads Query Language (GAQL) ====================

    def search(
        self,
        query: str,
        page_size: int = 10000,
    ) -> list[dict]:
        """
        执行 GAQL 查询并获取全量结果

        Google Ads API 使用 GAQL (类似 SQL) 来查询数据

        Args:
            query: GAQL 查询语句
            page_size: 每页条数

        Returns:
            list[dict]: 查询结果

        Example GAQL:
            SELECT
              campaign.id, campaign.name,
              metrics.impressions, metrics.clicks,
              metrics.cost_micros, metrics.installs,
              metrics.conversions_value,
              segments.date
            FROM campaign
            WHERE segments.date BETWEEN '2025-01-01' AND '2025-01-31'
        """
        endpoint = f"/customers/{self.customer_id}/googleAds:search"

        all_results = []
        next_page_token = None

        while True:
            body = {
                "query": query,
                "pageSize": page_size,
            }
            if next_page_token:
                body["pageToken"] = next_page_token

            response = self._post(endpoint, json_body=body)

            results = response.get("results", [])
            all_results.extend(results)

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        logger.info(f"Google Ads: query returned {len(all_results)} results")
        return all_results

    def search_stream(self, query: str) -> list[dict]:
        """
        流式 GAQL 查询（无需翻页，适合大批量数据）
        """
        endpoint = f"/customers/{self.customer_id}/googleAds:searchStream"

        body = {"query": query}

        response = self._post(endpoint, json_body=body)
        # searchStream 返回多个 batch
        all_results = []
        for batch in response:
            results = batch.get("results", [])
            all_results.extend(results)

        return all_results

    # ==================== 标准数据查询 ====================

    def get_campaign_performance(
        self,
        start_date: str,
        end_date: str,
        breakdown_country: bool = True,
    ) -> list[dict]:
        """
        拉取 Campaign 粒度的效果数据

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            breakdown_country: 是否按国家拆分

        Returns:
            list[dict]: 效果数据
        """
        segments = [
            "segments.date",
        ]
        if breakdown_country:
            segments.append("segments.geo_target_country")

        query = f"""
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            ad_group.id,
            ad_group.name,
            ad_group_ad.ad.id,
            ad_group_ad.ad.name,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.installs,
            metrics.conversions,
            metrics.conversions_value,
            metrics.all_conversions_value,
            metrics.video_views,
            metrics.video_quartile_p25_rate,
            metrics.video_quartile_p50_rate,
            metrics.video_quartile_p75_rate,
            metrics.video_quartile_p100_rate,
            metrics.ctr,
            metrics.average_cpm,
            metrics.average_cpc,
            {", ".join(segments)}
        FROM ad_group_ad
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
            AND campaign.status != 'REMOVED'
        ORDER BY segments.date DESC
        """

        return self.search(query)

    def get_creative_performance(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """
        拉取素材粒度效果数据
        """
        query = f"""
        SELECT
            ad_group_ad.ad.id,
            ad_group_ad.ad.name,
            ad_group_ad.ad.image_ad.images,
            ad_group_ad.ad.video_ad.videos,
            ad_group_ad.ad.responsive_search_ad.headlines,
            ad_group_ad.ad.responsive_search_ad.descriptions,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.installs,
            metrics.conversions_value,
            metrics.ctr,
            segments.date
        FROM ad_group_ad
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
            AND campaign.status != 'REMOVED'
        ORDER BY metrics.impressions DESC
        """

        return self.search(query)

    def get_campaigns(self) -> list[dict]:
        """获取所有 Campaign 基本信息"""
        query = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            campaign.bidding_strategy_type,
            campaign.start_date,
            campaign.end_date
        FROM campaign
        """
        return self.search(query)

    # ==================== 数据标准化 ====================

    def _cost_micros_to_usd(self, cost_micros: str) -> float:
        """
        Google Ads 金额单位为 micros (1 USD = 1,000,000 micros)
        转换为 USD 金额
        """
        try:
            return int(cost_micros) / 1_000_000
        except (ValueError, TypeError):
            return 0.0

    def _parse_google_ads_result(self, row: dict) -> dict:
        """
        将 Google Ads API 返回的行标准化为统一格式

        Google Ads API 使用点号分隔的嵌套字段名
        { 'campaign.id': '123', 'campaign.name': 'Test', ... }
        """
        def get_field(key: str, default: Any = None) -> Any:
            return row.get(key, default)

        metrics = {}
        for k, v in row.items():
            if k.startswith("metrics."):
                metrics[k] = v
            if k.startswith("segments."):
                metrics[k] = v
            if k.startswith("campaign."):
                metrics[k] = v
            if k.startswith("ad_group_ad."):
                metrics[k] = v

        # 金额转换
        cost_micros = row.get("metrics.costMicros", "0")
        spend = self._cost_micros_to_usd(cost_micros)

        conversions_value = row.get("metrics.conversionsValue", 0) or 0

        return {
            "date_id": row.get("segments.date", ""),
            "platform_code": "google",
            "platform_campaign_id": str(row.get("campaign.id", "")),
            "campaign_name": row.get("campaign.name", ""),
            "platform_adset_id": str(row.get("adGroup.id", "")),
            "adset_name": row.get("adGroup.name", ""),
            "platform_ad_id": str(row.get("adGroupAd.ad.id", "")),
            "ad_name": row.get("adGroupAd.ad.name", ""),
            "platform_creative_id": None,
            "country_code": row.get("segments.geoTargetCountry", "unknown"),
            "impressions": int(row.get("metrics.impressions", 0) or 0),
            "clicks": int(row.get("metrics.clicks", 0) or 0),
            "spend": spend,
            "installs": int(row.get("metrics.installs", 0) or 0),
            "revenue": float(conversions_value),
            "video_views": int(row.get("metrics.videoViews", 0) or 0),
            "video_views_25pct": 0,  # Google 返回比率而非绝对值
            "video_views_50pct": 0,
            "video_views_75pct": 0,
            "video_views_100pct": 0,
        }

    # ==================== 统一数据拉取入口 ====================

    def fetch_ad_performance(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """
        按日期范围拉取完整广告效果数据
        """
        raw_data = self.get_campaign_performance(
            start_date=start_date,
            end_date=end_date,
            breakdown_country=True,
        )

        return [self._parse_google_ads_result(row) for row in raw_data]

    def fetch_campaigns(self) -> list[dict]:
        return self.get_campaigns()
