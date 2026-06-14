"""
Meta Ads (Facebook Marketing API) 连接器

API 文档: https://developers.facebook.com/docs/marketing-apis/
Insights API: GET /{ad-account-id}/insights

数据维度:
- 广告系列 (campaign)
- 广告组 (adset)
- 广告 (ad)
- 国家/地区 (country)
- 素材 (creative — 通过 ads 关联获取)
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from connectors.base import BaseConnector, APIError, APIAuthError
from config.settings import settings

logger = logging.getLogger(__name__)


class MetaAdsConnector(BaseConnector):
    """
    Meta Marketing API 连接器

    认证方式: OAuth 2.0 Access Token
    """

    platform_name = "meta"
    base_url = f"https://graph.facebook.com/{settings.META_API_VERSION}"
    rate_limit_cps = 3.0  # Facebook 限制较严

    def __init__(self, access_token: str = None, ad_account_id: str = None):
        super().__init__()
        self.access_token = access_token or settings.META_ACCESS_TOKEN
        self.ad_account_id = ad_account_id or settings.META_AD_ACCOUNT_ID
        # 规范化 ad account id: act_xxxxx 或纯数字
        if not self.ad_account_id.startswith("act_"):
            self.ad_account_id = f"act_{self.ad_account_id}"

    def authenticate(self) -> bool:
        """验证 Access Token 是否有效"""
        try:
            resp = self._get(f"/me", params={"access_token": self.access_token})
            if resp.get("id"):
                logger.info(f"Meta: Authenticated as user {resp.get('id')}")
                return True
            return False
        except Exception as e:
            logger.error(f"Meta auth failed: {e}")
            return False

    def get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    # ==================== Insights API ====================

    INSIGHT_FIELDS = [
        "spend",
        "impressions",
        "clicks",
        "actions",           # 包含 installs (app_custom_event.fb_mobile_install_completed)
        "action_values",     # 包含 revenue (fb_mobile_purchase)
        "cpm",
        "cpc",
        "ctr",
        "cost_per_action_type",
        "reach",
        "frequency",
        "video_p25_watched_actions",
        "video_p50_watched_actions",
        "video_p75_watched_actions",
        "video_p100_watched_actions",
        "campaign_id",
        "campaign_name",
        "adset_id",
        "adset_name",
        "ad_id",
        "ad_name",
        "creative",          # {id, title, body, image_url, ...}
    ]

    INSIGHT_BREAKDOWNS = [
        "country",
        "publisher_platform",
        "device_platform",
        "age",
        "gender",
    ]

    def get_insights(
        self,
        start_date: str,
        end_date: str,
        breakdown: str = None,       # country / platform / device
        level: str = "ad",           # campaign / adset / ad
        fields: list[str] = None,
        filtering: list[dict] = None,
        limit: int = 100,
        action_attribution_windows: list[str] = None,
    ) -> list[dict]:
        """
        拉取广告效果数据 (Insights)

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            breakdown: 维度拆分
            level: 粒度层级
            fields: 需要拉取的字段
            filtering: 过滤条件
            limit: 每页条数
            action_attribution_windows: 归因窗口 ["7d_click", "1d_view"]

        Returns:
            list[dict]: 广告效果数据
        """
        endpoint = f"/{self.ad_account_id}/insights"

        params = {
            "access_token": self.access_token,
            "time_range": json.dumps({
                "since": start_date,
                "until": end_date,
            }),
            "level": level,
            "limit": limit,
            "action_attribution_windows": json.dumps(
                action_attribution_windows or ["7d_click", "1d_view"]
            ),
        }

        if fields:
            params["fields"] = ",".join(fields)

        if breakdown:
            params["breakdowns"] = json.dumps([breakdown])

        if filtering:
            params["filtering"] = json.dumps(filtering)

        # Facebook API 使用 cursor-based 分页
        return self._paginate_cursor(endpoint, params)

    def _paginate_cursor(self, endpoint: str, params: dict) -> list[dict]:
        """
        Meta API cursor-based 分页

        Args:
            endpoint: API endpoint
            params: 基础参数

        Returns:
            list[dict]: 全量数据
        """
        all_data = []
        current_params = params.copy()
        page_count = 0

        while True:
            page_count += 1
            response = self._get(endpoint, current_params)

            data = response.get("data", [])
            all_data.extend(data)

            logger.debug(f"Meta page {page_count}: {len(data)} records")

            # Meta 使用 paging.cursors.after / paging.next
            paging = response.get("paging", {})
            next_url = paging.get("next")

            if not next_url or not data:
                break

            # 提取 after cursor 用于下次请求
            cursors = paging.get("cursors", {})
            after = cursors.get("after")
            if after:
                current_params["after"] = after

        logger.info(f"Meta: fetched {len(all_data)} records across {page_count} pages")
        return all_data

    def parse_installs_from_actions(self, actions: list[dict]) -> int:
        """从 actions 数组中提取安装量"""
        if not actions:
            return 0
        for action in actions:
            if action.get("action_type") == "app_custom_event.fb_mobile_install_completed":
                return int(action.get("value", 0))
        return 0

    def parse_revenue_from_actions(self, action_values: list[dict]) -> float:
        """从 action_values 数组中提取收入"""
        if not action_values:
            return 0.0
        for av in action_values:
            if av.get("action_type") == "fb_mobile_purchase":
                return float(av.get("value", 0))
        return 0.0

    # ==================== Campaigns ====================

    def get_campaigns(self, status_filter: list[str] = None) -> list[dict]:
        """
        获取广告账户下的所有 Campaign

        Args:
            status_filter: ['ACTIVE', 'PAUSED', ...]
        """
        endpoint = f"/{self.ad_account_id}/campaigns"
        params = {
            "access_token": self.access_token,
            "fields": "id,name,status,objective,daily_budget,lifetime_budget,created_time,updated_time",
            "limit": 100,
        }
        if status_filter:
            params["filtering"] = json.dumps([{
                "field": "configured_status",
                "operator": "IN",
                "value": status_filter,
            }])

        return self._paginate_cursor(endpoint, params)

    # ==================== Ads ====================

    def get_ads(self, campaign_id: str = None) -> list[dict]:
        """
        获取广告

        Args:
            campaign_id: 可选，按 Campaign 过滤
        """
        endpoint = f"/{self.ad_account_id}/ads"
        params = {
            "access_token": self.access_token,
            "fields": "id,name,status,creative{id,title,body,image_url,video_id,thumbnail_url,call_to_action_type}",
            "limit": 100,
        }
        if campaign_id:
            params["filtering"] = json.dumps([{
                "field": "campaign.id",
                "operator": "EQUAL",
                "value": campaign_id,
            }])

        return self._paginate_cursor(endpoint, params)

    # ==================== Creatives ====================

    def get_creative(self, creative_id: str) -> dict:
        """获取单个素材详情"""
        endpoint = f"/{creative_id}"
        params = {
            "access_token": self.access_token,
            "fields": "id,name,title,body,image_url,video_id,thumbnail_url,call_to_action_type,object_story_spec",
        }
        return self._get(endpoint, params)

    def get_creatives_batch(self, creative_ids: list[str]) -> dict:
        """批量获取素材"""
        endpoint = f"/"
        ids_str = ",".join(creative_ids)
        params = {
            "ids": ids_str,
            "access_token": self.access_token,
            "fields": "id,name,title,body,image_url,video_id,thumbnail_url,call_to_action_type",
        }
        return self._get(endpoint, params)

    # ==================== 统一数据拉取入口 ====================

    def fetch_ad_performance(
        self,
        start_date: str,
        end_date: str,
        breakdown: str = "country",
    ) -> list[dict]:
        """
        按日期范围拉取完整广告效果数据（包含安装量和收入解析）

        Returns:
            list[dict]: 每行已包含 platform_campaign_id, platform_ad_id, creative_id,
                        country_code, impressions, clicks, spend, installs, revenue
        """
        raw_data = self.get_insights(
            start_date=start_date,
            end_date=end_date,
            level="ad",
            breakdown=breakdown,
            fields=[
                "campaign_id", "campaign_name",
                "adset_id", "adset_name",
                "ad_id", "ad_name",
                "creative",
                "spend",
                "impressions",
                "clicks",
                "cpm",
                "cpc",
                "ctr",
                "actions",
                "action_values",
                "reach",
                "frequency",
                "date_start",
                "date_stop",
            ],
        )

        parsed = []
        for row in raw_data:
            # 安装量解析
            actions = row.get("actions", [])
            installs = self.parse_installs_from_actions(actions)

            # 收入解析
            action_values = row.get("action_values", [])
            revenue = self.parse_revenue_from_actions(action_values)

            # 素材
            creative = row.get("creative", {})
            creative_id = creative.get("id") if isinstance(creative, dict) else creative

            parsed.append({
                "date_id": row.get("date_start", start_date),
                "platform_code": "meta",
                "platform_campaign_id": row.get("campaign_id"),
                "campaign_name": row.get("campaign_name"),
                "platform_adset_id": row.get("adset_id"),
                "adset_name": row.get("adset_name"),
                "platform_ad_id": row.get("ad_id"),
                "ad_name": row.get("ad_name"),
                "platform_creative_id": str(creative_id) if creative_id else None,
                "country_code": row.get("country", "unknown"),
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
                "spend": float(row.get("spend", 0)),
                "installs": installs,
                "revenue": revenue,
                "reach": int(row.get("reach", 0)),
                "frequency": float(row.get("frequency", 0)),
                "video_views_25pct": int(row.get("video_p25_watched_actions", [{}])[0].get("value", 0)) if row.get("video_p25_watched_actions") else 0,
                "video_views_50pct": int(row.get("video_p50_watched_actions", [{}])[0].get("value", 0)) if row.get("video_p50_watched_actions") else 0,
                "video_views_75pct": int(row.get("video_p75_watched_actions", [{}])[0].get("value", 0)) if row.get("video_p75_watched_actions") else 0,
                "video_views_100pct": int(row.get("video_p100_watched_actions", [{}])[0].get("value", 0)) if row.get("video_p100_watched_actions") else 0,
            })

        return parsed

    def fetch_campaigns(self) -> list[dict]:
        """拉取所有 Campaign 元数据"""
        return self.get_campaigns()

    def fetch_ads_with_creatives(self) -> list[dict]:
        """拉取所有广告及其关联的素材"""
        return self.get_ads()


