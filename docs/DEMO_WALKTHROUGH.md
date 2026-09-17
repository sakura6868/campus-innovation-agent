# V1.0 最终端到端演示验收记录

- 验收日期：2026-07-29
- 服务地址：`http://127.0.0.1:8000/`
- 演示账号：`test / test123`
- 数据库：保留 181 条赛事、12 个监控来源与现有用户项目，未使用清库验收

## V1.0 现场演示链验收

| 步骤 | 实际验收结果 |
| --- | --- |
| 登录与主导航 | 登录成功；左侧 01–08 导航完整，包含新增「质量驾驶舱」。 |
| 联网问答 | 问「2026蓝桥杯最新报名通知，帮我联网查」，本次 1.79 秒完成；联网结果与 4 条本地官方证据分区展示。 |
| 决策运行剧场 | 正确展示 6 个结构化节点、4 条去重证据、数据版本、节点耗时和 2 个兜底节点；证据数不再按节点重复累加。 |
| 候选可信边界 | 蓝桥杯已有截止日期官方原文，但整体关键证据未齐；页面明示「候选信息、不构成资格判断或推荐评分」。 |
| 雷达情报控制塔 | 展示 12 个监控来源、健康度、监控规则、人工审核门与情报收件箱；当前无待审核事项时正确显示空状态。 |
| 参赛执行闭环 | 现有项目展示七阶段任务、前置依赖和阻塞数；列表、看板、日历、时间线四种视图可以即时切换。 |
| 质量驾驶舱 | `#/admin` 展示 15/15 正式指标、59/59 回归、86 条金标问答、5 类量化门禁、实时来源状态及人工审核 / SSRF / 签名用户会话三类安全门。 |

## 自动化与静态检查

- Python 编译检查通过。
- `node --check frontend/app.js` 通过。
- 隔离 SQLite 数据库上 59/59 项回归测试通过。
- 15/15 条正式量化用例通过，五类指标均为 100%。

---

# V0.2 历史固定账号验收记录

- 验收日期：2026-07-19
- 固定账号：`mock_user_001`（示例用户）
- 浏览器尺寸：1440 x 960
- 验收服务：`http://127.0.0.1:8011/`
- 浏览器控制台：0 errors，0 warnings

## 主流程

| 步骤 | 实际操作 | 验收结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 使用固定示例账号登录 | 成功进入个性化推荐 | [登录页](../demo/acceptance/walkthrough-00-login.png) |
| 2 | 查看推荐 | 页面只展示通过官网来源、四类证据、时间与资格门控的正式推荐；候选赛事在大厅独立筛选 | [推荐页](../demo/acceptance/walkthrough-01-recommendations.png) |
| 3 | 展开中国软件杯官方依据 | 展示PDF名称、证据字段和页码 | [官方依据](../demo/acceptance/walkthrough-02-official-evidence.png) |
| 4 | 点击“加入我的项目” | 创建项目并自动生成任务计划和材料清单 | [项目创建](../demo/acceptance/walkthrough-03-project-created.png) |
| 5 | 完成首项任务并新增“最终答辩PPT”材料 | 完成进度更新，材料及日期持久化 | [任务与材料](../demo/acceptance/walkthrough-04-tasks-materials.png) |
| 6 | 导出 ICS | 浏览器成功下载 `project-1.ics` | [ICS 文件](../demo/acceptance/project-1.ics) |
| 7 | 询问中国软件杯报名截止日期 | 回答唯一日期 `2026-07-20`，附A级PDF第2页原文 | [Agent回答](../demo/acceptance/walkthrough-05-agent-answer.png) |

完整浏览器操作录像：[submission-walkthrough.webm](../demo/acceptance/submission-walkthrough.webm)

## ICS 核验

- 文件：`demo/acceptance/project-1.ics`
- SHA-256：`d1f3f37abbee7eb0a8b2dba16d6c083fec35e96b671f58409388f8d0f185c994`
- 包含报名截止：`DTSTART;VALUE=DATE:20260720`
- 包含提交截止：`DTSTART;VALUE=DATE:20260720`
- 官方日期事件说明：`来自官网来源与关键证据完整的赛事主表`

## 三个安全场景

| 场景 | 实际结果 | 证据 |
| --- | --- | --- |
| 未核验赛事不评分 | APMCM 显示“候选信息·未评分”，匹配度为 `—`，不提供加入项目按钮 | [未核验拦截](../demo/acceptance/safety-01-unverified-no-score.png) |
| 已截止赛事不推荐 | 服务外包大赛显示“不符合·一票否决”和“报名已经截止”，匹配度为 `—` | [截止门控](../demo/acceptance/safety-02-expired-not-recommended.png) |
| 同名赛事未指定年份 | 存在推荐级版本时明示“最新官网来源已确认版本”；只有候选版本时追问具体年份 | [多年份消歧](../demo/acceptance/safety-03-same-name-latest-verified.png) |

## 验收结论

固定账号已完整走通“推荐 -> 官方证据 -> 项目 -> 任务与材料 -> ICS -> Agent回答”。三个安全场景均按预期工作，Agent回答中的报名截止日期与项目及ICS中的官方日期一致。
