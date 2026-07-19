# 校园科创导航智能体

面向在校生的可信赛事导航与参赛执行助手。系统把官方通知解析、人工核验、赛事隔离 RAG、资格门控、个性化推荐和项目任务管理串成完整闭环。

## 核心能力

- **可信赛事库**：赛事按年份独立存储，报名截止日期直接来自 Ground Truth，不做演示性平移或自动改写。
- **证据一致问答**：回答可追溯到官方 PDF/Word 的页码、原文、链接、获取日期和核验日期。
- **推荐门控**：未核验赛事仅显示为“候选信息”，不进入正式推荐；已截止赛事与硬条件不符赛事均为 `score=null`。
- **多年份识别**：用户指定年份时查询对应版本；未指定年份时明确使用“最新已核验版本”；没有已核验版本时追问年份。
- **我的项目**：将仍可报名的已核验赛事加入工作台，管理项目状态、任务计划、材料清单和完成进度，并导出 ICS 日历。
- **隐私可控**：用户可删除画像，关联项目和任务同步删除；系统不要求身份证号、住址等敏感个人信息。

## 数据现状

仓库现包含 **177 条**按赛事、年份和赛道隔离的赛事数据，其中 130 条已基于真实官方 PDF/Word 完成人工核验（trusted_level=A / data_status=verified），140 条已锚定官方来源（official_source_status=found）。代表性赛事包括：

- 2026 中国软件杯大学生软件设计大赛
- 2026 中国大学生服务外包创新创业大赛
- 2026 中国大学生计算机设计大赛
- 2025 / 2026 高教社杯全国大学生数学建模竞赛
- 2026 全国大学生电子商务“创新、创意及创业”挑战赛
- 2026 MathorCup 高校数学建模挑战赛
- 2026 中国高校计算机大赛移动应用创新赛（启航赛道）
- 2025 中国国际大学生创新大赛（高教 / 产业 / 红旅 / 职教赛道）
- 2026 华为云具身智能大赛、昇腾AI创新大赛-算子挑战赛、大学生“AI+信息素养”大赛、UNIPP 大学生英语应用大赛（秋季赛）等本月新发现且报名进行中的赛事

另有 37 条赛事标记 `not_found`（未找到官方链接）——系统**绝不编造**日期、主办或奖项，仅保留原始字段并加红字提示，不进入正式推荐。其余未核验赛事保留为候选信息，不生成正式资格结论或推荐分数。

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

正式提交前可一键执行15条量化指标用例和现有24项回归测试：

```powershell
.\venv\Scripts\python.exe evals\run_formal_evaluation.py
```

运行后生成 [量化评测报告](docs/QUANTITATIVE_EVALUATION.md) 和机器可读结果 `evals/formal_results.json`。

当前共 24 条自动回归测试，另有 15 条量化指标用例，覆盖正常、异常和边界场景。关键断言包括：

- Ground Truth 日期与 SQLite 日期完全一致。
- 已截止赛事必须 `score=null`。
- 未核验赛事不得进入正式推荐或“我的项目”。
- 未知学历不得静默转换为“本科生”。
- Agent 对同一赛事只输出一个规范化截止日期。
- 项目任务、材料、ICS 和画像级联删除行为正确。

正式用例清单见 [docs/TEST_CASES.md](docs/TEST_CASES.md)。

## 真实数据闭环

```text
上传官方通知
  -> 自动解析并保留页码
  -> 人工修正结构化字段
  -> 关联原文证据
  -> 确认入库并标记 verified
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
|   |-- agent/graph.py            # 多年份解析与可解释 Agent 流程
|   |-- recommendation/engine.py  # 核验、资格、时间门控与评分
|   |-- rag/store.py              # 按赛事和年份隔离的证据检索
|   `-- parsing/pdf_extractor.py  # PDF/Word 页级解析
|-- frontend/                     # 无构建步骤的单页工作台
|-- data/
|   |-- raw/                      # 官方原始通知
|   |-- ground_truth/             # 人工核验结构化事实
|   |-- verified/                 # 核验记录
|   `-- campus_agent.db           # 默认 SQLite 数据库
|-- tests/                        # 24 条自动回归测试
|-- docs/                         # 架构、部署、合规、用例、演示脚本
|-- demo/campus-agent-demo.webm   # 4 分 59 秒操作演示
|-- Dockerfile
|-- compose.yaml
|-- .env.example
`-- start.ps1
```

## 配置项

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | 本地 SQLite | 可切换为 PostgreSQL SQLAlchemy URL |
| `RAG_USE_ST` | `自动` | 是否启用真实语义向量：`0` 强制关、`1` 强制开、不设则**本地有 all-MiniLM-L6-v2 即默认开启真·语义检索**（详见 [RAG 架构](docs/RAG_ARCHITECTURE.md)） |
| `CHROMA_HOST` | 空 | 远程 Chroma 地址；为空时使用本地检索 |
| `CHROMA_PORT` | `8000` | 远程 Chroma 端口 |
| `AGENT_LLM_API_KEY` | 空 | 可选的 OpenAI 兼容模型密钥；**配置后即对答案/组队文案做自然语言润色**，引用编号与门控结论不被改写（破坏则自动回退原稿） |
| `AGENT_LLM_BASE_URL` | 空 | 可选的兼容接口地址（如 `https://api.deepseek.com/v1` 接 DeepSeek；默认官方地址） |
| `AGENT_LLM_MODEL` | 空 | 可选模型名；为空时使用确定性模板 |

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
- [4 分 59 秒演示视频](demo/campus-agent-demo.webm)

## 常见问题

**为什么某个赛事没有推荐分数？**  
未核验、已截止或硬性资格不满足时，系统不会给出误导性分数；接口返回 `score=null` 并说明原因。

**为什么同名赛事会提示年份？**  
赛事规则按年度变化。存在已核验版本时系统会明确标注使用的最新年份；只有未核验版本时必须由用户指定年份。

**为什么不能把候选赛事加入项目？**  
“我的项目”属于正式执行流程，只接受仍可报名且已人工核验的赛事，防止用未经确认的日期生成任务和日历提醒。

**如何重建 SQLite 数据库？**  
停止服务后删除 `data/campus_agent.db`，再次启动应用即可按当前 Ground Truth 建表并灌入数据。重建前请确认没有需要保留的用户画像或项目数据。
