"""
TikTok Ads (TikTok Business API) 连接器

API 文档: https://ads.tiktok.com/marketing_api/docs

数据维度:
- 广告系列 (campaign)
- 广告组 (adgroup)
- 广告 (ad)
- 国家/地区 (country_code — 通过 breakdown)
- 素材 (creative — 通过 ad 关联)
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from connectors.base import BaseConnector, APIError, APIAuthError
from config.settings import settings

logger = logging.getLogger(__name__)


class TikTokAdsConnector(BaseConnector):
    """
    TikTok Business API 连接器

    认证方式: OAuth 2.0 Access Token (Long-term)
    """

    platform_name = "tiktok"
    base_url = "https://business-api.tiktok.com/open_api/v1.3"
    rate_limit_cps = 3.0

    def __init__(self, access_token: str = None, advertiser_id: str = None):
        super().__init__()
        self.access_token = access_token or settings.TIKTOK_ACCESS_TOKEN
        self.advertiser_id = advertiser_id or settings.TIKTOK_ADVERTISER_ID

    def authenticate(self) -> bool:
        """验证 Access Token"""
        try:
            resp = self._get(
                "/oauth2/advertiser/get/",
                params={"advertiser_id": self.advertiser_id}
            )
            if resp.get("code") == 0:
                logger.info(f"TikTok: Authenticated for advertiser {self.advertiser_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"TikTok auth failed: {e}")
            return False

    def get_headers(self) -> dict:
        return {
            "Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    def _parse_response(self, response: dict) -> dict:
        """
        解析 TikTok API 统一响应格式
        {code: 0, message: "ok", data: {...}}
        """
        code = response.get("code", -1)
        message = response.get("message", "Unknown error")

        if code != 0:
            raise APIError(
                f"TikTok API error {code}: {message}",
                platform="tiktok"
            )

        return response.get("data", {})

    # ==================== 广告数据拉取 ====================

    REPORT_METRICS = [
        # 花费
        "spend",
        # 展示
        "impressions",
        "video_play_actions",
        "video_watched_2s",
        "video_watched_6s",
        # 点击
        "clicks",
        # 转化
        "conversion",
        "app_install",              # 安装
        "purchase",                 # 购买
        "purchase_value",           # 收入
        "in_app_purchase",          # 内购
        "in_app_purchase_value",    # 内购收入
        # 计算指标
        "cpc",
        "cpm",
        "ctr",
        # 归因
        "real_time_app_install",
        "real_time_purchase",
        "real_time_purchase_value",
    ]

    REPORT_DIMENSIONS = [
        "campaign_id",
        "adgroup_id",
        "ad_id",
        "stat_time_day",
        "country_code",
    ]

    def get_report(
        self,
        start_date: str,
        end_date: str,
        dimensions: list[str] = None,
        metrics: list[str] = None,
        page_size: int = 100,
        page: int = 1,
    ) -> dict:
        """
        拉取报表数据 (Integrated Report)

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            dimensions: 维度列表
            metrics: 指标列表
            page_size: 每页条数

        Returns:
            dict: {list: [...], page_info: {...}}
        """
        endpoint = "/report/integrated/get/"

        body = {
            "advertiser_id": self.advertiser_id,
            "report_type": "BASIC",
            "data_level": "AUCTION_AD",
            "dimensions": json.dumps(dimensions or self.REPORT_DIMENSIONS),
            "metrics": json.dumps(metrics or self.REPORT_METRICS),
            "start_date": start_date,
            "end_date": end_date,
            "page_size": page_size,
            "page": page,
        }

        resp_json = self._post(endpoint, json_body=body)
        return self._parse_response(resp_json)

    def get_report_all_pages(
        self,
        start_date: str,
        end_date: str,
        dimensions: list[str] = None,
        metrics: list[str] = None,
    ) -> list[dict]:
        """
        自动翻页拉取全量报表数据
        """
        all_data = []
        page = 1

        while True:
            data = self.get_report(
                start_date=start_date,
                end_date=end_date,
                dimensions=dimensions,
                metrics=metrics,
                page=page,
            )

            records = data.get("list", [])
            if not records:
                break

            all_data.extend(records)

            page_info = data.get("page_info", {})
            total_page = page_info.get("total_page", 0)

            if page >= total_page:
                break

            page += 1

        logger.info(f"TikTok: fetched {len(all_data)} records across {page} pages")
        return all_data

    # ==================== Campaign / Adgroup / Ad 元数据 ====================

    def get_campaigns(self, status: str = None) -> list[dict]:
        """
        获取广告系列列表
        """
        endpoint = "/campaign/get/"
        body = {
            "advertiser_id": self.advertiser_id,
            "page_size": 100,
        }
        if status:
            body["status"] = status

        # TikTok 也使用分页
        all_data = []
        page = 1
        while True:
            body["page"] = page
            resp_json = self._post(endpoint, json_body=body)
            data = self._parse_response(resp_json)
            records = data.get("list", [])
            if not records:
                break
            all_data.extend(records)
            page += 1

        return all_data

    def get_ads(self, campaign_id: str = None) -> list[dict]:
        """
        获取广告列表
        """
        endpoint = "/ad/get/"
        body = {
            "advertiser_id": self.advertiser_id,
            "page_size": 100,
        }
        if campaign_id:
            body["campaign_id"] = campaign_id

        all_data = []
        page = 1
        while True:
            body["page"] = page
            resp_json = self._post(endpoint, json_body=body)
            data = self._parse_response(resp_json)
            records = data.get("list", [])
            if not records:
                break
            all_data.extend(records)
            page += 1

        return all_data

    def get_creatives(self, ad_id: str) -> list[dict]:
        """获取指定广告的素材信息"""
        endpoint = "/creative/get/"
        body = {
            "advertiser_id": self.advertiser_id,
            "ad_id": ad_id,
        }
        resp_json = self._post(endpoint, json_body=body)
        data = self._parse_response(resp_json)
        return data.get("list", [])

    # ==================== 统一数据拉取入口 ====================

    def fetch_ad_performance(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """
        按日期范围拉取完整广告效果数据

        Returns:
            list[dict]: 标准化格式的广告效果数据
        """
        raw_data = self.get_report_all_pages(
            start_date=start_date,
            end_date=end_date,
            dimensions=["campaign_id", "adgroup_id", "ad_id", "stat_time_day", "country_code"],
            metrics=[
                "campaign_name", "adgroup_name", "ad_name",
                "spend", "impressions", "clicks",
                "cpm", "cpc", "ctr",
                "app_install", "purchase_value",
                "video_play_actions", "video_watched_2s", "video_watched_6s",
            ],
        )

        parsed = []
        for row in raw_data:
            metrics = row.get("metrics", {})
            dimensions = row.get("dimensions", {})

            parsed.append({
                "date_id": dimensions.get("stat_time_day", start_date),
                "platform_code": "tiktok",
                "platform_campaign_id": dimensions.get("campaign_id"),
                "campaign_name": metrics.get("campaign_name", ""),
                "platform_adset_id": dimensions.get("adgroup_id"),
                "adset_name": metrics.get("adgroup_name", ""),
                "platform_ad_id": dimensions.get("ad_id"),
                "ad_name": metrics.get("ad_name", ""),
                "platform_creative_id": None,  # TikTok 需额外查询 creative
                "country_code": dimensions.get("country_code", "unknown"),
                "impressions": int(metrics.get("impressions", 0) or 0),
                "clicks": int(metrics.get("clicks", 0) or 0),
                "spend": float(metrics.get("spend", 0) or 0),
                "installs": int(metrics.get("app_install", 0) or 0),
                "revenue": float(metrics.get("purchase_value", 0) or 0),
                "video_views": int(metrics.get("video_play_actions", 0) or 0),
                "video_views_25pct": int(metrics.get("video_watched_2s", 0) or 0),
                "video_views_50pct": int(metrics.get("video_watched_6s", 0) or 0),
            })

        return parsed

    def fetch_campaigns(self) -> list[dict]:
        return self.get_campaigns()

    def fetch_ads(self) -> list[dict]:
        return self.get_ads()
