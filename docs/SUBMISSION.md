# 提交说明（评委查阅入口）

> **赛道**：中兴赛道 · **命题**：命题五「自主命题智能体」
> **作品**：校园科创导航智能体 `campus-innovation-agent`
> **定位**：面向在校生的**可信赛事导航与参赛执行助手**——把官方来源确认、赛事隔离 RAG、资格门控、个性化推荐、项目任务管理与情报雷达串成端到端闭环。
> 本文件是给评委的**单一入口**：① 六件提交物在哪、怎么核验；② 本地一键跑起来并登录；③ 复现我们的评测证据；④ 100 分评审维度对照。

---

## 一、六件提交物对照（命题五 · 中兴赛道）

| # | 手册要求 | 在仓库中的位置 | 评委核验方式 |
|---|---|---|---|
| 1 | **可运行作品**（含测试账号/演示模式） | 本地见下方「快速开始」 | 登录页点「一键体验」或填 `test / test123` 即可零输入进入 |
| 2 | **技术文档** | `docs/ARCHITECTURE.md`（架构）、`docs/RAG_ARCHITECTURE.md`（检索）、`docs/DEPLOYMENT.md`（运行）、`参赛作品说明.md`（根目录主文档）、`docs/INNOVATION_HIGHLIGHTS.md`（创新点） | 直接阅读 |
| 3 | **README** | `README.md`（环境/依赖/启动/测试/FAQ） | 直接阅读 |
| 4 | **用例集（≥10 条）** | `docs/TEST_CASES.md`（44 条正常/异常/边界/安全用例）、`scripts/challenge_probe.py`（15 条现场挑战用例）、`docs/TRIAL_FORM.md`（真人试用表） | 见第三节复现命令 |
| 5 | **演示视频（3—5 分钟）** | `demo/campus-agent-demo-final.mp4`（**3:28**，1440×900，**无配音、仅烧入中文字幕**）+ 脚本 `docs/DEMO_VIDEO_SCRIPT.md` | 播放；覆盖登录→推荐分化→详情来源→智能顾问引用→大厅→机会提醒→行动路线→我的项目→数据维护→质量驾驶舱 |
| 6 | **合规说明** | `docs/COMPLIANCE.md`（数据来源/隐私/脱敏/权限） | 直接阅读 |

---

## 二、快速开始（本地一键运行）

### 方式 A：Windows 一键（推荐评委验证）

```powershell
# 1) 安装依赖（首次）
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt

# 2) 启动（服务自动建库 + 灌入 190 条赛事样本）
.\start_local.bat
#   或手动：
#   cd src
#   ..\venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8011

# 3) 浏览器打开
#   http://127.0.0.1:8011
```

### 方式 B：Docker

```bash
docker build -t campus-agent .
docker run -p 8011:8011 campus-agent
# 打开 http://127.0.0.1:8011
```

### 登录与体验

- 进入即弹登录页，点「**一键体验**」按钮，或手动填 **`test` / `test123`**，零输入进入演示账号。
- 演示账号预置画像，可直接试用：赛事问答（答案内联 `[n]` 官方引用）、个性化推荐、七阶段项目工作台、情报雷达控制塔、作战地图。
- 无需任何 API Key 即可完整运行：未配置 LLM/联网时自动走确定性兜底（4 秒降级），引用与门控结论不受影响。

---

## 三、复现我们的评测证据（应对「复现抽检 + 统一挑战用例」）

服务启动后，开一个新终端：

```powershell
# 1) 单元测试 + 回归（当前 59 passed + 13 subtests）
.\venv\Scripts\python.exe -m pytest

# 2) 并发稳定性压测（10 并发 × 7 接口 × 30 次，预期 210/210 成功）
.\venv\Scripts\python.exe scripts\benchmark_smoke.py

# 3) 现场挑战用例压测（15 题：不存在赛事/超范围/模糊/异常/相关非竞赛/已知赛事怪问法）
#    验证陌生问题「不崩、不空、不编造」；结果写入 scripts/challenge_probe_result.json
.\venv\Scripts\python.exe scripts/challenge_probe.py
```

> 三项脚本均为仓库自带、可一键复现。测评数据（190 条赛事样本、154 条锚定官方来源）随首次启动自动灌入，干净环境一次跑通。

---

## 四、100 分评审维度对照

| 维度 | 分值 | 本作品抓手 | 佐证文档 |
|---|---|---|---|
| **落地价值** | 30 | 痛点明确（信息真假难辨/决策不可解释/变化难落地）；目标用户清晰；推广路径（学院科创中心、辅导员试点） | `参赛作品说明.md` 第一节「目标用户与核心痛点」+「需求依据：用可复现的真实数据说话」+ 第十一节「推广与试点路径」 |
| **任务闭环与稳定性** | 25 | 端到端「输入—处理—输出—兜底」；决策运行剧场逐节点可审计；联网 4 秒降级；官方来源异常保留最后可信版本 + 人工审核 | `docs/ARCHITECTURE.md`、`docs/CHALLENGE_PROBE.md`、`docs/PERFORMANCE.md` |
| **工程质量** | 20 | 架构清晰、模块合理；README 完整；有日志与错误处理；`pytest.ini` 排除冻结快照 | `README.md`、`docs/ARCHITECTURE.md`、`docs/DEPLOYMENT.md` |
| **交互与体验** | 15 | 答案内联 `[n]` 可点击官方依据；运行剧场逐节点展示；稳妥/均衡/冲刺三路线作战地图；可解释性强 | `README.md`（核心能力）、`docs/INNOVATION_HIGHLIGHTS.md` |
| **安全合规** | 10 | 官方来源锚定、SSRF 防护、最小采集、HMAC 签名会话、画像级联删除、引用真实可追溯 | `docs/COMPLIANCE.md`、`docs/TEST_CASES.md`（安全用例 TC-25~46） |

> 权重信号：**落地价值 30 + 任务闭环 25 = 55 分**占一半以上。本作品叙事主线即「真实痛点 → 端到端闭环 → 兜底可信」。

---

## 五、提交前须知（给队伍）

1. **仓库可见性**：评委若通过链接评审，需将仓库设为 **Public** 或将评委添加为协作者；`.env` 已被 `.gitignore` 排除，仓库不含任何密钥。
2. **演示视频时长**：手册要求 **3—5 分钟**；已重录为 `demo/campus-agent-demo-final.mp4`（**3:28**，1440×900，无配音、仅中文字幕），由 `rec_demo2.py`（playwright 实时录屏 + 自动生成字幕时间轴）与 `burn_subs.py`（ffmpeg `subtitles=` 烧字幕）可复现。
3. **第三方依赖**：已在 `docs/THIRD_PARTY_NOTICES.md` 逐项列明来源/用途/使用方式（FastAPI、SQLAlchemy、qwen-plus、duckduckgo、可选 Chroma/sentence-transformers 等），符合「使用开源/公开模型须说明」要求。

---

## 六、目录速览

```text
campus-innovation-agent/
├─ README.md                  # 环境/依赖/启动/测试/FAQ
├─ 参赛作品说明.md             # 主文档（目标用户/痛点/需求依据/创新/推广）
├─ docs/
│  ├─ SUBMISSION.md           # 本文件（提交索引）
│  ├─ COMPETITION_REQUIREMENTS.md  # 命题五要求逐条对照
│  ├─ ARCHITECTURE.md         # 系统架构
│  ├─ RAG_ARCHITECTURE.md     # 赛事隔离检索
│  ├─ INNOVATION_HIGHLIGHTS.md # 五大核心创新
│  ├─ DEPLOYMENT.md           # 部署
│  ├─ COMPLIANCE.md           # 合规说明（数据/隐私/脱敏）
│  ├─ TEST_CASES.md           # 44 条正式用例集
│  ├─ CHALLENGE_PROBE.md      # 现场挑战压测报告（15/15 安全）
│  ├─ PERFORMANCE.md          # 并发稳定性（210/210）
│  ├─ THIRD_PARTY_NOTICES.md  # 第三方依赖清单
│  ├─ DEMO_VIDEO_SCRIPT.md    # 演示视频脚本
│  └─ TRIAL_FORM.md           # 真人试用记录表
├─ demo/campus-agent-demo-final.mp4 # 演示视频（3:28，无配音、仅字幕）
├─ scripts/                   # benchmark_smoke.py / challenge_probe.py / trial_replay.py
├─ src/                       # 后端（FastAPI + SQLAlchemy + 智能体编排）
├─ frontend/                  # 单页前端（index.html / app.js / styles.css）
├─ tests/                     # 单元 + 回归用例
└─ requirements.txt / Dockerfile
```
