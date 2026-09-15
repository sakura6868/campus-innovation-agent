# 部署与运行说明

_适用于本地演示、Docker 提交和离线评审环境。_

---

## 🚀 一键启动

Windows PowerShell：

```powershell
.\start.ps1
```

脚本优先使用 Docker；未安装 Docker 时自动使用本地 `venv`。默认访问 `http://127.0.0.1:8000/`。

## 📦 Docker 部署

```powershell
Copy-Item .env.example .env
docker compose up --build
```

停止服务：

```powershell
docker compose down
```

`compose.yaml` 将宿主机 `data/` 挂载到容器 `/app/data`，SQLite、上传文件和解析结果可持续保存。

## 🛠️ 本地部署

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn api:app --app-dir src --host 127.0.0.1 --port 8000
```

## ⚙️ 配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | SQLite | 数据库连接串 |
| `ADMIN_API_TOKEN` | 无 | 必填；未配置时全部 `/api/admin/*` 接口关闭并返回 `503` |
| `RAG_USE_ST` | `自动` | 语义检索开关：`0` 强制关、`1` 强制开、不设则本地有 all-MiniLM-L6-v2 即默认开启真·语义检索（详见 `docs/RAG_ARCHITECTURE.md`） |
| `CHROMA_HOST` | 空 | 远程 Chroma 地址 |
| `CHROMA_PORT` | `8000` | 远程 Chroma 端口 |
| `AGENT_LLM_API_KEY` | 空 | 可选模型润色密钥 |
| `AGENT_LLM_BASE_URL` | 空 | OpenAI 兼容接口地址 |
| `AGENT_LLM_MODEL` | 空 | 模型名称 |

不配置模型时，Agent 使用确定性模板，门控、日期和引用行为不受影响。

## 🧪 验证部署

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

预期健康检查返回 `status=ok`，自动测试全部通过。

健康检查只公开数据库连通状态，不公开连接地址。管理员令牌只保存在本地 `.env`，前端维护页仅在当前浏览器会话中暂存令牌。

`AUTH_TOKEN_SECRET` 必须与 `ADMIN_API_TOKEN` 使用两个独立随机值。前者用于签发用户短期会话，后者仅用于管理写操作。两者不得复用同一值。用户令牌只保存在当前 `sessionStorage`，页面重新进入后强制再次登录。

## 🧯 常见问题

| 现象 | 处理 |
| --- | --- |
| 端口被占用 | `.\start.ps1 -Port 8011` 使用其他端口 |
| 扫描版 PDF 无文本 | 使用可检索官方 PDF，或 OCR 后关联原始页码与来源 |
| Docker 找不到 `.env` | 从 `.env.example` 复制生成 |
| 项目无法加入 | 确认已保存画像、赛事官网来源及四类关键证据完整，且仍可报名 |
| 同名赛事未识别 | 在问题中写明年份，或先补齐该年份的官网关键证据 |
