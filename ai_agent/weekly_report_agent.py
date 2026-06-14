#!/usr/bin/env python3
"""
周报自动生成 Agent

功能：
1. 每周一自动生成上周投放数据周报
2. 包含：各渠道 CPI/CPM/CTR/ROI/LTV 对比、TOP 素材、地区表现、趋势分析
3. 输出 Markdown 周报 + 终端摘要
4. 可推送到邮件 / 钉钉 / 飞书 / Slack

调度方式：
- Claude Code: 每周一 9:07 AM 自动触发
"""
import os
import requests
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import db as database
from config.settings import settings
from config.metric_definitions import cpi, cpm, ctr, roi_roas, cvr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("weekly_report_agent")


class WeeklyReportAgent:
    """
    周报生成 Agent

    输出内容：
    1. 整体概览 (总花费、总安装、总营收、综合 KPI)
    2. 渠道对比 (Meta vs TikTok vs Google)
    3. 地区表现 (按大区 CPI/ROI)
    4. 素材排行 (Top 10 by CTR/ROI)
    5. 趋势分析 (环比变化 + AI 解读)
    6. 异常与建议
    """

    def __init__(self, output_dir: str = None):
        self.db = database
        self.output_dir = Path(output_dir or __file__).resolve().parent
        self.report: list[str] = []  # Markdown lines

    def run(
        self,
        week_ending: str = None,
        save_to_file: bool = True,
    ) -> str:
        """
        生成周报

        Args:
            week_ending: 周日日期 (None = 上周日)
            save_to_file: 是否保存到文件

        Returns:
            str: 完整的 Markdown 周报
        """
        if week_ending is None:
            today = datetime.now()
            # 找到上一个周日
            days_since_sunday = (today.weekday() + 1) % 7
            last_sunday = today - timedelta(days=days_since_sunday if days_since_sunday > 0 else 7)
            week_ending = last_sunday.strftime("%Y-%m-%d")

        week_start = (datetime.strptime(week_ending, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
        prev_week_start = (datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        prev_week_end = (datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"📝 Generating weekly report: {week_start} → {week_ending}")

        # 构建 Markdown 周报
        self._header(week_start, week_ending)
        self._overview_section(week_start, week_ending, prev_week_start, prev_week_end)
        self._channel_section(week_start, week_ending, prev_week_start, prev_week_end)
        self._region_section(week_start, week_ending)
        self._creative_section(week_start, week_ending)
        self._ltv_section(week_start, week_ending)
        self._trends_section(week_start, week_ending, prev_week_start, prev_week_end)
        self._insights_section(week_start, week_ending)
        self._footer()

        report_md = "\n".join(self.report)
        logger.info(f"Report generated: {len(report_md)} chars")

        if save_to_file:
            filename = f"weekly_report_{week_ending}.md"
            filepath = Path(self.output_dir) / filename
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report_md)
            logger.info(f"Report saved to {filepath}")

        return report_md

    def _header(self, week_start: str, week_ending: str):
        self.report.extend([
            f"# 📊 海外广告投流周报",
            f"",
            f"**报告周期**: {week_start} ～ {week_ending}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**数据源**: Meta Ads / TikTok Ads / Google Ads / AppsFlyer",
            f"",
            f"---",
            f"",
        ])

    def _overview_section(self, ws, we, pws, pwe):
        """整体概览"""
        self.report.extend(["## 一、整体概览", ""])

        try:
            current = self._get_aggregated_kpis(ws, we)
            previous = self._get_aggregated_kpis(pws, pwe)

            if current:
                self.report.extend([
                    f"| 指标 | 本周值 | 上周值 | 环比变化 |",
                    f"|------|--------|--------|----------|",
                ])

                for label, key in [
                    ("总花费 (USD)", "total_spend"),
                    ("总展示量", "total_impressions"),
                    ("总点击量", "total_clicks"),
                    ("总安装量", "total_installs"),
                    ("总收入 (USD)", "total_revenue"),
                    ("CPI (USD)", "cpi"),
                    ("CPM (USD)", "cpm"),
                    ("CTR (%)", "ctr"),
                    ("ROI", "roi"),
                ]:
                    cur_val = current.get(key, 0) or 0
                    prev_val = previous.get(key, 0) or 0
                    change_pct = ((cur_val - prev_val) / prev_val * 100) if prev_val else 0

                    arrow = "⬆️" if change_pct > 0 else "⬇️" if change_pct < 0 else "➡️"
                    change_str = f"{arrow} {abs(change_pct):.1f}%" if change_pct != 0 else "—"

                    if key in ("total_spend", "total_revenue", "cpi", "cpm"):
                        cur_str = f"${cur_val:,.2f}"
                        prev_str = f"${prev_val:,.2f}"
                    elif key in ("ctr",):
                        cur_str = f"{cur_val:.2f}%"
                        prev_str = f"{prev_val:.2f}%"
                    elif key in ("cvr",):
                        cur_str = f"{cur_val:.2f}%"
                        prev_str = f"{prev_val:.2f}%"
                    elif key in ("roi", "ltv"):
                        cur_str = f"{cur_val:.2f}x"
                        prev_str = f"{prev_val:.2f}x"
                    else:
                        cur_str = f"{cur_val:,.0f}"
                        prev_str = f"{prev_val:,.0f}"

                    self.report.append(f"| {label} | {cur_str} | {prev_str} | {change_str} |")

        except Exception as e:
            logger.error(f"Overview section failed: {e}")
            self.report.append(f"⚠️ 数据查询异常: {e}")

        self.report.extend(["", ""])

    def _channel_section(self, ws, we, pws, pwe):
        """渠道对比"""
        self.report.extend(["## 二、渠道对比", ""])

        try:
            channels = self.db.fetch_all("""
                SELECT
                    p.platform_code,
                    p.platform_name,
                    SUM(f.spend) AS total_spend,
                    SUM(f.impressions) AS total_impressions,
                    SUM(f.clicks) AS total_clicks,
                    SUM(f.installs) AS total_installs,
                    SUM(f.revenue) AS total_revenue,
                    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 4) AS cpi,
                    ROUND(SUM(f.spend) * 1000.0 / NULLIF(SUM(f.impressions), 0), 4) AS cpm,
                    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 4) AS ctr,
                    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN ? AND ?
                GROUP BY p.platform_code, p.platform_name
                ORDER BY total_spend DESC
            """, (ws, we))

            if channels:
                self.report.extend([
                    f"| 渠道 | 花费 | 安装 | CPI | CPM | CTR | ROI | Spend% |",
                    f"|------|------|------|-----|-----|-----|-----|--------|",
                ])

                total_spend = sum(c["total_spend"] for c in channels) or 1

                for ch in channels:
                    spend_pct = ch["total_spend"] / total_spend * 100
                    self.report.append(
                        f"| **{ch['platform_name']}** | "
                        f"${ch['total_spend']:,.0f} | "
                        f"{ch['total_installs']:,} | "
                        f"${ch['cpi']:.2f} | "
                        f"${ch['cpm']:.2f} | "
                        f"{ch['ctr']:.2f}% | "
                        f"{ch['roi']:.2f} | "
                        f"{spend_pct:.1f}% |"
                    )

                # 最佳/最差渠道
                best_roi = max(channels, key=lambda c: c["roi"])
                lowest_cpi = min(channels, key=lambda c: c["cpi"] if c["cpi"] > 0 else float("inf"))

                self.report.extend([
                    f"",
                    f"**🏆 最佳渠道**: {best_roi['platform_name']} (ROI={best_roi['roi']:.2f})",
                    f"**💡 最低 CPI**: {lowest_cpi['platform_name']} (CPI=${lowest_cpi['cpi']:.2f})",
                ])

        except Exception as e:
            logger.error(f"Channel section failed: {e}")

        self.report.extend(["", ""])

    def _region_section(self, ws, we):
        """地区表现"""
        self.report.extend(["## 三、地区表现", ""])

        try:
            regions = self.db.fetch_all("""
                SELECT
                    c.region,
                    c.country_code,
                    SUM(f.spend) AS total_spend,
                    SUM(f.installs) AS total_installs,
                    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 4) AS cpi,
                    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi
                FROM fact_ad_performance f
                JOIN dim_country c ON f.country_id = c.country_id
                WHERE f.date_id BETWEEN ? AND ?
                GROUP BY c.region, c.country_code
                ORDER BY total_spend DESC
            """, (ws, we))

            if regions:
                self.report.extend([
                    f"### 按大区汇总",
                    f"",
                ])

                # 大区聚合
                from collections import defaultdict
                region_agg = defaultdict(lambda: {"spend": 0, "installs": 0, "revenue": 0})
                for r in regions:
                    agg = region_agg[r["region"]]
                    agg["spend"] += r["total_spend"]
                    agg["installs"] += r["total_installs"]

                self.report.extend([
                    f"| 大区 | 花费 | 安装 | CPI | 国家数 |",
                    f"|------|------|------|-----|--------|",
                ])

                for region, agg in sorted(region_agg.items(), key=lambda x: x[1]["spend"], reverse=True):
                    region_cpi = cpi(agg["spend"], agg["installs"])
                    country_count = len(set(r["country_code"] for r in regions if r["region"] == region))
                    self.report.append(
                        f"| **{region}** | "
                        f"${agg['spend']:,.0f} | "
                        f"{agg['installs']:,} | "
                        f"${region_cpi:.2f} | "
                        f"{country_count} |"
                    )

                # Top 5 国家
                self.report.extend(["", "### Top 5 国家 (按花费)", ""])
                top_countries = sorted(regions, key=lambda r: r["total_spend"], reverse=True)[:5]
                self.report.extend([
                    f"| 国家 | 花费 | CPI | ROI |",
                    f"|------|------|-----|-----|",
                ])
                for tc in top_countries:
                    self.report.append(
                        f"| {tc['country_code']} | "
                        f"${tc['total_spend']:,.0f} | "
                        f"${tc['cpi']:.2f} | "
                        f"{tc['roi']:.2f} |"
                    )

        except Exception as e:
            logger.error(f"Region section failed: {e}")

        self.report.extend(["", ""])

    def _creative_section(self, ws, we):
        """素材排行"""
        self.report.extend(["## 四、素材成效排行", ""])

        try:
            top_creatives = self.db.fetch_all("""
                SELECT * FROM mv_creative_top
                ORDER BY total_spend DESC
                LIMIT 10
            """)

            # 数据库里的 mv_creative_top 没有日期过滤，需要重写查询
            top_creatives = self.db.fetch_all(f"""
                SELECT
                    c.creative_name,
                    c.creative_type,
                    p.platform_name,
                    SUM(f.impressions) AS impressions,
                    SUM(f.clicks) AS clicks,
                    SUM(f.installs) AS installs,
                    SUM(f.spend) AS spend,
                    SUM(f.revenue) AS revenue,
                    ROUND(SUM(f.clicks) * 100.0 / NULLIF(SUM(f.impressions), 0), 4) AS ctr,
                    ROUND(SUM(f.spend) * 1.0 / NULLIF(SUM(f.installs), 0), 4) AS cpi,
                    ROUND(SUM(f.revenue) * 1.0 / NULLIF(SUM(f.spend), 0), 4) AS roi
                FROM fact_ad_performance f
                JOIN dim_creative c ON f.creative_id = c.creative_id
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN '{ws}' AND '{we}'
                GROUP BY c.platform_creative_id
                ORDER BY spend DESC
                LIMIT 10
            """)

            if top_creatives:
                self.report.extend([
                    f"| # | 素材 | 渠道 | 花费 | CPI | CTR | ROI |",
                    f"|---|------|------|------|-----|-----|-----|",
                ])

                for i, c in enumerate(top_creatives, 1):
                    name = c["creative_name"] or f"Creative #{i}"
                    self.report.append(
                        f"| {i} | {name} | {c['platform_name']} | "
                        f"${c['spend']:,.0f} | "
                        f"${c['cpi']:.2f} | "
                        f"{c['ctr']:.2f}% | "
                        f"{c['roi']:.2f} |"
                    )

                # 素材类型效果对比
                type_agg = self.db.fetch_all(f"""
                    SELECT
                        c.creative_type,
                        COUNT(DISTINCT c.platform_creative_id) AS count,
                        AVG(f.ctr) AS avg_ctr,
                        AVG(f.cpi) AS avg_cpi,
                        AVG(f.roi) AS avg_roi
                    FROM fact_ad_performance f
                    JOIN dim_creative c ON f.creative_id = c.creative_id
                    WHERE f.date_id BETWEEN '{ws}' AND '{we}'
                      AND c.creative_type != ''
                    GROUP BY c.creative_type
                """)

                if type_agg:
                    self.report.extend(["", "### 素材类型效果对比", ""])
                    self.report.extend([
                        f"| 类型 | 数量 | 平均 CTR | 平均 CPI | 平均 ROI |",
                        f"|------|------|----------|----------|----------|",
                    ])
                    for t in type_agg:
                        self.report.append(
                            f"| {t['creative_type']} | {t['count']} | "
                            f"{t['avg_ctr']:.2f}% | ${t['avg_cpi']:.2f} | {t['avg_roi']:.2f} |"
                        )
            else:
                self.report.append("暂无素材数据（可能尚未配置素材维度同步）")

        except Exception as e:
            logger.error(f"Creative section failed: {e}")

        self.report.extend(["", ""])

    def _ltv_section(self, ws, we):
        """LTV 与留存"""
        self.report.extend(["## 五、LTV 与用户留存", ""])

        try:
            ltv_data = self.db.fetch_all(f"""
                SELECT
                    media_source,
                    ROUND(AVG(ltv_d7), 4) AS avg_ltv_d7,
                    ROUND(AVG(ltv_d30), 4) AS avg_ltv_d30,
                    ROUND(AVG(retention_d1), 2) AS avg_ret_d1,
                    ROUND(AVG(retention_d7), 2) AS avg_ret_d7,
                    ROUND(AVG(retention_d30), 2) AS avg_ret_d30
                FROM fact_attribution
                WHERE date_id BETWEEN '{ws}' AND '{we}'
                GROUP BY media_source
            """)

            if ltv_data:
                self.report.extend([
                    f"| 媒体来源 | LTV D7 | LTV D30 | Ret D1 | Ret D7 | Ret D30 |",
                    f"|----------|--------|---------|--------|--------|---------|",
                ])
                for l in ltv_data:
                    self.report.append(
                        f"| {l['media_source']} | "
                        f"${l['avg_ltv_d7']:.4f} | "
                        f"${l['avg_ltv_d30']:.4f} | "
                        f"{l['avg_ret_d1']:.1f}% | "
                        f"{l['avg_ret_d7']:.1f}% | "
                        f"{l['avg_ret_d30']:.1f}% |"
                    )
            else:
                self.report.append("暂无 LTV 数据（需配置 AppsFlyer 连接器）")

        except Exception as e:
            logger.error(f"LTV section failed: {e}")

        self.report.extend(["", ""])

    def _trends_section(self, ws, we, pws, pwe):
        """趋势分析"""
        self.report.extend(["## 六、趋势分析", ""])

        try:
            daily = self.db.fetch_all(f"""
                SELECT
                    date_id,
                    p.platform_code,
                    SUM(spend) AS spend,
                    SUM(installs) AS installs,
                    ROUND(SUM(spend) * 1.0 / NULLIF(SUM(installs), 0), 4) AS cpi,
                    ROUND(SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0), 4) AS ctr,
                    ROUND(SUM(revenue) * 1.0 / NULLIF(SUM(spend), 0), 4) AS roi
                FROM fact_ad_performance f
                JOIN dim_platform p ON f.platform_id = p.platform_id
                WHERE f.date_id BETWEEN '{pws}' AND '{we}'
                GROUP BY f.date_id, p.platform_code
                ORDER BY f.date_id
            """)

            if daily:
                self.report.extend([
                    f"### 每日 CPI 趋势 (14天)",
                    f"",
                    f"```",
                ])

                platforms = set(d["platform_code"] for d in daily)
                dates = sorted(set(d["date_id"] for d in daily))

                for plat in sorted(platforms):
                    plat_data = [d for d in daily if d["platform_code"] == plat]
                    cpi_values = []
                    for date in dates:
                        match = next((d for d in plat_data if d["date_id"] == date), None)
                        cpi_values.append(f"${match['cpi']:.2f}" if match else "   N/A")
                    self.report.append(f"  {plat:>8}: {' → '.join(cpi_values)}")

                self.report.extend([f"```", ""])

                # ROI 趋势表
                self.report.extend([
                    f"### 每日 ROI 趋势",
                    f"",
                    f"| 日期 | " + " | ".join(sorted(platforms)) + " |",
                    f"|------|" + "|".join(["------" for _ in platforms]) + "|",
                ])

                for date in dates[-7:]:  # 最近 7 天
                    row_values = []
                    for plat in sorted(platforms):
                        match = next((d for d in daily if d["date_id"] == date and d["platform_code"] == plat), None)
                        row_values.append(f"{match['roi']:.2f}" if match else "N/A")
                    self.report.append(f"| {date} | " + " | ".join(row_values) + " |")

        except Exception as e:
            logger.error(f"Trends section failed: {e}")

        self.report.extend(["", ""])

    def _insights_section(self, ws, we):
        """AI 洞察与建议"""
        self.report.extend([
            "## 七、AI 洞察与建议",
            "",
            "_以下洞察基于本周数据自动生成 — 请结合业务经验做最终判断_",
            "",
        ])

        insights = self._generate_insights(ws, we)
        # 如果 insights 是字符串，按换行分割成列表
        if isinstance(insights, str):
            lines = [line.strip() for line in insights.split('\n') if line.strip()]
        else:
            lines = insights

        for line in lines:
            self.report.append(line)
            self.report.append("")

        self.report.extend(["", ""])

    def _get_weekly_summary(self, start_date: str, end_date: str) -> dict:
        try:
            overall = self._get_aggregated_kpis(start_date, end_date)
            channels = self.db.fetch_all(f"""
                SELECT platform_name, SUM(spend) AS spend, SUM(installs) AS installs,
                       ROUND(SUM(revenue)*1.0/NULLIF(SUM(spend),0),4) AS roi,
                       ROUND(SUM(spend)*1.0/NULLIF(SUM(installs),0),4) AS cpi,
                       ROUND(SUM(clicks)*100.0/NULLIF(SUM(impressions),0),4) AS ctr
                FROM fact_ad_performance f JOIN dim_platform p ON f.platform_id=p.platform_id
                WHERE date_id BETWEEN ? AND ?
                GROUP BY platform_name
            """, (start_date, end_date))
            top_countries = self.db.fetch_all(f"""
                SELECT c.country_code, SUM(spend) AS spend, SUM(installs) AS installs,
                       ROUND(SUM(revenue)*1.0/NULLIF(SUM(spend),0),4) AS roi
                FROM fact_ad_performance f JOIN dim_country c ON f.country_id=c.country_id
                WHERE date_id BETWEEN ? AND ?
                GROUP BY c.country_code ORDER BY spend DESC LIMIT 5
            """, (start_date, end_date))
            return {
                "overall": overall or {},
                "channels": [dict(ch) for ch in channels],
                "top_countries": [dict(tc) for tc in top_countries],
                "start_date": start_date,
                "end_date": end_date,
            }
        except Exception as e:
            self.logger.error(f"Get weekly summary failed: {e}")
            return {}

    def _call_deepseek(self, summary: dict, api_key: str) -> str:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        overall = summary.get("overall", {})
        channels = summary.get("channels", [])
        top_countries = summary.get("top_countries", [])
        prompt = f"""
你是海外短剧/游戏投放数据分析师。请根据以下周报数据，写出一段200字内的分析洞察和建议。

报告周期：{summary.get('start_date')} 至 {summary.get('end_date')}

整体表现：
- 总花费: ${overall.get('total_spend',0):.2f}
- 总安装: {overall.get('total_installs',0):.0f}
- 总收入: ${overall.get('total_revenue',0):.2f}
- 整体CPI: ${overall.get('cpi',0):.2f}
- 整体ROI: {overall.get('roi',0):.2f}
- 整体CTR: {overall.get('ctr',0):.2f}%

渠道细分：
{chr(10).join([f"- {c['platform_name']}: 花费${c['spend']:.0f}, CPI=${c['cpi']:.2f}, ROI={c['roi']:.2f}, CTR={c['ctr']:.2f}%" for c in channels])}

花费TOP5国家：
{chr(10).join([f"- {c['country_code']}: 花费${c['spend']:.0f}, ROI={c['roi']:.2f}" for c in top_countries])}

请输出：
1. 最突出的问题或亮点（1个）
2. 一条可执行的优化建议（如预算调整、素材方向等）
3. 一条风险提示（如有）
只输出正文，不要其他内容。
"""
        payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 500}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self.logger.error(f"DeepSeek API call failed: {e}")
            return ""
        
    def _generate_insights(self, ws, we) -> list[str]:
        insights = []
        deepseek_key = getattr(settings, 'DEEPSEEK_API_KEY', None) or os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            try:
                summary = self._get_weekly_summary(ws, we)
                if summary:
                    ai_text = self._call_deepseek(summary, deepseek_key)
                    if ai_text:
                        for line in ai_text.split('\n'):
                            line = line.strip()
                            if line:
                                insights.append(line)
                        return insights
            except Exception as e:
                logger.warning(f"DeepSeek failed, fallback: {e}")
        # 降级规则（原有逻辑）
        try:
            channels = self.db.fetch_all(f"""
                SELECT p.platform_name, SUM(f.spend) AS spend, SUM(f.installs) AS installs,
                       ROUND(SUM(f.revenue)*1.0/NULLIF(SUM(f.spend),0),4) AS roi
                FROM fact_ad_performance f JOIN dim_platform p ON f.platform_id=p.platform_id
                WHERE f.date_id BETWEEN '{ws}' AND '{we}'
                GROUP BY p.platform_code ORDER BY roi DESC
            """)
            if channels and len(channels) >= 2:
                best, worst = channels[0], channels[-1]
                if best["roi"] > worst["roi"] * 1.5:
                    insights.append(f"**预算分配建议**: {best['platform_name']} 本周 ROI ({best['roi']:.2f}) 显著高于 {worst['platform_name']} ({worst['roi']:.2f})，建议适当增加 {best['platform_name']} 预算占比。")
            daily_cpi = self.db.fetch_all(f"""
                SELECT date_id, ROUND(SUM(spend)*1.0/NULLIF(SUM(installs),0),4) AS cpi
                FROM fact_ad_performance WHERE date_id BETWEEN '{ws}' AND '{we}'
                GROUP BY date_id ORDER BY date_id
            """)
            if daily_cpi and len(daily_cpi) >= 3:
                cpi_vals = [d["cpi"] for d in daily_cpi if d["cpi"]]
                if cpi_vals:
                    trend = (cpi_vals[-1] - cpi_vals[0]) / cpi_vals[0] * 100
                    if trend > 10:
                        insights.append(f"**CPI 上涨预警**: 本周 CPI 上升 {trend:.1f}%，建议检查投放质量。")
                    elif trend < -10:
                        insights.append(f"**CPI 优化良好**: 本周 CPI 下降 {abs(trend):.1f}%，可考虑放量。")
            weekend = self.db.fetch_one(f"SELECT ROUND(AVG(cpi),4) AS cpi FROM (SELECT ROUND(SUM(spend)*1.0/NULLIF(SUM(installs),0),4) AS cpi FROM fact_ad_performance f JOIN dim_date d ON f.date_id=d.date_id WHERE f.date_id BETWEEN '{ws}' AND '{we}' AND d.is_weekend=1 GROUP BY f.date_id)")
            weekday = self.db.fetch_one(f"SELECT ROUND(AVG(cpi),4) AS cpi FROM (SELECT ROUND(SUM(spend)*1.0/NULLIF(SUM(installs),0),4) AS cpi FROM fact_ad_performance f JOIN dim_date d ON f.date_id=d.date_id WHERE f.date_id BETWEEN '{ws}' AND '{we}' AND d.is_weekend=0 GROUP BY f.date_id)")
            if weekend and weekday and weekend["cpi"] and weekday["cpi"] and weekend["cpi"] > weekday["cpi"] * 1.2:
                insights.append(f"**周末效应**: 周末 CPI ({weekend['cpi']:.2f}) 比平日高 {(weekend['cpi']/weekday['cpi']-1)*100:.0f}%，建议周末预算适当收缩。")
        except Exception as e:
            logger.error(f"Rule insights failed: {e}")
        if not insights:
            insights.append("本周各指标表现平稳，未检测到显著异常。")
        return insights

    def _footer(self):
        self.report.extend([
            f"---",
            f"",
            f"*本报告由 AI Agent 自动生成 | 海外广告投流数据分析项目*",
            f"*数据来源: Meta Ads API / TikTok Ads API / Google Ads API / AppsFlyer API*",
            f"*核心指标: CPI / CPM / CTR / ROI (ROAS) / LTV*",
        ])

    def _get_aggregated_kpis(self, start_date: str, end_date: str) -> dict:
        """获取聚合 KPI"""
        result = self.db.fetch_one("""
            SELECT
                SUM(spend) AS total_spend,
                SUM(impressions) AS total_impressions,
                SUM(clicks) AS total_clicks,
                SUM(installs) AS total_installs,
                SUM(revenue) AS total_revenue,
                ROUND(SUM(spend) * 1.0 / NULLIF(SUM(installs), 0), 4) AS cpi,
                ROUND(SUM(spend) * 1000.0 / NULLIF(SUM(impressions), 0), 4) AS cpm,
                ROUND(SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0), 4) AS ctr,
                ROUND(SUM(revenue) * 1.0 / NULLIF(SUM(spend), 0), 4) AS roi,
                ROUND(SUM(installs) * 100.0 / NULLIF(SUM(clicks), 0), 4) AS cvr
            FROM fact_ad_performance
            WHERE date_id BETWEEN ? AND ?
        """, (start_date, end_date))

        return dict(result) if result else {}

    # ==================== 发布推送 ====================

    def publish_report(self, report_md: str, channel: str = "file") -> bool:
        """
        将报告推送到指定渠道

        Args:
            report_md: 报告 Markdown 内容
            channel: 'file' | 'email' | 'dingtalk' | 'feishu' | 'slack'

        Returns:
            bool: 推送是否成功
        """
        if channel == "file":
            # 已经保存到文件
            return True

        if channel == "dingtalk":
            return self._push_dingtalk(report_md)

        if channel == "feishu":
            return self._push_feishu(report_md)

        if channel == "slack":
            return self._push_slack(report_md)

        logger.warning(f"Unsupported push channel: {channel}")
        return False

    def _push_dingtalk(self, report_md: str) -> bool:
        """钉钉 Webhook 推送 (需配置 DINGTALK_WEBHOOK_URL)"""
        import os
        webhook_url = os.getenv("DINGTALK_WEBHOOK_URL")
        if not webhook_url:
            logger.warning("DINGTALK_WEBHOOK_URL not configured")
            return False

        import requests
        # 钉钉限制消息长度，取前 20000 字符
        message = {"msgtype": "markdown", "markdown": {"title": "海外广告投流周报", "text": report_md[:20000]}}
        try:
            resp = requests.post(webhook_url, json=message, timeout=10)
            resp.raise_for_status()
            logger.info("Report pushed to DingTalk successfully")
            return True
        except Exception as e:
            logger.error(f"DingTalk push failed: {e}")
            return False

    def _push_feishu(self, report_md: str) -> bool:
        """飞书 Webhook 推送"""
        # TODO: 实现飞书推送
        logger.warning("Feishu push not yet implemented")
        return False

    def _push_slack(self, report_md: str) -> bool:
        """Slack Webhook 推送"""
        # TODO: 实现 Slack 推送
        logger.warning("Slack push not yet implemented")
        return False


# ==================== CLI 入口 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Weekly Report Agent")
    parser.add_argument("--week-ending", type=str, help="Week ending date (YYYY-MM-DD)")
    parser.add_argument("--no-save", action="store_true", help="Do not save to file")
    parser.add_argument("--push", type=str, choices=["dingtalk", "feishu", "slack"],
                        help="Push to channel")
    args = parser.parse_args()

    agent = WeeklyReportAgent()
    report = agent.run(
        week_ending=args.week_ending,
        save_to_file=not args.no_save,
    )

    if args.push:
        agent.publish_report(report, channel=args.push)

    # Print report summary to terminal
    print(report[:3000])
    print(f"\n... (full report: {len(report)} chars)")
