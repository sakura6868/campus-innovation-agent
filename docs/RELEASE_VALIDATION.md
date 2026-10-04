# 本版归档验收

归档由当前源码、官方资料和演示视频生成，凭据模式扫描通过后再输出 ZIP 与 SHA256 清单。`scripts/check_release.py` 对解压源码、隔离数据库和实际 HTTP 运行验证；沿用现有 Python 环境，不宣称重新创建环境或线上生产验收。

具体验收报告作为归档旁的独立附件保存于 `evals/release_validation.json`，包含实际检查与 ZIP 指纹。报告不打入对应ZIP，以避免自引用指纹。当前指标见 [提交快照](SUBMISSION_STATUS.md)。
