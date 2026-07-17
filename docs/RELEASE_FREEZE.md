# 版本冻结说明

## 冻结范围

候选版本备份包含：

- `src/` 后端、Agent、RAG和推荐引擎代码
- `frontend/` 前端应用
- `data/` SQLite、向量库、21份 Ground Truth、12份已核验记录及官方PDF/Word和解析结果
- `demo/` 演示视频及端到端验收证据
- `docs/`、`evals/`、`tests/` 和部署配置

不包含本地虚拟环境、临时目录和开发浏览器缓存。所有冻结包均位于 `backups/`，并配有同名 `.sha256` 文件；使用以下命令复核：

```powershell
Get-FileHash -Algorithm SHA256 backups\campus-agent-freeze-*.zip
```

## 冻结策略

1. 首次冻结后运行15条正式指标用例和24项回归测试。
2. 仅允许修复验收发现的阻塞性问题，不继续增加产品功能。
3. 每次阻塞性修复必须由失败用例复现，并在修复后重新执行全部评测。
4. 最终候选包以 `backups/` 中时间最新的冻结包为准。

## 本轮阻塞性修复

正式评测 `FE-12` 首次运行发现：无用户画像时，Agent虽然不会正式推荐未核验赛事，但回答末尾漏掉“待人工确认”提示。修复范围仅限 `src/agent/graph.py` 的门控跳过分支，使其仍传递数据核验状态。

修复后结果：

- 15条正式指标用例：15/15通过
- 现有自动回归测试：23/23通过
- 浏览器端到端流程：通过
- 浏览器控制台：0错误

详细结果见 [量化评测报告](QUANTITATIVE_EVALUATION.md) 和 [端到端演示验收记录](DEMO_WALKTHROUGH.md)。

## 最终候选包

- 文件：以 `backups/` 中时间戳最新的 `campus-agent-freeze-*.zip` 为准
- SHA-256：见同名 `.sha256` 文件
- SQLite完整性：`ok`
- 赛事数量：21（其中12项已核验）
- 固定账号演示项目：1

包外同时提供同名 `.sha256`、`.evaluation.md` 和 `.evaluation.json` 文件，分别用于完整性核验和机器复评。
