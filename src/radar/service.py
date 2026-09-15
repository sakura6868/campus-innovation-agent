"""动态赛事雷达：安全抓取、规范化、差异检测和待审核事件生成。"""

from __future__ import annotations

import difflib
import hashlib
import ipaddress
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests

import db


MAX_SOURCE_BYTES = 8 * 1024 * 1024
USER_AGENT = "CampusInnovationRadar/1.0 (+official-source-monitor)"
_DROP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header"}
_PUBLIC_DNS_ENDPOINTS = (
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query",
)
_PUBLIC_DNS_CACHE_SECONDS = 300
_public_dns_cache: dict[str, tuple[float, tuple[str, ...]]] = {}


def _is_public_address(raw: str) -> bool:
    """Return whether an IP is globally routable for an untrusted source URL."""
    try:
        return ipaddress.ip_address(raw).is_global
    except ValueError:
        return False


def _resolve_public_dns(host: str) -> set[str]:
    """Resolve a public hostname through a public DNS view when needed.

    Some managed desktop networks transparently map every hostname to an
    internal HTTP proxy.  The normal ``getaddrinfo`` check then sees only a
    private proxy IP and would reject every legitimate public source.  This
    fallback asks a public DNS resolver for the hostname itself; it is used
    only after the local resolver produced no public address.  Private hosts
    and literal private IPs remain blocked before this function is reached.
    """
    now = time.monotonic()
    cached = _public_dns_cache.get(host)
    if cached and now - cached[0] < _PUBLIC_DNS_CACHE_SECONDS:
        return set(cached[1])

    addresses: set[str] = set()
    # Most contest sites publish an A record.  Resolve it first, avoiding
    # twice the latency for every source on slow managed networks; use AAAA
    # only when no public IPv4 record is available.
    for record_type in ("A", "AAAA"):
        for endpoint in _PUBLIC_DNS_ENDPOINTS:
            try:
                response = requests.get(
                    endpoint,
                    params={"name": host, "type": record_type},
                    headers={"Accept": "application/dns-json", "User-Agent": USER_AGENT},
                    timeout=(4, 10),
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                continue
            for item in payload.get("Answer") or []:
                value = str(item.get("data") or "").strip()
                if _is_public_address(value):
                    addresses.add(value)
            if addresses:
                break
        if addresses:
            break

    if addresses:
        _public_dns_cache[host] = (now, tuple(sorted(addresses)))
    return addresses


def validate_public_url(url: str) -> str:
    """拒绝本机、内网和非 HTTP(S) 地址，防止管理接口被用于 SSRF。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("仅允许公开 HTTP/HTTPS 官方来源")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("不允许监控本机或内网地址")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not literal_ip.is_global:
            raise ValueError("来源地址解析到本机或非公开网络")
        return url

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror:
        addresses = set()
    if any(_is_public_address(raw) for raw in addresses):
        return url

    # 受管网络可能把所有请求路由到内网代理。只有公共 DNS 仍能确认该
    # hostname 指向公网时才放行，避免因为代理而放宽对私网目标的限制。
    if _resolve_public_dns(host):
        return url
    if not addresses:
        raise ValueError("来源域名无法解析")
    raise ValueError("来源地址解析到本机或非公开网络")


def _fetch(url: str, etag: str | None = None, last_modified: str | None = None) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/pdf,"
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "text/plain;q=0.9,*/*;q=0.5"
        ),
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    current = validate_public_url(url)
    for _ in range(4):
        response = requests.get(current, headers=headers, timeout=(5, 15), stream=True, allow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            target = response.headers.get("Location")
            if not target:
                raise ValueError("来源重定向缺少目标地址")
            current = validate_public_url(urljoin(current, target))
            continue
        if response.status_code == 304:
            return {
                "status": 304,
                "content": b"",
                "content_type": response.headers.get("Content-Type", ""),
                "etag": response.headers.get("ETag") or etag,
                "last_modified": response.headers.get("Last-Modified") or last_modified,
            }
        response.raise_for_status()
        length = int(response.headers.get("Content-Length") or 0)
        if length > MAX_SOURCE_BYTES:
            raise ValueError("来源文件超过 8MB 安全上限")
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_SOURCE_BYTES:
                raise ValueError("来源响应超过 8MB 安全上限")
            chunks.append(chunk)
        return {
            "status": response.status_code,
            "content": b"".join(chunks),
            "content_type": response.headers.get("Content-Type", ""),
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }
    raise ValueError("来源重定向次数超过安全上限")


def _selector_nodes(root, selector: str | None):
    if not selector:
        return [root]
    selector = selector.strip()
    if selector.startswith("xpath:"):
        return root.xpath(selector[6:].strip()) or []
    if selector.startswith("#"):
        return root.xpath(f"//*[@id={selector[1:]!r}]") or []
    if selector.startswith("."):
        cls = selector[1:]
        return root.xpath(
            f"//*[contains(concat(' ', normalize-space(@class), ' '), ' {cls} ')]"
        ) or []
    if re.fullmatch(r"[A-Za-z][\w-]*", selector):
        return root.xpath(f"//{selector}") or []
    return []


def _normalize_html(
    raw: bytes,
    selector: str | None = None,
    exclude_selector: str | None = None,
) -> str:
    text = raw.decode("utf-8", errors="replace")
    try:
        from lxml import html

        root = html.fromstring(text)
        for element in root.xpath("//script|//style|//noscript|//svg|//nav|//footer|//header"):
            element.drop_tree()
        for rule in (exclude_selector or "").split(","):
            for element in _selector_nodes(root, rule.strip()):
                if element is not root:
                    element.drop_tree()
        nodes = _selector_nodes(root, selector) or [root]
        visible = "\n".join(" ".join(node.itertext()) for node in nodes)
    except Exception:
        visible = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for line in visible.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if clean and clean not in lines[-1:]:
            lines.append(clean)
    return "\n".join(lines)


def _normalize_pdf(raw: bytes) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(BytesIO(raw)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = re.sub(r"\s+", " ", page.extract_text() or "").strip()
            if text:
                pages.append(f"[第{index}页] {text}")
    return "\n".join(pages)


def _looks_like_docx(raw: bytes) -> bool:
    """DOCX 是 ZIP 容器；只在包含 Word 主文档条目时才按 DOCX 解析。"""
    if not raw.startswith(b"PK"):
        return False
    try:
        from zipfile import BadZipFile, ZipFile

        with ZipFile(BytesIO(raw)) as archive:
            return "word/document.xml" in archive.namelist()
    except (BadZipFile, OSError):
        return False


def _normalize_docx(raw: bytes) -> str:
    """提取 Word 段落和表格文本，避免把 DOCX 二进制误当作 HTML。"""
    from docx import Document

    document = Document(BytesIO(raw))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        clean = re.sub(r"\s+", " ", paragraph.text).strip()
        if clean:
            lines.append(clean)
    for table in document.tables:
        for row in table.rows:
            clean = " | ".join(
                re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells
            ).strip(" |")
            if clean:
                lines.append(clean)
    return "\n".join(lines)


def _safe_ignore_pattern(pattern: str | None):
    if not pattern:
        return None
    if len(pattern) > 1000 or re.search(r"(?:\+|\*|\{\d+,?\d*\})\s*\)\s*(?:\+|\*)", pattern):
        raise ValueError("忽略正则过于复杂，可能造成性能风险")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"忽略正则无效：{exc}") from exc


def _apply_ignore_rules(text: str, ignore_regex: str | None) -> str:
    pattern = _safe_ignore_pattern(ignore_regex)
    if pattern is None:
        return text
    return "\n".join(line for line in text.splitlines() if not pattern.search(line[:4000]))


def validate_watch_configuration(
    include_selector: str | None,
    exclude_selector: str | None,
    ignore_regex: str | None,
    trigger_terms: list[str] | None,
) -> None:
    """在保存前验证规则，避免无效或高风险配置进入扫描循环。"""
    _safe_ignore_pattern(ignore_regex)
    for selector in (include_selector, *((exclude_selector or "").split(","))):
        selector = (selector or "").strip()
        if selector and not (
            selector.startswith(("#", ".", "xpath:"))
            or re.fullmatch(r"[A-Za-z][\w-]*", selector)
        ):
            raise ValueError(f"不支持的选择器：{selector}")
    if any(len(str(term)) > 80 for term in (trigger_terms or [])):
        raise ValueError("单个关注词不能超过 80 个字符")


def _normalise(
    content: bytes,
    content_type: str,
    source_type: str,
    selector: str | None,
    exclude_selector: str | None = None,
    ignore_regex: str | None = None,
) -> tuple[str, str]:
    # 一些官方赛事页由前端脚本在浏览器内渲染。服务端直接请求时只能拿到
    # 页面壳和标题，若把它当正文做语义比对会造成“看似正常、实际未监测”的
    # 假象。动态页改为比较原始响应指纹：能发现版本变化，但绝不伪造字段级
    # 事实，后续仍由人工打开官方页确认。
    if source_type == "dynamic":
        return (
            f"[动态页面；仅比较原始响应指纹：{hashlib.sha256(content).hexdigest()}]",
            "dynamic",
        )
    lowered_type = content_type.lower()
    is_pdf = source_type == "pdf" or "application/pdf" in lowered_type or content.startswith(b"%PDF")
    if is_pdf:
        text = _apply_ignore_rules(_normalize_pdf(content), ignore_regex)
        if text:
            return text, "pdf"
        # 部分官方通知是纯扫描件，没有可提取的文字层。不能把它当成抓取
        # 失败：保留文件指纹即可在版本变化时生成“需人工查看 PDF”的低风险
        # 情报，且绝不把 OCR 缺失伪装成字段级变化。
        return f"[图像型 PDF；仅比较文件指纹：{hashlib.sha256(content).hexdigest()}]", "pdf"
    is_docx = (
        source_type == "docx"
        or "wordprocessingml.document" in lowered_type
        or _looks_like_docx(content)
    )
    if is_docx:
        return _apply_ignore_rules(_normalize_docx(content), ignore_regex), "docx"
    if "html" in lowered_type or source_type in {"html", "auto"}:
        normalized = _apply_ignore_rules(
            _normalize_html(content, selector, exclude_selector), ignore_regex
        )
        if normalized:
            return normalized, "html"
        # 部分官网首页完全由脚本渲染，服务端拿到的只有空页面壳。把它
        # 当作抓取失败会导致重复告警；把它伪装为正文又会误提取字段。
        # 因此降级为动态页指纹：可发现响应版本变化，但只产生人工核验线索。
        return (
            f"[脚本渲染页面；仅比较原始响应指纹：{hashlib.sha256(content).hexdigest()}]",
            "dynamic",
        )
    plain = re.sub(r"\s+", " ", content.decode("utf-8", errors="replace")).strip()
    return _apply_ignore_rules(plain, ignore_regex), "text"


_DATE_PATTERN = re.compile(r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?")


def _date_from_line(line: str) -> str | None:
    match = _DATE_PATTERN.search(line)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def _extract_semantic_fields(text: str) -> dict[str, dict]:
    """从快照中确定性抽取少量高价值字段，供字段级前后对照。"""
    result: dict[str, dict] = {}
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        value = _date_from_line(line)
        if value and "报名" in line and any(word in line for word in ("截止", "结束", "至")):
            result["registration_deadline"] = {"value": value, "source_text": line}
        elif value and any(word in line for word in ("提交", "作品", "材料")) and "截止" in line:
            result["submission_deadline"] = {"value": value, "source_text": line}
        if any(word in line for word in ("参赛对象", "参赛资格", "参赛范围")):
            result["eligibility_rule"] = {"value": line[:500], "source_text": line[:500]}
        if any(word in line for word in ("团队人数", "每队", "组队")) and "人" in line:
            result["team_rule"] = {"value": line[:500], "source_text": line[:500]}
        if any(word in line for word in ("提交材料", "作品要求", "报名材料")):
            result["materials_rule"] = {"value": line[:500], "source_text": line[:500]}
    return result


def analyse_change(old_text: str, new_text: str) -> dict:
    old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
    diff_lines = list(
        difflib.unified_diff(old_lines, new_lines, fromfile="上次可信快照", tofile="本次来源快照", lineterm="")
    )
    added = [line[1:].strip() for line in diff_lines if line.startswith("+") and not line.startswith("+++")]
    old_fields = _extract_semantic_fields(old_text)
    new_fields = _extract_semantic_fields(new_text)
    affected: list[str] = []
    proposed: dict = {}
    field_changes: list[dict] = []
    labels = {
        "registration_deadline": "报名截止",
        "submission_deadline": "作品提交截止",
        "eligibility_rule": "参赛资格",
        "team_rule": "组队规则",
        "materials_rule": "材料要求",
    }
    for field in sorted(set(old_fields) | set(new_fields)):
        old = old_fields.get(field, {})
        new = new_fields.get(field, {})
        if old.get("value") == new.get("value"):
            continue
        affected.append(field)
        field_changes.append({
            "field": field,
            "label": labels.get(field, field),
            "old_value": old.get("value"),
            "new_value": new.get("value"),
            "source_text": new.get("source_text"),
        })
        if field in {"registration_deadline", "submission_deadline"} and new.get("value"):
            proposed[field] = new
    affected = list(dict.fromkeys(affected))
    combined = " ".join(added)
    if any(field in {"registration_deadline", "submission_deadline"} for field in affected):
        severity, change_type = "high", "critical_field_changed"
    elif affected:
        severity, change_type = "medium", "rules_changed"
    elif any(word in combined for word in ("参赛资格", "参赛对象", "团队", "附件", "赛道", "报名")):
        severity, change_type = "medium", "rules_changed"
    else:
        severity, change_type = "low", "content_changed"
    summary = (
        f"检测到关键字段变化：{', '.join(affected)}"
        if affected
        else f"检测到来源内容变化，新增或修改 {len(added)} 行"
    )
    return {
        "severity": severity,
        "change_type": change_type,
        "summary": summary,
        "diff_text": "\n".join(diff_lines[:500]),
        "affected_fields": affected,
        "field_changes": field_changes,
        "proposed_changes": proposed,
    }


def run_watch(watch_id: int, demo_content: str | None = None) -> dict:
    watch = db.get_source_watch(watch_id)
    if watch is None:
        raise ValueError("watch_not_found")
    previous = db.latest_source_snapshot(watch_id)
    started = time.perf_counter()
    try:
        if demo_content is None:
            fetched = _fetch(watch["source_url"], watch.get("etag"), watch.get("last_modified"))
        else:
            fetched = {
                "status": 200,
                "content": demo_content.encode("utf-8"),
                "content_type": "text/html; charset=utf-8",
                "etag": None,
                "last_modified": None,
            }
        if fetched["status"] == 304 and previous:
            normalized = previous["normalized_text"]
            kind = watch["source_type"]
            content_hash = previous["content_hash"]
            document_id = previous.get("document_id")
        else:
            normalized, kind = _normalise(
                fetched["content"],
                fetched["content_type"],
                watch["source_type"],
                watch.get("include_selector") or watch.get("css_selector"),
                watch.get("exclude_selector"),
                watch.get("ignore_regex"),
            )
            if not normalized:
                raise ValueError("来源未提取到可比较正文")
            content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            document_id = None
            if kind in {"pdf", "docx"}:
                extension = "pdf" if kind == "pdf" else "docx"
                mime_type = (
                    "application/pdf"
                    if kind == "pdf"
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
                stored = db.store_document(
                    f"radar_watch_{watch_id}_{content_hash[:12]}.{extension}",
                    mime_type,
                    fetched["content"],
                )
                document_id = stored["document_id"]
        snapshot = db.save_source_snapshot(
            watch_id,
            fetched["status"],
            content_hash,
            normalized,
            document_id=document_id,
            response_etag=fetched.get("etag"),
            response_last_modified=fetched.get("last_modified"),
            latency_ms=round((time.perf_counter() - started) * 1000),
            content_bytes=len(fetched.get("content") or b""),
        )
        if previous is None:
            return {"watch_id": watch_id, "status": "baseline_created", **snapshot}
        if previous["content_hash"] == content_hash:
            return {"watch_id": watch_id, "status": "unchanged", **snapshot}
        if kind == "dynamic":
            analysis = {
                "severity": "low",
                "change_type": "dynamic_page_changed",
                "summary": "动态赛事页响应发生变化，需人工打开官方页面核对赛程与规则",
                "diff_text": "\n".join(
                    [
                        "--- 上次动态页面响应",
                        "+++ 本次动态页面响应",
                        f"- {previous['normalized_text']}",
                        f"+ {normalized}",
                    ]
                ),
                "affected_fields": [],
                "field_changes": [],
                "proposed_changes": {},
            }
        elif watch.get("monitor_tier") == "maintenance":
            # 往届、已截止和执行中的赛事仍值得跟踪：官网可能发布获奖、补充
            # 通知或下一赛季公告。但它们不应因页面的日期/文字变化自动改写当前
            # 赛事事实，因此仅产出低优先级、无字段建议的人工核验线索。
            raw_analysis = analyse_change(previous["normalized_text"], normalized)
            analysis = {
                "severity": "low",
                "change_type": "maintenance_source_changed",
                "summary": "资料维护来源发生变化，可能包含新赛季公告、补充通知或结果发布，请人工审核",
                "diff_text": raw_analysis["diff_text"],
                "affected_fields": [],
                "field_changes": [],
                "proposed_changes": {},
            }
        else:
            analysis = analyse_change(previous["normalized_text"], normalized)
        trigger_terms = [str(term).strip().lower() for term in (watch.get("trigger_terms") or []) if str(term).strip()]
        if trigger_terms and kind != "dynamic" and not analysis["affected_fields"]:
            matcher = difflib.SequenceMatcher(
                None, previous["normalized_text"], normalized, autojunk=False
            )
            changed_text = " ".join(
                normalized[b1:b2].lower()
                for tag, _a1, _a2, b1, b2 in matcher.get_opcodes()
                if tag in {"insert", "replace"} and b2 > b1
            )
            if not any(term in changed_text for term in trigger_terms):
                return {
                    "watch_id": watch_id,
                    "status": "noise_filtered",
                    "matched_trigger_terms": [],
                    "reason": "变化未命中关注词，已保存快照但未进入审核队列",
                    **snapshot,
                }
        event = db.create_change_event(
            watch_id,
            previous["snapshot_id"],
            snapshot["snapshot_id"],
            **analysis,
        )
        return {
            "watch_id": watch_id,
            **snapshot,
            **event,
            **analysis,
            "status": "change_detected",
        }
    except Exception as exc:
        db.record_watch_failure(watch_id, str(exc))
        return {"watch_id": watch_id, "status": "error", "error": str(exc)}


def run_all(
    watch_ids: list[int] | None = None,
    demo_content_by_watch: dict | None = None,
    max_workers: int = 4,
) -> dict:
    """Run selected watches concurrently while preserving a stable result order.

    Fetching independent official pages is network-bound.  A small worker pool
    keeps the admin action responsive without creating a burst of requests to
    public competition sites; database snapshots remain short transactions.
    """
    watches = db.list_source_watches(enabled_only=True)
    selected = [w for w in watches if not watch_ids or w["watch_id"] in watch_ids]
    demo = demo_content_by_watch or {}
    if not selected:
        results: list[dict] = []
    else:
        workers = max(1, min(int(max_workers or 1), 4, len(selected)))
        by_watch_id: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="radar-fetch") as executor:
            futures = {
                executor.submit(
                    run_watch,
                    watch["watch_id"],
                    demo.get(str(watch["watch_id"])) or demo.get(watch["watch_id"]),
                ): watch["watch_id"]
                for watch in selected
            }
            for future in as_completed(futures):
                watch_id = futures[future]
                try:
                    by_watch_id[watch_id] = future.result()
                except Exception as exc:  # 守住单个来源异常，不能中断同批扫描。
                    db.record_watch_failure(watch_id, str(exc))
                    by_watch_id[watch_id] = {"watch_id": watch_id, "status": "error", "error": str(exc)}
        results = [by_watch_id[watch["watch_id"]] for watch in selected]
    return {
        "checked": len(results),
        "changed": sum(1 for item in results if item["status"] == "change_detected"),
        "errors": sum(1 for item in results if item["status"] == "error"),
        "results": results,
    }


def run_due(limit: int = 12, max_workers: int = 4) -> dict:
    """Scan only sources whose next scheduled check is due.

    New sources have no ``next_scan_at`` and are therefore prioritised to
    establish their initial baseline.  The bounded batch keeps the background
    worker courteous to public sites and prevents a large import from blocking
    the application process.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def due_key(watch: dict) -> tuple[int, datetime, int]:
        raw = watch.get("next_scan_at")
        if not raw:
            return (0, datetime.min, int(watch["watch_id"]))
        try:
            scheduled = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            scheduled = datetime.min
        return (1, scheduled, int(watch["watch_id"]))

    due = []
    for watch in db.list_source_watches(enabled_only=True):
        raw = watch.get("next_scan_at")
        if not raw:
            due.append(watch)
            continue
        try:
            scheduled = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            due.append(watch)
            continue
        if scheduled <= now:
            due.append(watch)
    selected = sorted(due, key=due_key)[:max(1, min(int(limit or 1), 24))]
    result = run_all(
        watch_ids=[item["watch_id"] for item in selected],
        max_workers=max_workers,
    )
    result["due_total"] = len(due)
    result["deferred"] = max(0, len(due) - len(selected))
    return result
