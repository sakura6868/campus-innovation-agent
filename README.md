# 校园科创导航智能体

[![CI](https://github.com/sakura6868/campus-innovation-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/sakura6868/campus-innovation-agent/actions/workflows/ci.yml)

面向在校生的可信赛事导航与参赛执行助手。系统把官方通知解析、官网来源确认、赛事隔离 RAG、资格门控、个性化推荐和项目任务管理串成完整闭环。

## 核心能力

- **可信赛事库**：赛事按年份独立存储，报名截止日期直接来自 Ground Truth，不做演示性平移或自动改写。
- **证据一致问答**：回答可追溯到官方 PDF/Word 页码或网页原文、官方链接、获取日期和来源检查日期。
- **推荐门控**：已截止赛事与硬条件不符赛事均为 `score=null`；来源核验状态会在推荐结果中透明提示，不把“待核验”伪装成已确认事实。
- **多年份识别**：用户指定年份时查询对应版本；未指定年份时明确使用“最新官网来源已确认版本”；没有合格版本时追问年份。
- **我的项目**：将仍可报名且基础资料完整的赛事加入工作台，管理项目状态、任务计划、材料清单和完成进度，并导出 ICS 日历；来源状态始终随赛事展示。
- **个性化首页**：登录后聚合画像、今日重点、7 日内节点、项目进度、适合的新机会和官方变化；用户可以从一个焦点任务直接进入项目、赛事详情或智能问答。
- **赛事大厅检索**：赛事库首次加载后在浏览器本地仅检索赛事正式名称，避免简介中的类比赛事提及造成误命中；可与类别、年份、可信状态筛选叠加使用。
- **隐私可控**：用户可删除画像，关联项目和任务同步删除；系统不要求身份证号、住址等敏感个人信息。
- **签名用户会话**：登录后颁发短期 HMAC 签名令牌；画像、组合、项目、Agent 历史和情报收件箱只能由所有者会话访问。管理员令牌与用户会话密钥独立。

## 赛事态势感知与可验证机会规划

项目新增三项可串联演示的工程能力：

- **动态赛事雷达**：所有具备可追溯官方来源的展示赛事都会进入监控。当前可行动赛事采用 6–24 小时高频“行动提醒”；已截止、执行中和往届赛事仍以每周一次的“资料维护”追踪新赛季公告、补充通知与结果发布。网页、PDF 与 DOCX 通知生成规范化快照和新旧差异；纯扫描型 PDF 与脚本动态赛事页分别采用文件／响应指纹检测，不伪造字段变化。行动层关键变化和资料维护层线索都只进入人工审核队列，绝不自动覆盖可信事实；连续抓取失败会保留最后可信版本并标记来源异常。
- **科创机会组合优化**：不再只对单场赛事排序，而是在资格、报名状态、每周可用时间、截止冲突和已有项目约束下，精确枚举最多四场赛事的可行组合，输出稳妥型、均衡型和冲刺型三套方案；采用方案时在单一事务中重新校验，任一项失效即整组回滚。

三项能力形成同一条闭环：

```text
官网变化 -> 雷达差异 -> 人工审核 -> 事实与证据更新 -> 组合重新规划 -> 项目风险提醒
```

## 评审演示增强（V0.5 参赛候选版）

在上述可信底座上，当前版本将成熟产品模式做了轻量、独立实现：

- **决策运行剧场**：每次 Agent 问答返回 `run_id` 和结构化节点轨迹，逐步展示状态、真实耗时、证据数、数据版本与兜底原因；只公开可审计业务动作，不暴露模型隐式推理。运行摘要写入 `agent_runs`，支持历史查看和冻结输入回放。
- **机会提醒 + 雷达维护**：前台“机会提醒”把官方变化翻译为“现在该处理什么、当前可行动机会、我的参赛计划”，不向学生暴露扫描频率和来源异常；管理员“数据维护”页才展示来源健康度、规则、扫描和审核队列。来源分为高频“行动提醒”和低频“资料维护”两层，按到期时间小批次扫描（默认每 15 分钟检查一次，单批最多 12 个来源）；资料维护层不产出字段写回建议，只把可能的新赛季线索交给人工审核。
- **参赛执行闭环**：新项目自动生成“资格核对 → 组队选题 → 报名 → 方案 → 制作 → 提交 → 答辩”阶段模板；任务支持依赖、阻塞原因以及雷达/证据来源，并可切换列表、看板、日历和时间线视图。
- **科创作战地图**：稳妥、均衡、冲刺三套组合同时输出技能、能力缺口、赛事、材料和里程碑节点；已有项目受雷达变化影响时，下游任务进入阻塞态。
- **质量与安全校验**：自动回归覆盖可信数据、推荐门控、Agent、项目闭环、雷达差异、SSRF 与会话隔离；冻结评测与当前运行指标分层保存，避免把历史成绩冒充实时数据。

完整评审演示链路：

```text
官方来源变化 → 噪声过滤 → 字段级差异 → 人工审核
→ 用户收件箱 → 转执行任务 / 重新规划 → 作战地图风险联动
→ Agent 决策剧场 → 参赛执行闭环
```

雷达的管理写操作继续受 `X-Admin-Token` 保护。服务内自动扫描可通过 `RADAR_AUTOMATION_ENABLED`、`RADAR_SCAN_INTERVAL_SECONDS` 与 `RADAR_SCAN_BATCH_SIZE` 调整；自动扫描工作流位于 `.github/workflows/source-radar.yml`，需要在 GitHub Actions 中配置 `RADAR_BASE_URL` 和 `ADMIN_API_TOKEN` 两个 Secrets；也可通过管理界面的“立即扫描”和“演示截止日期变化”进行本地验收。

## 数据现状

当前赛事大厅展示 **146 条**赛事；另有 **33 条**旧赛事、地方赛、重复项或无法纠正名称的记录被归档保留审计。展示赛事均已定位来源，其中 **18 条**完成核验、**16 条**达到 A 级证据标准。官方通知仅给出团队上限时，产品规则按最少 1 人处理，并明确不将此视为官网逐字结论。这里的 `verified` 表示官网来源和证据通过自动完整性规则，不表示人工替代用户作出最终资格确认。代表性赛事包括：

- 2026 中国软件杯大学生软件设计大赛
- 2026 中国大学生服务外包创新创业大赛
- 2026 中国大学生计算机设计大赛
- 2025 / 2026 高教社杯全国大学生数学建模竞赛
- 2026 全国大学生电子商务“创新、创意及创业”挑战赛
- 2026 MathorCup 高校数学建模挑战赛
- 2026 中国高校计算机大赛移动应用创新赛（启航赛道）
- 2025 中国国际大学生创新大赛（高教 / 产业 / 红旅 / 职教赛道）
- 2026 华为云具身智能大赛、昇腾AI创新大赛-算子挑战赛、大学生“AI+信息素养”大赛、UNIPP 大学生英语应用大赛（秋季赛）等本月新发现且报名进行中的赛事

无法定位当前赛季官方来源的记录会被归档保留审计；系统**绝不编造**日期、主办或奖项。其余来源完整度较低的赛事保留核验状态，并在结果中说明信息边界。

## 一键启动

### Windows 本地运行

```powershell
.\start.ps1
```

脚本会在缺少虚拟环境时自动创建 `venv` 并安装依赖，然后启动服务。默认访问：

- 应用：[http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

指定端口：

```powershell
.\start.ps1 -Port 8011
```

### macOS / Linux 本地运行

```bash
chmod +x start.sh
./start.sh
```

也可用 `./start.sh 8011` 指定端口。脚本会创建 `venv`、安装依赖并启动本地服务。

### Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build
```

容器启动后访问 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)。SQLite 数据、上传文件和本地检索数据均持久化到 `data/`。

### 手动启动

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn api:app --app-dir src --host 127.0.0.1 --port 8000
```

### 评审测试账号与演示模式

首次启动会幂等创建一名仅用于演示的普通学生账号：

| 用户名 | 密码 | 初始画像 |
| --- | --- | --- |
| `test` | `test123` | 本科大二、计算机科学与技术、Python / 算法 / 前端开发、12 小时/周、3 人队 |

该账号不具备管理员权限，所有画像均为虚构数据。登录后可直接验证首页、推荐、行动路线、项目工作台和智能顾问；右上角可切换内置学生画像以预览不同身份的推荐差异。公开部署时请勿向测试账号写入真实个人信息或真实项目资料。

## ☁️ 云端部署（Render）与更新

本项目已配置 GitHub + Render 自动部署：代码 push 到 GitHub 的 `master` 分支后，Render 通过 `render.yaml`（Blueprint）自动重新构建并上线，**无需手动操作 Render 控制台**。

### 首次部署（一次性）

1. 在 GitHub 创建仓库（本仓库为 `sakura6868/campus-innovation-agent`，私有，`master` 分支）。
2. 打开预填链接用 GitHub 登录 Render：
   `https://dashboard.render.com/new/blueprint?repo=https://github.com/sakura6868/campus-innovation-agent`
3. 授权时勾选允许访问该私有仓库；确认将创建两个资源：
   - `campus-innovation-agent`（Web 服务，free）
   - `campus-db`（PostgreSQL，free，数据持久化）
4. 点 **Deploy Blueprint**，等待 3–8 分钟构建完成，即可访问
   `https://campus-innovation-agent.onrender.com`。

> **健康检查（可选但建议）**：服务启动后默认暴露 `GET /health` 接口（返回
> `{"status":"ok"}`）。可在 Render 服务设置页把 **Health Check Path** 设为
> `/health`，让平台自动探活、异常时自动重启，提升稳定性观感与可用性。
> 健康检查只返回数据库连通状态，不返回连接地址或凭据。所有 `/api/admin/*`
> 接口强制使用 `X-Admin-Token`；Render Blueprint 会自动生成 `ADMIN_API_TOKEN`。

### 部署踩过的坑（已修复，记录备查）

- `requirements.txt` 中 `pdfplumber>=3.0` 版本不存在（最新 `0.11.10`）→ 已改为 `>=0.11`；并补充 `psycopg2-binary>=2.9`（连接 Postgres 必需）。
- `render.yaml` 旧版把 Postgres 写在 `services:` 下（`type: postgres`）→ 报 `unknown type "postgres"`；Postgres 必须放在顶层 `databases:` 块，且 `fromDatabase.name` 与该块 `name` 一致。
- `rag/store.py` 原本在模块顶层 `import chromadb` → Render 未装该库时启动即崩溃；已改为构造器内**惰性导入 + 未安装自动降级本地检索**。
- Render 注入的 `DATABASE_URL` 协议头为 `postgres://`，而 SQLAlchemy 2.0 只认 `postgresql://` → `db.py` 已做归一化。

### 以后怎么更新

> 核心：把新代码 push 到 GitHub `master` → Render 自动重新部署。

- **方式 A（找我改）**：在对话里说明要改什么，我直接在沙箱改代码、提交并 push；每次 push 需要你的 GitHub PAT（建议用完即 revoke）。
- **方式 B（自己改）**：本地 `git clone` 后修改，`git push` 即触发自动部署。

push 后一般无需去 Render 点按钮（auto-sync 会自动触发）；若未自动部署，到服务页点 **Manual Deploy → Deploy latest commit**。

### 免费套餐注意事项

- **冷启动**：15 分钟无访问服务休眠，首次打开需等 10–30 秒唤醒。
- **数据库保留**：免费 Postgres 90 天无访问会被自动删库；可设置定时访问（如每 10 天请求一次 `/health`）保活。
- **访问量**：无硬性人数上限，但单实例资源有限，适合教学/作业展示级别的几十人访问。

## 自动测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

正式提交前可一键执行 15 条量化指标用例和现有 59 项回归测试：

```powershell
.\venv\Scripts\python.exe evals\run_formal_evaluation.py
```

运行后生成 [量化评测报告](docs/QUANTITATIVE_EVALUATION.md) 和机器可读结果 `evals/formal_results.json`。

当前自动回归测试除原有可信、项目、Agent 与安全用例外，还覆盖组合容量约束与原子采用、雷达关键日期差异、SSRF 防护、DOCX 规范化和多年份消歧；另有 15 条量化指标用例。关键断言包括：

- Ground Truth 日期与 SQLite 日期完全一致。
- 已截止赛事必须 `score=null`。
- 已截止、缺少明确参赛对象或不满足硬性资格的赛事不得进入正式推荐或“我的项目”。
- 未知学历不得静默转换为“本科生”。
- Agent 对同一赛事只输出一个规范化截止日期。
- 项目任务、材料、ICS 和画像级联删除行为正确。
- 未登录访问用户资源返回 `401`，跨用户访问返回 `403`，本人签名会话通过。

正式用例清单见 [docs/TEST_CASES.md](docs/TEST_CASES.md)。

## 真实数据闭环

```text
上传官方通知
  -> 自动解析并保留页码
  -> 核对结构化字段与官方来源
  -> 关联原文证据
  -> 自动评估证据完整性并分类
  -> 刷新赛事隔离 RAG
  -> Agent 证据问答
  -> 资格门控与推荐
  -> 加入我的项目并执行任务
```

项目记录只保存 `competition_id`，截止日期始终从赛事主表实时读取，避免项目副本与官方事实产生分叉。

## 目录结构

```text
campus-innovation-agent/
|-- src/
|   |-- api.py                    # FastAPI、静态前端与业务接口
|   |-- db.py                     # SQLite/PostgreSQL 数据访问与项目工作台
|   |-- schemas.py                # 赛事、画像、推荐和项目模型
|   |-- trust.py                  # 官网来源与推荐资格统一判定
|   |-- agent/graph.py            # 多年份解析与可解释 Agent 流程
|   |-- recommendation/engine.py  # 核验、资格、时间门控与评分
|   |-- rag/store.py              # 按赛事和年份隔离的证据检索
|   `-- parsing/pdf_extractor.py  # PDF/Word 页级解析
|-- frontend/                     # 无构建步骤的单页工作台
|-- data/
|   |-- raw/                      # 官方原始通知
|   |-- ground_truth/             # 可追溯结构化事实与候选目录
|   |-- verified/                 # 来源检查记录
|   `-- campus_agent.db           # 默认 SQLite 数据库
|-- tests/                        # 56 条自动回归测试
|-- docs/                         # 架构、部署、合规、用例、演示脚本
|-- demo/campus-agent-demo-final.mp4 # 4分25秒正式演示视频（另含旧预览片段）
|-- Dockerfile
|-- compose.yaml
|-- .env.example
`-- start.ps1
```

## 配置项

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | 本地 SQLite | 可切换为 PostgreSQL SQLAlchemy URL |
| `AUTH_TOKEN_SECRET` | 进程启动时随机生成 | 签发用户会话；云端/多进程部署必须配置稳定的独立随机密钥 |
| `AUTH_TOKEN_TTL_SECONDS` | `28800` | 用户签名会话有效期，限制为 15 分钟至 24 小时 |
| `DEV_ADMIN_QUICK_LOGIN` | 未启用 | 开发预留接口，仅本机 `127.0.0.1` 调试时设为 `1`；还须设置 `ADMIN_API_TOKEN`。正式前端不展示快捷登录入口，线上环境保持未启用 |
| `RAG_USE_ST` | 示例配置为 `0` | `0` 使用轻量本地检索，`1` 启用已离线预热的真实语义向量；不设时仅在本地存在模型时自动启用（详见 [RAG 架构](docs/RAG_ARCHITECTURE.md)） |
| `CHROMA_HOST` | 空 | 远程 Chroma 地址；为空时使用本地检索 |
| `CHROMA_PORT` | `8000` | 远程 Chroma 端口 |
| `AGENT_LLM_API_KEY` | 空 | 可选的 OpenAI 兼容模型密钥；**配置后即对答案/组队文案做自然语言润色**，引用编号与门控结论不被改写（破坏则自动回退原稿） |
| `AGENT_LLM_BASE_URL` | 空 | 可选的兼容接口地址（如 `https://api.deepseek.com/v1` 接 DeepSeek；默认官方地址） |
| `AGENT_LLM_MODEL` | 空 | 可选模型名；为空时使用确定性模板 |
| `AGENT_LLM_PROVIDER` | 空 | LLM 提供方标识；接入通义千问时设 `qwen`，用于匹配对应兼容端点习惯 |
| `AGENT_LLM_TEMPERATURE` | `0.3` | 润色采样温度；越低越稳，仅影响自然语言润色层 |
| `WEB_SEARCH_RETRIES` | `1` | 联网补充尝试次数；失败立即回退本地证据链 |
| `WEB_SEARCH_TIMEOUT_SECONDS` | `4` | 单次联网补充超时上限（2–10 秒） |

> LLM 润色层用项目已依赖的 `requests` 直连任意 OpenAI 兼容 `/chat/completions`，**无需安装 `openai` SDK**；未配置 Key 时完全不触发网络，答案回退到确定性模板，保证离线可复现。

默认配置无需外部模型或网络即可完成可信检索、门控、推荐和项目管理。

## 提交文档

- [系统架构与模块说明](docs/ARCHITECTURE.md)
- [RAG 混合检索与赛事隔离创新点](docs/RAG_ARCHITECTURE.md)
- [部署与依赖说明](docs/DEPLOYMENT.md)
- [数据与隐私合规说明](docs/COMPLIANCE.md)
- [正式测试用例集](docs/TEST_CASES.md)
- [量化评测报告](docs/QUANTITATIVE_EVALUATION.md)
- [固定账号端到端验收记录](docs/DEMO_WALKTHROUGH.md)
- [版本冻结说明](docs/RELEASE_FREEZE.md)
- [3-5 分钟演示视频脚本](docs/DEMO_VIDEO_SCRIPT.md)
- [正式演示视频（4 分 25 秒，1080p）](demo/campus-agent-demo-final.mp4)
- [演示视频录制与交付说明](demo/README.md)

## 常见问题

**为什么某个赛事没有推荐分数？**  
已截止或硬性资格不满足时，系统不会给出误导性分数；基础资料完整但来源尚待补充的赛事可以参与匹配，并会明确展示来源状态与报名核对提示。

**为什么同名赛事会提示年份？**  
赛事规则按年度变化。存在官网来源与关键证据完整的版本时系统会明确标注使用的最新年份；只有候选版本时必须由用户指定年份。

**为什么不能把候选赛事加入项目？**  
“我的项目”属于执行流程，只接受仍可报名且基础资料完整的赛事。系统提供辅助判断，用户报名前仍须查看官网最新通知。

**如何重建 SQLite 数据库？**  
停止服务后删除 `data/campus_agent.db`，再次启动应用即可按当前 Ground Truth 建表并灌入数据。重建前请确认没有需要保留的用户画像或项目数据。
