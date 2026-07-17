"""可选 LLM 接口（OpenAI 兼容）。

设计目标
--------
- **零依赖默认可用**：未配置 API Key 时，`polish()` / `complete()` 一律返回 None，
  调用方原样回退到确定性模板，不影响任何现有行为。
- **不绑定 langchain**：直接用官方 `openai` SDK（仅当已安装才 import），天然兼容
  OpenAI / DeepSeek / 通义千问 / 智谱 / 本地 vLLM / 任何 OpenAI 兼容端点
  （设置 `AGENT_LLM_BASE_URL` 即可）。
- **引用安全（最重要）**：prompt 强约束「不得改写 [n] 引用编号、门控结论、任何数字」；
  润色后做引用标记校验，若 [n] 集合被破坏（丢失/新增），**自动回退原稿**，
  保证「答案里的引用始终来自官方标注、门控结论始终来自本地可信数据」。
- **配置（环境变量）**：
    AGENT_LLM_API_KEY      必填（有它才启用；也可同时设 AGENT_LLM=1 显式开）
    AGENT_LLM_BASE_URL     可选，如 https://api.deepseek.com/v1
    AGENT_LLM_MODEL        可选，默认 gpt-4o-mini
    AGENT_LLM_TEMPERATURE  可选，默认 0.3
    AGENT_LLM_PROVIDER     可选（仅备注/日志用）
    AGENT_LLM              可选：=0 强制关闭；=1 强制开启（需同时有 API Key）

启用判定：`AGENT_LLM != "0"` 且 `AGENT_LLM_API_KEY` 非空。
"""

from __future__ import annotations

import os
import re
from typing import Optional

# 引用标记 [n]：用于润色后校验，保证编号不被模型改动。
_MARKER_RE = re.compile(r"\[(\d+)\]")


def _citation_markers(text: str) -> set[int]:
    return {int(m) for m in _MARKER_RE.findall(text or "")}


def is_llm_enabled() -> bool:
    """是否启用了 LLM 润色。"""
    if os.getenv("AGENT_LLM") == "0":
        return False
    return bool(os.getenv("AGENT_LLM_API_KEY"))


def _get_client():
    """惰性构造 OpenAI 客户端；未装 openai 或缺少 key 时返回 None。"""
    key = os.getenv("AGENT_LLM_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI  # 仅当已安装才 import
    except Exception:
        return None
    base_url = os.getenv("AGENT_LLM_BASE_URL") or None
    return OpenAI(api_key=key, base_url=base_url)


def _chat(system: str, user: str) -> Optional[str]:
    """通用 chat 接口：成功返回文本，失败/未配置返回 None。"""
    if not is_llm_enabled():
        return None
    client = _get_client()
    if client is None:
        return None
    model = os.getenv("AGENT_LLM_MODEL", "gpt-4o-mini")
    try:
        temperature = float(os.getenv("AGENT_LLM_TEMPERATURE", "0.3"))
    except (TypeError, ValueError):
        temperature = 0.3
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception:
        # 任何网络/鉴权/限流错误都回退，不让 LLM 失败影响主链路。
        return None


_POLISH_SYSTEM = (
    "你是校园科创导航助手。请在不改变任何事实、数字、门控结论、以及引用编号[n]的"
    "前提下，把下面的草稿润色得更自然流畅、简洁友好。只输出润色后的正文，不要"
    "添加任何额外说明、不要编造新的引用编号。如果草稿里出现 [1]、[2] 等引用标记，"
    "必须原样保留，一个都不能少、也不能多。"
)


def polish(draft: str, context: str) -> Optional[str]:
    """润色确定性草稿（用于答案 / 组队文案）。

    未启用或调用失败 → 返回 None（调用方回退原稿）。
    若润色结果破坏了引用标记 [n] → 返回 None（同样回退原稿，保证引用安全）。
    """
    if not draft or not is_llm_enabled():
        return None
    user = (
        f"【参考事实 / 上下文】\n{context}\n\n"
        f"【待润色草稿】\n{draft}"
    )
    out = _chat(_POLISH_SYSTEM, user)
    if not out:
        return None
    # 引用标记安全校验：仅当原稿含 [n] 时才校验
    orig_markers = _citation_markers(draft)
    if orig_markers and _citation_markers(out) != orig_markers:
        return None
    return out


def complete(system: str, user: str) -> Optional[str]:
    """通用问答接口（供未来自由对话 / 复杂意图使用）。"""
    return _chat(system, user)


if __name__ == "__main__":
    print(f"LLM enabled: {is_llm_enabled()}")
    if is_llm_enabled():
        test = polish(
            "蓝桥杯团队人数要求：1至3人。[1] 报名截止：2026-03-15。",
            "赛事=蓝桥杯",
        )
        print("polish test ->", test)
    else:
        print("未配置 AGENT_LLM_API_KEY，polish 将回退到原稿。")
