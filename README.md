# 校园科创导航智能体

[![CI](https://github.com/sakura6868/campus-innovation-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/sakura6868/campus-innovation-agent/actions/workflows/ci.yml)

面向在校生的可信赛事导航与参赛执行助手。系统把官方通知解析、官网来源确认、赛事隔离 RAG、资格门控、个性化推荐和项目任务管理串成完整闭环。

## 🏆 参赛提交 / For Judges

> 本作品参加**中兴赛道 · 命题五「自主命题智能体」**。评委请先看 [`docs/SUBMISSION.md`](docs/SUBMISSION.md)：六件提交物位置、本地一键运行、测试账号、复现评测证据与 100 分评审维度对照，一处可查。
>
> - 测试账号：**`test` / `test123`**（登录页可「一键体验」零输入进入）
> - 提交清单：可运行作品 / 技术文档 / README / 用例集(44 条) / 演示视频(3—5 min) / 合规说明 —— 详见 SUBMISSION.md

## 核心能力

- **可信赛事库**：赛事按年份独立存储，报名截止日期直接来自 Ground Truth，不做演示性平移或自动改写。
- **证据一致问答**：回答可追溯到官方 PDF/Word 页码或网页原文、官方链接、获取日期和来源检查日期。
- **推荐门控**：未核验赛事仅显示为“候选信息”，不进入正式推荐；已截止赛事与硬条件不符赛事均为 `score=null`。
- **多年份识别**：用户指定年份时查询对应版本；未指定年份时明确使用“最新官网来源已确认版本”；没有合格版本时追问年份。
- **我的项目**：将仍可报名且关键证据完整的赛事加入工作台，管理项目状态、任务计划、材料清单和完成进度，并导出 ICS 日历。
- **隐私可控**：用户可删除画像，关联项目和任务同步删除；系统不要求身份证号、住址等敏感个人信息。
- **签名用户会话**：登录后颁发短期 HMAC 签名令牌；画像、组合、项目、Agent 历史和情报收件箱只能由所有者会话访问。管理员令牌与用户会话密钥独立。

## 赛事态势感知与可验证机会规划

项目新增三项可串联演示的工程能力：

- **动态赛事雷达**：为已核验赛事建立官方来源监控，对网页、PDF 与 DOCX 通知生成规范化快照和新旧差异；报名/提交截止等关键变化只进入人工审核队列，绝不自动覆盖可信事实。连续抓取失败会保留最后可信版本并标记来源异常。
- **科创机会组合优化**：不再只对单场赛事排序，而是在资格、报名状态、每周可用时间、截止冲突和已有项目约束下，精确枚举最多四场赛事的可行组合，输出稳妥型、均衡型和冲刺型三套方案；采用方案时在单一事务中重新校验，任一项失效即整组回滚。

三项能力形成同一条闭环：

```text
官网变化 -> 雷达差异 -> 人工审核 -> 事实与证据更新 -> 组合重新规划 -> 项目风险提醒
```

## 评审演示增强（V0.3）

在上述可信底座上，V0.3 将 GitHub 优秀项目中的产品模式做了轻量、独立实现：

- **决策运行剧场**：每次 Agent 问答返回 `run_id` 和结构化节点轨迹，逐步展示状态、真实耗时、证据数、数据版本与兜底原因；只公开可审计业务动作，不暴露模型隐式推理。运行摘要写入 `agent_runs`，支持历史查看和冻结输入回放。
- **雷达情报控制塔**：监控项支持包含/排除选择器、忽略正则、关注词、时区和抓取模式；页面展示来源健康度、字段级前后值和受影响项目/任务。已审核变化进入用户收件箱，可接受、忽略、转任务或触发重新规划。
- **参赛执行闭环**：新项目自动生成“资格核对 → 组队选题 → 报名 → 方案 → 制作 → 提交 → 答辩”阶段模板；任务支持依赖、阻塞原因以及雷达/证据来源，并可切换列表、看板、日历和时间线视图。
- **科创作战地图**：稳妥、均衡、冲刺三套组合同时输出技能、能力缺口、赛事、材料和里程碑节点；已有项目受雷达变化影响时，下游任务进入阻塞态。
- **质量驾驶舱**：`#/quality` 以可视化页面展示 15 项正式指标、59 项回归、86 条金标问答与安全门禁；`GET /api/system/quality` 保留机器可读契约。冻结评测与当前运行指标分开展示，避免把历史成绩冒充实时数据。

完整评审演示链路：

```text
官方来源变化 → 噪声过滤 → 字段级差异 → 人工审核
→ 用户收件箱 → 转执行任务 / 重新规划 → 作战地图风险联动
→ Agent 决策剧场 → 参赛执行闭环
```

雷达的管理写操作继续受 `X-Admin-Token` 保护。自动扫描工作流位于 `.github/workflows/source-radar.yml`，需要在 GitHub Actions 中配置 `RADAR_BASE_URL` 和 `ADMIN_API_TOKEN` 两个 Secrets；也可通过管理界面的“立即扫描”和“演示截止日期变化”进行本地验收。

## 数据现状

仓库现包含 **190 条**按赛事、年份和赛道隔离的赛事数据，其中 **154 条已找到官方来源**，**7 条同时具备四类关键字段证据**并达到正式推荐标准（`trusted_level=A / data_status=verified`；2026-09-13 快照，随报名截止动态变化）。官方通知仅给出团队上限时，产品规则按最少 1 人处理，并明确不将此视为官网逐字结论。这里的 `verified` 表示官网来源和证据通过自动完整性规则，不表示人工替代用户作出最终资格确认。代表性赛事包括：

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

## 自动测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

正式提交前可一键执行 15 条量化指标用例和现有 59 项回归测试：

```powershell
.\venv\Scripts\python.exe evals\run_formal_evaluation.py
```

运行后生成 [量化评测报告](docs/QUANTITATIVE_EVALUATION.md) 和机器可读结果 `evals/formal_results.json`。

当前自动回归测试除原有可信、项目、Agent 与安全用例外，还覆盖组合容量约束与原子采用、雷达关键日期差异、SSRF 防护、DOCX 规范化、PDF 坐标提取、高亮渲染及重启后坐标保留；另有 15 条量化指标用例。关键断言包括：

- Ground Truth 日期与 SQLite 日期完全一致。
- 已截止赛事必须 `score=null`。
- 未核验赛事不得进入正式推荐或“我的项目”。
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
|-- tests/                        # 59 条自动回归测试
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
| `AUTH_TOKEN_SECRET` | 进程启动时随机生成 | 签发用户会话；多进程部署必须配置稳定的独立随机密钥 |
| `AUTH_TOKEN_TTL_SECONDS` | `28800` | 用户签名会话有效期，限制为 15 分钟至 24 小时 |
| `RAG_USE_ST` | `自动` | 是否启用真实语义向量：`0` 强制关、`1` 强制开、不设则**本地有 all-MiniLM-L6-v2 即默认开启真·语义检索**（详见 [RAG 架构](docs/RAG_ARCHITECTURE.md)） |
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

## 界面模型切换（qwen 系列）

问答模块支持在界面上直接切换通义千问模型，无需改代码或重启服务：

- 问答输入区下方有 **模型下拉框**，可选 `qwen-plus` / `qwen-max` / `qwen-turbo`。
- 选择结果保存在浏览器 `localStorage`，刷新页面后保留。
- 每次提问会把所选模型通过 `?model=` 透传到后端，后端用同一个 `AGENT_LLM_API_KEY` 请求对应模型。
- 仅影响 Agent 答案的自然语言润色层；引用编号 `[n]`、资格门控与推荐结论由确定性逻辑生成，不受模型选择影响。

> 前提：已在环境变量（本地 `.env`）配置 `AGENT_LLM_API_KEY`、`AGENT_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`、`AGENT_LLM_MODEL=qwen-plus`、`AGENT_LLM_PROVIDER=qwen`。未配置 LLM 时下拉框无效，答案回退到确定性模板，不影响可信检索与推荐。

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
- [演示视频（mp4，校内平台可直接打开）](demo/campus-agent-demo.mp4)
- [演示视频（webm，备用）](demo/campus-agent-demo.webm)

## 常见问题

**为什么某个赛事没有推荐分数？**  
未核验、已截止或硬性资格不满足时，系统不会给出误导性分数；接口返回 `score=null` 并说明原因。

**为什么同名赛事会提示年份？**  
赛事规则按年度变化。存在官网来源与关键证据完整的版本时系统会明确标注使用的最新年份；只有候选版本时必须由用户指定年份。

**为什么不能把候选赛事加入项目？**  
“我的项目”属于正式执行流程，只接受仍可报名、官网来源已确认且关键证据完整的赛事。系统提供辅助判断，用户报名前仍须查看官网最新通知。

**如何重建 SQLite 数据库？**  
停止服务后删除 `data/campus_agent.db`，再次启动应用即可按当前 Ground Truth 建表并灌入数据。重建前请确认没有需要保留的用户画像或项目数据。
