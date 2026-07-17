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

仓库包含 21 份按赛事、年份和赛道隔离的数据，其中 12 份已基于真实官方 PDF/Word 完成人工核验：

- 2026 中国软件杯大学生软件设计大赛
- 2026 中国大学生服务外包创新创业大赛
- 2026 中国大学生计算机设计大赛
- 2025 高教社杯全国大学生数学建模竞赛
- 2026 全国大学生电子商务“创新、创意及创业”挑战赛
- 2026 MathorCup 高校数学建模挑战赛
- 2026 高教社杯全国大学生数学建模竞赛
- 2026 中国高校计算机大赛移动应用创新赛（启航赛道）
- 2025 中国国际大学生创新大赛高教主赛道
- 2025 中国国际大学生创新大赛产业赛道
- 2025 中国国际大学生创新大赛青年红色筑梦之旅赛道
- 2025 中国国际大学生创新大赛职教赛道

核心字段均关联页级证据。其余未核验赛事保留为候选信息，不生成正式资格结论或推荐分数。

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
| `RAG_USE_ST` | `0` | 是否尝试使用 sentence-transformers |
| `CHROMA_HOST` | 空 | 远程 Chroma 地址；为空时使用本地检索 |
| `CHROMA_PORT` | `8000` | 远程 Chroma 端口 |
| `AGENT_LLM_API_KEY` | 空 | 可选的 OpenAI 兼容模型密钥 |
| `AGENT_LLM_BASE_URL` | 空 | 可选的兼容接口地址 |
| `AGENT_LLM_MODEL` | 空 | 可选模型名；为空时使用确定性模板 |

默认配置无需外部模型或网络即可完成可信检索、门控、推荐和项目管理。

## 提交文档

- [系统架构与模块说明](docs/ARCHITECTURE.md)
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
