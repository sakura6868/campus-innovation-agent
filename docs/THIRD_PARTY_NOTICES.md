# 第三方组件与服务说明

## 依赖
运行依赖及版本约束见 requirements.txt，测试依赖见 requirements-dev.txt。FastAPI/Uvicorn 用于 API 服务；Pydantic 校验数据；SQLAlchemy/psycopg2 访问数据库；pdfplumber/python-docx 解析官方通知；requests 用于 HTTP 调用；pytest/httpx2 用于测试。组件来源为各同名上游 GitHub 项目及 PyPI，许可遵循上游声明。

可选 LangGraph、ChromaDB、sentence-transformers 的用途见依赖清单。默认使用内置编排、本地隔离检索及轻量向量，不宣称与外部完整组件效果相同。前端使用本地 HTML/CSS/JavaScript，无 CDN 依赖。

## 模型与搜索
当前本地联调使用第三方 OpenAI 兼容网关 TokenRhythm（https://tokenrhythm.studio/v1），供应商提供的模型标识为 qwen3.8-flash。这不是已验证的阿里云官方直连接口；本项目未独立核实底层模型来源，不分发模型权重。部署方须确认服务条款、隐私及计费规则。

模型用于有证据约束的回答表达及通用建议；关键日期、资格门控、路由和评分由本地规则控制。模型选项由后端配置提供。无密钥时使用本地兜底。模型和搜索各有独立超时，搜索的 4 秒超时不代表完整问答耗时上限。

可选 DuckDuckGo、Tavily、Serper 搜索仅作补充，不直接成为官方证据。离线交付验收关闭外部模型和搜索，不携带密钥。

## 数据与隐私
本版目录包含 196 条赛事，160 条找到官方来源，12 条满足关键字段证据完整规则。其余仅为候选或历史信息，找到链接不等于字段已核实。不伪造缺失证据，最终以官网最新通知为准。

演示账号为虚构数据。真实用户画像的来源确认与自动化评测的执行方式分别记录，不宣称自动化结果是用户本人操作。交付包排除运行数据库及私人配置。外部服务仅接收用户同意分享的必要信息，不发送密码或管理令牌。详见 COMPLIANCE.md。
