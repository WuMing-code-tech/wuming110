# 海外广告投流自动化分析系统

[![Python](https://img.shields.io/badge/Python-3.14-blue)](https://www.python.org/)
[![Metabase](https://img.shields.io/badge/Metabase-0.62-green)](https://www.metabase.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-blue)](https://www.sqlite.org/)

> 从广告平台数据采集到 AI 自动生成优化建议的全链路解决方案。

## 📌 项目简介

广告投流数据的自动化分析系统，涵盖 **Meta Ads、TikTok Ads、Google Ads、AppsFlyer** 多平台数据接入、ETL 处理、核心指标计算（CPI、CPM、CTR、ROI、LTV）、**AI 智能周报**（DeepSeek API）以及 **Metabase** 可视化看板。

**核心价值**：自动识别低效渠道（TikTok），输出预算重分配建议，预期整体 ROI 提升 15%+。

## 🛠️ 技术栈

| 类别       | 技术                                                         |
| ---------- | ------------------------------------------------------------ |
| 后端       | Python (pandas, requests, sqlite3)                          |
| 数据库     | SQLite                                                      |
| 可视化     | Metabase                                                    |
| AI 模型    | DeepSeek API                                                |
| 开发辅助   | Claude Code                                                 |
| 自动化     | ETL 管道 + 异常检测 Agent + 周报生成 Agent                   |

## 📊 核心功能

- **多平台数据接入**：Meta、TikTok、Google、AppsFlyer 连接器（支持真实 API 或模拟数据）
- **ETL 管道**：数据提取 → 标准化 → 指标计算 → 加载到星型模型
- **核心指标**：CPI、CPM、CTR、ROI、LTV、留存率、素材疲劳度
- **AI Agent**：每周自动生成 Markdown 周报，调用 DeepSeek 输出三条可执行优化建议（附预算调整、素材策略、风险预警）
- **异常检测**：CPI 突增（2σ）、CTR 骤降、ROI 低于阈值、素材疲劳
- **可视化看板**：Metabase 仪表盘，包含渠道对比、国家排行、素材 ROI、趋势图、LTV 分析等

## 🔍 成果展示

### AI 自动生成的周报节选

> **亮点与问题**：TikTok Ads 花费占比 41%，ROI 仅 1.49，远低于 Google（2.93），存在“高量低效”问题。  
> **优化建议**：削减 TikTok 预算 30%，转移至 Google 及日韩市场，预期整体 ROI 提升 15-20%。  
> **风险提示**：美国市场 ROI 低于均值，建议设置预警线（<1.8）。

### Metabase 看板截图

（此处可插入截图，建议将截图放在 `docs/` 目录并在 README 中引用）

## 🚀 快速启动（脱敏版）

> **注意**：本仓库仅包含脱敏代码，真实 API Key 需自行配置。如需完整运行，请参考以下步骤。

```bash
# 1. 克隆仓库
git clone https://github.com/WuMing-code-tech/wuming110.git
cd wuming110

# 2. 创建虚拟环境并安装依赖
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入真实 API Key（或跳过，使用模拟数据）

# 4. 生成模拟数据（无需真实 API）
python scripts/generate_data.py

# 5. 初始化数据库
python db/connection.py --init

# 6. 运行 ETL（全量）
python etl/orchestrator.py --mode full

# 7. 生成 AI 周报
python ai_agent/weekly_report_agent.py
