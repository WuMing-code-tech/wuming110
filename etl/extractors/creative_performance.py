"""
素材效果数据抽取
从各广告平台拉取素材（Creative）粒度的效果数据
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class CreativePerformanceExtractor:
    """
    素材效果数据抽取器

    素材维度数据用于分析：
    - 哪些素材 CTR 最高
    - 素材疲劳度（CTR 随时间下降趋势）
    - 素材类型效果对比（视频 vs 图片 vs 轮播）
    """

    def __init__(self, connectors: dict = None):
        self.connectors = connectors or {}

    def extract(
        self,
        platform: str = None,
        start_date: str = None,
        end_date: str = None,
    ) -> list[dict]:
        """
        抽取素材效果数据

        部分平台（如 Meta）在 Insights 中直接包含 creative 信息
        其他平台需额外调用 ad list 获取素材元数据

        Returns:
            list[dict]: 素材效果数据（含 creative_id, creative_type, headline, body 等）
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        all_data = []
        platforms = [platform] if platform else ["meta", "tiktok", "google"]

        for plat in platforms:
            if plat not in self.connectors:
                logger.warning(f"Skipping {plat}: no connector configured")
                continue

            conn = self.connectors[plat]
            logger.info(f"Extracting creative data from {plat}: {start_date} ~ {end_date}")

            try:
                if plat == "meta":
                    # Meta 在 Insights breakdown 中直接包含 creative
                    data = conn.fetch_ad_performance(
                        start_date=start_date,
                        end_date=end_date,
                        breakdown=None,  # 获取所有数据，creative 信息在每行中
                    )
                    # 补充素材元数据
                    creative_ids = set()
                    for row in data:
                        if row.get("platform_creative_id"):
                            creative_ids.add(row["platform_creative_id"])
                    if creative_ids:
                        try:
                            creative_data = conn.get_creatives_batch(list(creative_ids))
                            # 将素材详情映射回去（简化处理：追加元数据字段）
                            creative_map = {}
                            if isinstance(creative_data, dict):
                                for cid, cdata in creative_data.items():
                                    creative_map[cid] = cdata
                            for row in data:
                                cid = row.get("platform_creative_id")
                                if cid and cid in creative_map:
                                    cd = creative_map[cid]
                                    row["creative_name"] = cd.get("name", "")
                                    row["creative_type"] = "IMAGE"
                                    row["headline"] = cd.get("title", "")
                                    row["body_text"] = cd.get("body", "")
                                    if cd.get("video_id"):
                                        row["creative_type"] = "VIDEO"
                        except Exception as e:
                            logger.warning(f"Failed to fetch creative details: {e}")

                    all_data.extend(data)

                elif plat == "tiktok":
                    # TikTok 需单独查询 ads 获取 creative 信息
                    ads = conn.fetch_ads()
                    ad_creative_map = {}
                    for ad in ads:
                        creative_info = ad.get("creative", {})
                        ad_creative_map[ad.get("ad_id")] = {
                            "platform_creative_id": creative_info.get("creative_id"),
                            "creative_name": creative_info.get("creative_name", ""),
                            "creative_type": creative_info.get("creative_type", "IMAGE"),
                            "headline": creative_info.get("title", ""),
                            "body_text": creative_info.get("ad_text", ""),
                        }

                    perf_data = conn.fetch_ad_performance(
                        start_date=start_date,
                        end_date=end_date,
                    )
                    for row in perf_data:
                        ad_id = row.get("platform_ad_id")
                        if ad_id and ad_id in ad_creative_map:
                            row.update(ad_creative_map[ad_id])
                    all_data.extend(perf_data)

                elif plat == "google":
                    # Google Ads 通过 get_creative_performance 直接获取
                    data = conn.get_creative_performance(
                        start_date=start_date,
                        end_date=end_date,
                    )
                    # 解析 Google Ads 特有字段
                    parsed = []
                    for row in data:
                        parsed.append({
                            "date_id": row.get("segments.date", ""),
                            "platform_code": "google",
                            "platform_ad_id": str(row.get("adGroupAd.ad.id", "")),
                            "ad_name": row.get("adGroupAd.ad.name", ""),
                            "platform_creative_id": None,  # Google Ads 素材是复合结构
                            "creative_type": "IMAGE",
                            "headline": "",
                            "body_text": "",
                            "impressions": int(row.get("metrics.impressions", 0) or 0),
                            "clicks": int(row.get("metrics.clicks", 0) or 0),
                            "spend": float(row.get("metrics.costMicros", 0) or 0) / 1_000_000,
                            "installs": int(row.get("metrics.installs", 0) or 0),
                            "revenue": float(row.get("metrics.conversionsValue", 0) or 0),
                        })
                    all_data.extend(parsed)

            except Exception as e:
                logger.error(f"Failed to extract creative data from {plat}: {e}")
                continue

        logger.info(f"Total creative performance rows extracted: {len(all_data)}")
        return all_data
