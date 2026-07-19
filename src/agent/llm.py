"""可选 LLM 润色层（OpenAI 兼容 /chat/completions，零额外依赖）。

设计目标
--------
- **零额外依赖默认可用**：仅用标准库 + 已安装的 `requests`（不依赖 `openai` SDK）。
  未配置 API Key 时，`polish()` / `complete()` 一律返回 None，调用方原样回退到
  确定性模板，不影响任何现有行为。
- **兼容任意 OpenAI 兼容端点**：OpenAI / DeepSeek / 通义千问 / 智谱 / 本地 vLLM
  等，只要暴露 `/chat/completions` 即可（设置 `AGENT_LLM_BASE_URL`）。
- **引用安全（最重要）**：prompt 强约束「不得改写 [n] 引用编号、门控结论、任何数字」；
  润色后做引用标记校验，若 [n] 集合被破坏（丢失/新增），**自动回退原稿**，
  保证「答案里的引用始终来自官方标注、门控结论始终来自本地可信数据」。
- **配置（环境变量）**：
    AGENT_LLM_API_KEY      必填（有它才启用；也可同时设 AGENT_LLM=1 显式开）
    AGENT_LLM_BASE_URL     可选，如 https://api.deepseek.com/v1 ，默认官方地址
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

try:  # pragma: no cover - requests 为本项目运行依赖，缺失则 LLM 自动关闭
    import requests
except Exception:  # noqa: BLE001
    requests = None  # type: ignore

# 引用标记 [n]：用于润色后校验，保证编号不被模型改动。
_MARKER_RE = re.compile(r"\[(\d+)\]")


def _citation_markers(text: str) -> set[int]:
    return {int(m) for m in _MARKER_RE.findall(text or "")}


def is_llm_enabled() -> bool:
    """是否启用了 LLM 润色（未配 key 或 requests 缺失则自动关闭）。"""
    if os.getenv("AGENT_LLM") == "0":
        return False
    if requests is None:
        return False
    return bool(os.getenv("AGENT_LLM_API_KEY"))


def _post_chat(system: str, user: str, model: Optional[str] = None) -> Optional[str]:
    """调用 OpenAI 兼容 /chat/completions；任何异常都返回 None（优雅降级）。

    ``model`` 为可选请求级覆盖：传入时优先于环境变量 ``AGENT_LLM_MODEL``，
    便于前端在同源 key 的模型间（如 qwen-plus / qwen-max / qwen-turbo）切换。
    """
    if not is_llm_enabled():
        return None
    key = os.getenv("AGENT_LLM_API_KEY") or ""
    base_url = (os.getenv("AGENT_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = model or os.getenv("AGENT_LLM_MODEL", "gpt-4o-mini")
    try:
        temperature = float(os.getenv("AGENT_LLM_TEMPERATURE", "0.3"))
    except (TypeError, ValueError):
        temperature = 0.3

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip() or None
    except Exception:  # 网络/鉴权/限流/超时/解析错误一律回退，绝不阻断主链路
        return None


_POLISH_SYSTEM = (
    "你是校园科创导航助手。请在不改变任何事实、数字、门控结论、以及引用编号[n]的"
    "前提下，把下面的草稿润色得更自然流畅、简洁友好。只输出润色后的正文，不要"
    "添加任何额外说明、不要编造新的引用编号。如果草稿里出现 [1]、[2] 等引用标记，"
    "必须原样保留，一个都不能少、也不能多。"
)


def polish(draft: str, context: str, model: Optional[str] = None) -> Optional[str]:
    """润色确定性草稿（用于答案 / 组队文案）。

    未启用或调用失败 → 返回 None（调用方回退原稿）。
    若润色结果破坏了引用标记 [n] → 返回 None（同样回退原稿，保证引用安全）。
    ``model`` 可选，请求级覆盖默认模型。
    """
    if not draft or not is_llm_enabled():
        return None
    user = (
        f"【参考事实 / 上下文】\n{context}\n\n"
        f"【待润色草稿】\n{draft}"
    )
    out = _post_chat(_POLISH_SYSTEM, user, model=model)
    if not out:
        return None
    # 引用标记安全校验：仅当原稿含 [n] 时才校验
    orig_markers = _citation_markers(draft)
    if orig_markers and _citation_markers(out) != orig_markers:
        return None
    return out


def complete(system: str, user: str, model: Optional[str] = None) -> Optional[str]:
    """通用问答接口（供未来自由对话 / 复杂意图使用）。"""
    return _post_chat(system, user, model=model)


if __name__ == "__main__":
    print(f"LLM enabled: {is_llm_enabled()}")
    if is_llm_enabled():
        test = polish(
            "蓝桥杯团队人数要求：1至3人。[1] 报名截止：2026-03-15。",
            "赛事=蓝桥杯",
        )
        print("polish test ->", test)
    else:
        print("未配置 AGENT_LLM_API_KEY（或 requests 缺失），polish 将回退到原稿。")
