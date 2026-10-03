# 提交入口

作品：校园科创导航智能体。按队伍提供的命题五“自主命题智能体”和六项提交要求整理。赛道名称、评分权重和上传限制以正式通知为准，不自行推定。

## 六项材料
| 要求 | 材料 |
| --- | --- |
| 可运行作品及测试账号 | 源码交付包、submission/01_可运行作品说明.md；普通演示账号 test / test123 |
| 技术文档 | ARCHITECTURE.md、RAG_ARCHITECTURE.md、DEPLOYMENT.md、根目录作品说明 |
| README | 根目录 README.md |
| 至少 10 条用例 | TEST_CASES.md、15 条正式用例及 evals/formal_results.json |
| 3 至 5 分钟视频 | demo/演示视频.mp4，3 分 28 秒，含音轨 |
| 合规说明 | COMPLIANCE.md、THIRD_PARTY_NOTICES.md |

## 本地运行
安装 Python 后，在解压目录执行：

```powershell
.\start.ps1 -Port 8000
# 浏览器打开 http://127.0.0.1:8000/
```

脚本创建虚拟环境、安装依赖并初始化数据库。首次依赖安装需要网络；随后离线核心流程不需要模型密钥。macOS/Linux 使用 start.sh。Docker 是备选部署方式，提供 Dockerfile 不代表容器运行已经实测。

测试账号不能存放真实个人数据。未配置管理令牌时管理接口关闭，不应为评审取消鉴权。

## 复现评测
```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest tests -q
.\venv\Scripts\python.exe evals\run_formal_evaluation.py
```

最新结果见 QUANTITATIVE_EVALUATION.md、QA_FIX_VALIDATION.md 及机器报告。历史压测和挑战报告按记录日期解读。真实画像来源和自动化执行方式见 evals/user_profile_provenance.json。

## 评审关注
选题价值与需求真实性：作品说明中的用户痛点及来源记录，真人试用表如实填写。
数据质量：官方文件清单与指纹、字段证据、候选隔离。
闭环：推荐 → 官方证据 → 加入项目 → 任务材料 → ICS → 问答。
可用性：回归、正式用例、浏览器及独立解压启动验收。
推广：院系试点计划，不将规划描述为已落地。

## 上线限制
交付包不含私人配置、数据库、密钥和旧演示素材。线上发布前须在 Render 控制台轮换已暴露的 PostgreSQL 凭据及聊天中提供的 API 密钥，重新部署并验证鉴权。无控制台访问权限，不能声称线上凭据已轮换或线上已验收。
