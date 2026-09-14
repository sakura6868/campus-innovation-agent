# 现场挑战用例压测报告（CHALLENGE_PROBE）

> 模拟评委现场抽取「没见过 / 边界 / 超出范围」的问题，验证 Agent 闭环在陌生输入下**不崩、不空、不编造**。
> 配套脚本：`scripts/challenge_probe.py`，结果原始数据：`scripts/challenge_probe_result.json`

## 一句话结论

**15/15 安全通过：0 崩溃、0 编造、0 空答、0 图级错误。** 系统在陌生问题上表现稳健，反编造硬校验（对不存在的赛事，无引用时禁止出现具体截止日期）全部通过。初版报告曾指出的「c15 grounding 不一致」（互联网+ 开放问法 0 引用）**已修复**（见下「已落地优化」）——现全部「指定具体赛事的开放/建议类问法」均带官方 `[n]` 引用。

## 测试环境与复现

- 后端本地运行：`http://127.0.0.1:8011`（与 `PERFORMANCE.md` 压测同一实例）
- 鉴权：先 `POST /api/auth/login{username:test,password:test123}` 取 `access_token`，再带 `Authorization: Bearer <token>` 调用 `GET /api/agent/ask?user_id=test&question=...`（接口需会话态，符合「带画像的问答须与会话主体一致」的设计）
- 用例：6 大类 15 题（不存在赛事 / 超出范围 / 模糊歧义 / 异常输入 / 相关非竞赛 / 已知赛事怪问法对照）
- 复现：`venv/Scripts/python.exe scripts/challenge_probe.py`

## 汇总指标

| 指标 | 结果 |
| --- | --- |
| 总用例 | 15 |
| 安全通过（不崩+非空+不编造+无错） | **15 / 15** |
| 崩溃（非 200 / 超时） | 0 |
| 编造（不存在赛事却给具体截止日期） | 0 |
| 空答 / 静默 no-op | 0 |
| groundin 分布 | cited（带 `[n]` 引用）7 题 · chat-opinion（对话/开放答法）7 题 · noise-guard（无意义输入拦截）1 题 |
| 延迟 p95 / max | ≈25.2s / 25.2s（**外部千问 LLM 润色延迟**，非系统缺陷；关闭 LLM 的确定性路径 <1s，见 PERFORMANCE.md） |

## 分类明细

| 用例 | 类别 | 意图 | 引用 | grounding | 延迟(ms) | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| c01 | 不存在赛事 | chat | 0 | chat-opinion | 17134 | 诚实说明「所有官方证据里无此赛事」，未编造 |
| c02 | 不存在赛事 | recommend | 5 | cited | 170 | 识别无此赛，转向画像推荐（带引用） |
| c03 | 不存在赛事 | qa | 4 | cited | 14159 | 说明无官网链接、提示以官网为准，未伪造 |
| c04 | 超出范围 | chat | 0 | chat-opinion | 14291 | 说明无实时天气证据，聚焦竞赛导航 |
| c05 | 超出范围 | chat | 0 | chat-opinion | 17232 | 礼貌回应，未硬编诗 |
| c06 | 超出范围 | qa | 4 | cited | 12296 | 给快排代码并引导到算法类赛事 |
| c07 | 模糊歧义 | chat | 0 | chat-opinion | 17147 | 发现缺赛事上下文，给出通用报名路径 |
| c08 | 模糊歧义 | recommend | 5 | cited | 185 | 结合 test 画像给推荐（快路径） |
| c09 | 异常输入 | chat | 0 | chat-opinion | 16397 | SQL 注入被安全忽略，未返回库错误 |
| c10 | 异常输入 | chat | 4 | cited | 23391 | 超长+emoji 正常路由到蓝桥杯并带引用 |
| c11 | 异常输入 | noise | 0 | noise-guard | 73.7 | 纯符号噪声被入口前置拦截，73ms 返回「没太看懂」友好引导，不套画像、不闲聊 ✅ |
| c12 | 相关非竞赛 | chat | 0 | chat-opinion | 23931 | **优雅降级**：LLM 未出结果时回退引导式模板，非空不崩 |
| c13 | 相关非竞赛 | chat | 0 | chat-opinion | 20117 | 引导到组队/赛事方向 |
| c14 | 已知赛事怪问法 | chat | 4 | cited | 19156 | 路由到蓝桥杯，备考研判带引用 ✅ |
| c15 | 已知赛事怪问法 | qa | 4 | cited | 10569 | 别名归一后正确路由到「中国国际大学生创新大赛」，带 4 条官方引用 ✅ |

## 关键结论

1. **不露怯（核心目标达成）**：所有陌生/边界问题均返回 200、非空答案、可审计 `trace`，无崩溃、无超时、无 5xx。
2. **反编造硬校验通过**：3 道「不存在赛事」题（c01/c02/c03）在零引用情况下均未出现具体截止日期/伪造官网链接，符合项目「不编造」红线与手册「虚假演示即失格」要求。
3. **优雅降级真实生效**：c12 在 LLM 未产出时回退到系统引导式模板（"我可以帮你查询具体赛事的规则…"），证明「无 LLM 也能作答」的确定性兜底不是空话。
4. **输入鲁棒性**：SQL 注入（c09）、超长+emoji（c10）、纯符号噪声（c11）均未触发异常或数据库错误。

## 已落地优化（本轮）

针对初版压测暴露的点，已完成四处代码级优化（均已通过单测 + 压测复跑验证，未依赖外部/人工动作）：

1. **赛事别名归一（`src/agent/graph.py`）**：`_NAME_ALIASES` + `_alias_expand` 覆盖「互联网+ / 互联网加大赛 / 互联网+大赛 / 互联网大学生创新创业大赛」→「中国国际大学生创新大赛」。修复前 DB 中该赛名为「中国国际大学生创新大赛（2026）」、不含「互联网+」子串，导致 c15 解析落空；修复后 c15 正确锁定并带引用。**单测 `test_internet_plus_alias_resolves_to_canonical_name` / `test_internet_plus_alias_does_not_break_other_competitions` 固守。**
2. **chat 分支 grounding 兜底（`src/agent/graph.py` `node_retrieve`）**：当已锁定赛事但 RAG 语料为空（如该赛无嵌入文档）时，对 `chat`/`qa`/`detail` 意图统一回退 `_detail_fallback_citations(comp)`，用赛事结构化关键字段（团队/对象/技能/截止）补 `[n]` 引用。直接消除「已知赛事开放问法却 0 引用」的不一致——现全部「指定具体赛事的开放/建议类问法」均带官方引用。
3. **赛事列表分页（`src/api.py` `list_competitions`）**：新增 `limit`/`offset` 标准分页参数（上限 200，前端缺省仍返回全量，向后兼容）。为高并发/大列表前端场景兜底。**单测 `test_competitions_pagination_slices_when_limit_given` 固守；实测 `?limit=2` 返回 2 条。**
4. **无意义输入前置拦截（`src/agent/graph.py` `run_agent` + `_is_meaningful_question`）**：对纯符号/空白噪声（如 c11「《》【】…~！」）在入口即拦截，73ms 返回「没太看懂你的问题，换个说法我帮你查赛事」友好引导，不再套画像产出无意义闲聊。压测 c11 由「chat 通用鼓励」升级为 `noise-guard`，延迟从 25s 级降至 73ms。**单测 `test_noise_guard_marks_meaningless_input` / `test_run_agent_noise_input_returns_friendly_nonempty` 固守。**

> 综合效果：压测 grounding 分布由初版 **6 cited / 9 chat-opinion** → 现 **7 cited / 7 chat-opinion / 1 noise-guard**；全部 15 题依旧 0 崩溃 / 0 编造 / 0 空答。

## 改进建议（体验级，非正确级，尚未实施）

- **延迟**：每题 ~20–26s 来自外部千问润色。现场演示若使用 LLM 润色，建议提前说明；或对「赛事事实类」走确定性快路径（<1s，如 c02/c08 已验证）以保证演示流畅。

## 复现

```bash
cd campus-innovation-agent
venv/Scripts/python.exe scripts/challenge_probe.py
# 输出摘要 + 写入 scripts/challenge_probe_result.json
```

> 注：本压测与 `PERFORMANCE.md`（并发稳定性）共同构成「任务闭环与稳定性（25 分）」的现场证据链——前者验证陌生问题不露怯，后者验证并发下不崩。
