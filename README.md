# 海外广告投流数据分析项目
# Overseas Advertising Performance Data Analysis

## 项目概览

本项目搭建海外广告投流数据的采集、存储、计算、可视化和智能分析全链路管道。

### 数据源
- **Meta Ads** (Facebook / Instagram)
- **TikTok Ads**
- **Google Ads**
- **AppsFlyer** (移动归因 MMP)

### 核心指标
| 指标 | 说明 | 计算公式 |
|------|------|----------|
| **CPI** | Cost Per Install | SUM(spend) / SUM(installs) |
| **CPM** | Cost Per Mille | SUM(spend) / SUM(impressions) × 1000 |
| **CTR** | Click-Through Rate | SUM(clicks) / SUM(impressions) × 100% |
| **ROI (ROAS)** | Return on Investment | SUM(revenue) / SUM(spend) |
| **LTV** | Lifetime Value | AppsFlyer 回传 D0/D7/D30 |

### 技术栈
- **数据管道**: Python 3.10+ (pandas, requests, sqlite3)
- **数据库**: SQLite
- **可视化**: Metabase (Docker)
- **AI Agent**: Claude Agent SDK
- **定时调度**: Claude Code Cron + Python schedule

## 快速启动

### 1. 环境配置
```bash
cp .env.example .env
# 编辑 .env 填入各广告平台的 API Key
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 初始化数据库
```bash
python db/connection.py --init
```

### 4. 运行 ETL 数据管道
```bash
# 全量同步（首次使用）
python etl/orchestrator.py --mode full

# 增量同步（日常使用）
python etl/orchestrator.py --mode incremental --days 1
```

### 5. AI Agent 自动化
```bash
# 每日自动取数
python ai_agent/daily_fetch_agent.py

# 异常检测
python ai_agent/anomaly_detector.py

# 周报生成
python ai_agent/weekly_report_agent.py
```

### 6. 启动 Metabase
```bash
docker run -d -p 3000:3000 \
  -v /Users/chen/Desktop/ADs_da/db:/data \
  metabase/metabase
# 访问 http://localhost:3000
# 运行看板配置脚本
python dashboards/metabase_setup.py
```

## 项目结构
```
ADs_da/
├── config/          # 全局配置 & 指标定义
├── db/              # 数据库 Schema & 连接
├── connectors/      # 广告平台 API 连接器
├── etl/             # ETL 数据管道
├── ai_agent/        # AI Agent 自动化层
├── dashboards/      # Metabase 看板配置
├── scheduled_tasks/ # 定时任务
└── tests/           # 测试
```
