# 第三方依赖与开源组件说明

> 依据参赛手册「参赛注意事项」第 2 条：
> **允许使用开源框架、公开模型和第三方工具，但须在文档中说明来源、用途和使用方式。**
>
> 说明：本项目**未使用任何第三方数据集**——赛事数据均由团队依据各赛事组委会官网公开通知自行整理（见「六、数据来源」）。

---

## 一、核心开源依赖（运行时必需）

| 组件 | 来源 | 用途 | 使用方式 |
|---|---|---|---|
| **FastAPI** | https://github.com/fastapi/fastapi | 构建全部 HTTP API 接口层与自动 OpenAPI 文档 | 直接作为 Web 框架，定义 `@app.get/post` 路由 |
| **Uvicorn** | https://github.com/encode/uvicorn | ASGI 服务器，承载应用进程 | 启动命令 `uvicorn api:app`（见 `start.ps1`） |
| **Pydantic** v2 | https://github.com/pydantic/pydantic | 请求/响应数据校验、`src/schemas.py` 全部数据模型 | 以模型类声明接口契约与 ORM 序列化结构 |
| **SQLAlchemy** 2.0 | https://github.com/sqlalchemy/sqlalchemy | ORM 与数据库访问层（12 张表） | `src/db.py` 中声明模型与仓储查询 |
| **psycopg2-binary** | https://github.com/psycopg/psycopg2 | PostgreSQL 驱动（可选；仅配置 PostgreSQL 时使用，本地 SQLite 不依赖） | 由 `DATABASE_URL` 自动选择驱动 |
| **pdfplumber** | https://github.com/jsvine/pdfplumber | 抽取官方通知 **PDF** 的文本与表格 | 来源雷达解析 PDF、证据定位（`src/evidence/`） |
| **python-docx** | https://github.com/python-openxml/python-docx | 解析官方通知 **DOCX** | 来源雷达解析 Word 文档 |
| **requests** | https://github.com/psf/requests | HTTP 客户端 | ① 调用 LLM 接口 ② 联网补充检索 ③ 雷达抓取官方页面 |
| **httpx2** | PyPI `httpx2`（Starlette 1.x 起 TestClient 的依赖） | 仅用于自动化测试的 `TestClient` | 仅测试环境使用，不参与运行时 |

## 二、可选开源依赖（未安装也能完整运行）

项目对上述组件均**内置等价降级实现**，不安装不会导致功能缺失：

| 组件 | 来源 | 用途 | 未安装时的降级方式 |
|---|---|---|---|
| **LangGraph** | https://github.com/langchain-ai/langgraph | Agent 编排 | 自动降级到内置 `src/agent/_graph_shim.py`（已验证等价，本地默认即走此路） |
| **ChromaDB** | https://github.com/chroma-core/chroma | 向量检索库 | 惰性导入；不可用时降级为**本地隔离检索**（`src/rag/store.py`） |
| **sentence-transformers** | https://github.com/UKPLab/sentence-transformers | 语义向量（embedding） | 默认关闭（`RAG_USE_ST=1` 才启用），否则使用内置 `light-hash-256` 向量 |
| **langchain-openai** | https://github.com/langchain-ai/langchain | LLM 接入封装 | 未配置 `AGENT_LLM_API_KEY` 时，全部走确定性本地作答 |

> 以上四项在 `requirements.txt` 中均为**注释状态**，构建镜像时可省略，因此部署更快、更稳。

## 三、公开模型与第三方服务

| 服务 | 来源 | 用途 | 使用方式 |
|---|---|---|---|
| **通义千问 qwen-plus** | 阿里云 DashScope（OpenAI 兼容接口） | **仅用于自然语言表达层润色**——把确定性逻辑产出的结论改写得通顺自然 | 通过 OpenAI 兼容 SDK/HTTP 调用；需配置 `AGENT_LLM_API_KEY`。**引用编号 `[n]`、资格门控、赛事路由、推荐排序均由本地确定性逻辑产出，不经模型生成** |
| **DuckDuckGo** | https://duckduckgo.com | 联网补充检索（**默认 provider，免 API Key**） | `src/agent/web_search.py` 发起 GET 查询；结果仅作补充，**不混入 `[n]` 官方引用** |
| **Tavily / Serper** | https://tavily.com · https://serper.dev | 可选联网检索 provider | 配置对应 Key 后切换；未配置则使用 DuckDuckGo |

> **降级设计**：联网补充默认 **4 秒超时 / 单次尝试**，失败立即回退本地可信证据链；无外网、无 LLM Key 时系统仍可完整作答。

## 四、前端

- **原生 HTML / CSS / JavaScript**，无第三方前端框架、无构建步骤。
- **不加载任何外部 CDN 资源**（无第三方字体、图标库或统计脚本），全部资源由本项目静态目录提供，可完全离线运行。

## 五、部署与运行平台

| 平台 | 用途 | 说明 |
|---|---|---|
| **Docker / Docker Compose** | 容器化部署 | 见 `compose.yaml`、`Dockerfile` |
| **GitHub Actions** | 定时触发官方来源雷达扫描 | `.github/workflows/source-radar.yml`，每 6 小时调用 `/api/admin/radar/run` |

## 六、数据来源（非第三方数据集）

- 全部赛事数据来自**各赛事组委会官方网站公开发布的通知、章程与 PDF/DOCX 文件**，由团队人工整理为 Ground Truth 样本（190 条）。
- 每条记录保留：官方来源链接、获取日期、最近核验日期、文档指纹与版本状态，**可逐条追溯**。
- **不使用任何未授权的真实个人敏感信息**；用户画像仅收集推荐所必需的专业、年级、技能与经历，支持一键删除（含级联删除项目与任务）。详见 `docs/COMPLIANCE.md`。

---

## 合规声明

1. 上述开源组件均按其开源许可证使用，仅作为库依赖调用，**未修改其源代码**。
2. 公开模型（qwen-plus）通过其官方 API 调用，按量计费，未进行模型权重的再分发。
3. 联网检索结果仅作补充参考，**不写入可信事实库**，也不作为官方引用 `[n]` 的来源。
4. 作品核心逻辑（赛事路由、资格门控、组合优化、雷达差异检测、七阶段模板、决策运行剧场）均为**本项目原创实现**。
