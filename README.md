# 校园科创导航智能体

`v1.3-competition` · 面向在校学生的赛事选择、可信问答与参赛执行助手。

评委入口：[提交说明](SUBMISSION.md)。数据、测试与视频统一以 [本版提交快照](docs/SUBMISSION_STATUS.md) 为准。目录包含 201 条记录，其中 17 条关键证据完整、11 条在 2026-10-04 01:00 UTC+08:00 仍可报名。不同赛道分别统计，全部目录不能等同于正式推荐。

核心功能：

- 官方网页/PDF/Word 的字段原文、页码、来源日期与指纹可追溯；未知规则保留未知，截止日期不平移。
- 按学生资格、队伍人数、证据与报名状态门控，给出解释型匹配。
- 新增“参赛规划”模式：目标 → 工具选择 → 观察 → 下一步，六个有状态工具完成规划与执行清单；启用模型时最多两次工具选择，失败回退。
- 周时间预算、已有项目工作量与最多参赛数共同约束组合；规划不自动写入画像或报名。用户确认后可采用方案生成项目。
- 项目列表、看板、日历、时间线及材料管理；来源变化经人工审核再更新事实。
- 用户资源所有权校验；生产配置检查与源码包凭据扫描。

## 本地运行

需要 Python 3.10+。Windows：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

或者手动启动：

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\venv\Scripts\python.exe -m uvicorn api:app --app-dir src --host 127.0.0.1 --port 8000
```

打开 [本地页面](http://127.0.0.1:8000)。本地演示账号 `test / test123` 为虚构学生，可一键体验。请在 `.env` 中设置自己的 `AUTH_TOKEN_SECRET`；管理员功能另设独立 `ADMIN_API_TOKEN`。部署配置详见 [.env.example](.env.example) 和 [render.yaml](render.yaml)。Linux/macOS 可使用 `bash start.sh`；Docker 可使用 `docker compose up --build`。

默认不依赖付费模型。`AGENT_LLM=1` 开启模型辅助；API 地址、模型名和私密密钥仅在本机 `.env` 设置，具体变量见示例文件。当前提交验证为离线模式，在线模型规划尚未实测。联网搜索只是参考信息，不替代正式事实。

## 验证与交付

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe evals/run_formal_evaluation.py
.\venv\Scripts\python.exe evals/run_eval.py
.\venv\Scripts\python.exe scripts/security_audit.py --history
.\venv\Scripts\python.exe scripts/refresh_submission.py
.\venv\Scripts\python.exe scripts/create_release_bundle.py --output-dir submission/releases
```

本版回归 168 项及 26 子测试、正式用例 15/15、模板回归 806/806、实际浏览器规划检查 8/8。固定日期评测与当前开放目录统计分别记录；模板回归不是人工金标准，也不是用户效果研究。

- [技术文档](submission/02_技术文档.md) · [架构](docs/ARCHITECTURE.md)
- [实际浏览器演示视频](demo/演示视频.mp4) · [本版旁白稿](docs/DEMO_NARRATION.md)
- [新增官方来源与指纹](data/official_sources/open_2026/manifest.json)
- [定量评测](docs/QUANTITATIVE_EVALUATION.md) · [浏览器检查](evals/planning_browser_results.json)
- [合规说明](docs/COMPLIANCE.md)

生产环境默认关闭演示登录，拒绝弱密钥、共用密钥、调试管理员入口和通配跨域。此前暴露的云数据库及模型服务凭据仍需服务商端撤销并验证旧值失效；本地扫描无法证明已轮换。真实学生试用效果仍待验证。当前材料不宣称线上新版本已部署、提高获奖率或实测节省时间。
