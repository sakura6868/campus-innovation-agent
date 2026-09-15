# Agent 自动化评测闭环

对照全部官方 `data/ground_truth/samples/*.json`，自动验证 Agent 闭环质量。
**零外部依赖**：直接 import 业务代码（`agent.graph.run_agent`），不需要起服务、不需要 LLM key、不需要 Chroma（走本地隔离检索）。

## 运行

```bash
cd campus-innovation-agent
./venv/Scripts/python.exe evals/run_eval.py
```

输出：
- 控制台：逐条用例 OK/XX + 指标汇总
- `evals/report.md`：Markdown 指标报告（含失败用例清单）
- `evals/metrics.json`：机器可读指标

## 用例如何生成

从 ground_truth 读取每个赛事的「名称 / ID」，自动构造六类问句（每个赛事 4 条 + 全局 2 条）：

| 分组 | 问句模板 | 期望意图 | 主要断言 |
| --- | --- | --- | --- |
| detail | 介绍一下{名称} | detail | 意图 + 赛事锁定 |
| qa_team | {名称} 团队几人 | qa | 锁定 + 引用召回 team_min/team_max |
| qa_deadline | {名称} 报名什么时候截止 | qa | 锁定 + 引用召回 registration_deadline |
| team | 帮我写一份{名称}的组队招募文案 | team | 锁定 + 组队文案命中 |
| recommend | 推荐适合我的比赛 | recommend | 推荐非空 |
| unknown | 今天天气怎么样 | unknown | 意图 = unknown |

> 若 ground_truth 目录缺失，自动退化为读取已 seed 的 DB 赛事（仍能拿到名称/ID），保证评测可跑。

## 指标定义

| 指标 | 含义 |
| --- | --- |
| intent_acc | 意图分类准确率（全部用例） |
| resolve_acc | 赛事锁定准确率（resolved_competition == 期望 ID） |
| citation_recall | 引用字段召回：团队类问题是否召回到 `team_min`/`team_max`、截止类是否召回到 `registration_deadline` |
| gate_consistency | 门控一致性：与 `recommendation.engine.eligibility_gate` 重算结果比对（带 user_id 的用例） |
| answer_coverage | 答案非空率 |
| team_hit / recommend_hit | 组队文案含「组队招募」且非空 / 推荐结果非空 |

## 已知预期短板（评测会自然暴露）

当前默认是**离线轻量哈希向量**，RAG 走「本地关键词重叠检索」。因此：
- **介绍 / 详情类问句（"介绍一下X"）中的「介绍」「详情」等词不出现在赛事数据中** → 关键词重叠检索召回为空。

### 已修复（detail 兜底检索）
`src/agent/graph.py` 的 `node_retrieve` 已为 `detail` 意图加兜底：当关键词检索为空时，用该赛事的
**结构化关键字段**（团队/参赛对象/截止/材料/技能）兜底生成引用，保证「介绍一下X」也带官方引用，
不再回退成"未检索到相关条款"。

- 评测的 `detail` 用例改用 `target_any`（是否返回任意引用）度量，**修复前为 0%、修复后应为 ~100%**，
  可直接在 `evals/report.md` 里看到对比。
- 更彻底的改进（让 qa/team 也更稳）仍需接真实 sentence-transformers embedding（或外部 Chroma 服务端），
  评测的价值正是把这类短板量化出来，指导下一步该优先投在哪。

## 进一步：启用真实语义 embedding（推荐下一步）

默认用**离线轻量哈希向量**，语义召回有限（如「组队几人 / 团队几个人」paraphrase 可能漏召）。
装好真实 embedding 后，`rag.store` 会自动切换为**余弦语义本地检索**（绕开本环境不稳定的 Chroma
持久化），让 qa / team 类问题召回更稳更准，且引用仍 100% 来自官方标注。

### 一键准备（项目根目录，需联网）

```bash
./venv/Scripts/python.exe setup_embedding.py
```

脚本会：① 安装 sentence-transformers（含 torch，体积较大）；② 预热并下载 `all-MiniLM-L6-v2`。
装完后再跑一次评测，`citation_recall` / `resolve_acc` 通常会有可见提升。

### 启用开关

| 环境变量 | 行为 |
| --- | --- |
| 不设 | 自动探测：装了 ST 就用语义检索，没装回退离线轻量向量 |
| `RAG_USE_ST=1` | 强制开启真实 embedding（语义本地检索） |
| `RAG_USE_ST=0` | 强制关闭，只用离线轻量向量 + 本地关键词检索 |

启动服务时带上即可：

```bash
# Windows (PowerShell)
$env:RAG_USE_ST='1'; ./venv/Scripts/python.exe -m uvicorn api:app --port 8011
# Linux/macOS
RAG_USE_ST=1 ./venv/Scripts/python.exe -m uvicorn api:app --port 8011
```

> 说明：本环境的 Chroma 持久化查询（`PersistentClient`）会报磁盘段错误，因此语义检索**不走 Chroma**，
> 改为用 sentence-transformers 直接对 DB 片段做 cosine 排序（无外部依赖、引用来自官方标注）。
> 若你有**远程 Chroma 服务**，设 `CHROMA_HOST` 即切回 Chroma 语义检索，业务代码无需改动。

## LLM 润色接口（可选，OpenAI 兼容）

答案/组队文案默认由确定性模板生成（离线可跑）。配置 LLM 后，`compose` 与 `team_copy`
会用模型对草稿做自然语言润色，**只改措辞、不改引用编号 [n] / 门控结论 / 数字**；
润色后自动校验引用标记，被破坏则回退原稿，引用安全。

接口实现：`src/agent/llm.py`（零依赖默认可用，未配置即原样回退）。

### 配置（环境变量）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `AGENT_LLM_API_KEY` | **必填**，有它才启用（也可再加 `AGENT_LLM=1` 显式开） | 空=关闭 |
| `AGENT_LLM_BASE_URL` | OpenAI 兼容端点，可接 DeepSeek / 通义 / 本地 vLLM 等 | OpenAI 官方 |
| `AGENT_LLM_MODEL` | 模型名 | `gpt-4o-mini` |
| `AGENT_LLM_TEMPERATURE` | 温度 | `0.3` |
| `AGENT_LLM` | `=0` 强制关闭；`=1` 强制开启（需同时有 Key） | 自动（有 Key 即开） |

### 启用示例

```bash
# 1) 安装 openai SDK（仅需一次）
./venv/Scripts/python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple openai

# 2) 带配置启动（以 DeepSeek 为例）
$env:AGENT_LLM_API_KEY='sk-xxx'; $env:AGENT_LLM_BASE_URL='https://api.deepseek.com/v1'; $env:AGENT_LLM_MODEL='deepseek-chat'
./venv/Scripts/python.exe -m uvicorn api:app --port 8011

# 3) 自检接口是否就绪（不联网也能跑，只看配置）
./venv/Scripts/python.exe -m agent.llm
```

> 校验：用 `evals/run_eval.py` 跑一遍，开启 LLM 后 `answer_coverage` 仍为 100%、`gate_consistency`
> 不变（润色不改变结论）；引用编号应与关闭时完全一致。
