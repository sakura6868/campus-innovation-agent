"""准备「真实语义 embedding」依赖（sentence-transformers + all-MiniLM-L6-v2）。

用途：当前默认用离线轻量哈希向量 + 本地关键词/语义检索，已能带引用，但语义
召回有限（如 paraphrase「组队几人 / 团队几个人」可能漏召）。装好真实 embedding 后，
rag.store 会自动用 cosine 语义本地检索（绕开本环境不稳定的 Chroma 持久化），
让 qa / team 类问题召回更稳、更准。

运行（项目根目录，需联网）：
  ./venv/Scripts/python.exe setup_embedding.py

装完后启用（二选一）：
  A. 临时：启动服务前设环境变量  RAG_USE_ST=1
  B. 永久：在 .env 或系统环境变量里加  RAG_USE_ST=1

注意：
  - sentence-transformers 会拉取 torch，体积较大（数百 MB），请耐心等待。
  - 若沙箱 pip 受限（SSL），请在你本机/有网环境运行本脚本，或手动
    `pip install sentence-transformers` 后再跑一次本脚本以下载模型。
  - 本脚本只装依赖 + 预热模型，不会改动任何业务代码（开关已内置）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VENV_PY = Path(__file__).resolve().parent / "venv" / "Scripts" / "python.exe"
MODEL = "all-MiniLM-L6-v2"
PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _run(cmd: list[str]) -> int:
    print(">>> " + " ".join(cmd))
    return subprocess.call(cmd)


def install_st() -> bool:
    print("\n[1/2] 安装 sentence-transformers（含 torch，可能较慢）...")
    if VENV_PY.exists():
        py = str(VENV_PY)
    else:
        py = sys.executable
    rc = _run([py, "-m", "pip", "install", "-i", PIP_INDEX, "sentence-transformers"])
    return rc == 0


def warmup_model() -> bool:
    print(f"\n[2/2] 预热并下载模型 {MODEL} ...")
    code = (
        "from sentence_transformers import SentenceTransformer as M;"
        f"m = M('{MODEL}');"
        "v = m.encode(['测试'], normalize_embeddings=True);"
        "print('model ready, dim=', len(v[0]))"
    )
    if VENV_PY.exists():
        rc = _run([str(VENV_PY), "-c", code])
    else:
        rc = _run([sys.executable, "-c", code])
    return rc == 0


def main() -> None:
    ok_install = install_st()
    if not ok_install:
        print("\n[!] 安装失败：请检查网络/镜像源（沙箱 pip 常因 SSL 受限）。"
              "可手动 `pip install sentence-transformers` 后重新运行本脚本。")
        sys.exit(1)
    ok_model = warmup_model()
    if not ok_model:
        print("\n[!] 模型下载失败：同上，请确认可访问 HuggingFace。")
        sys.exit(1)
    print("\n[✓] 准备完成！启用方式：")
    print("    Windows (PowerShell):  $env:RAG_USE_ST='1'; ./venv/Scripts/python.exe -m uvicorn api:app --port 8011")
    print("    Linux/macOS:           RAG_USE_ST=1 ./venv/Scripts/python.exe -m uvicorn api:app --port 8011")
    print("    或写进 .env:          RAG_USE_ST=1")
    print("\n启用后 rag.store 会自动切换为余弦语义本地检索（无需 Chroma），引用仍来自官方标注。")


if __name__ == "__main__":
    main()
