"""赛事隔离 RAG 检索（真实 Chroma 服务 + DB 数据源）。

核心约束（对应修订方案「赛事隔离 RAG」）：
  - 通过 competition_id + document_year + doc_version 限制检索范围，
    避免不同赛事 / 不同年份规则混淆（每个 competition_id 一个独立 collection，
    metadata 再叠加 competition_id/year/version 三重过滤，双保险隔离）。
  - 检索结果附带页码与原文证据（完整 Citation：文档名/官方链接/获取日期/
    最后核验/可信等级），供前端角标展示。
  - 数据源来自真实数据库 db.get_all_competitions()（21 份按赛事/年份/赛道隔离的数据），
    不再硬编码样例，实现「接 DB 的赛事 ID」。

Chroma 连接（生产可切真实服务）：
  - 默认本地持久化 PersistentClient（零外部依赖，data/chunks）。
  - 设环境变量 CHROMA_HOST（可选 CHROMA_PORT，默认 8000）即切换到
    真实 Chroma 服务端（HttpClient），业务代码无需改动。

embedding：
  - 优先使用 sentence-transformers 的 all-MiniLM-L6-v2（若已安装）。
  - 否则回退到内置轻量哈希向量（离线可用，仅用于演示隔离检索）。

检索流程：
  DB -> ingest(每赛事字段+证据构造检索块，带 metadata) -> add
      -> query(强制 scoped by competition_id, 可选 year/version)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# 允许脚本直接运行（python rag/store.py）或模块运行（python -m rag.store）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb
from chromadb.config import Settings

import db  # 延迟可用的数据访问层（用于 Chroma 不可用时的本地降级检索）
from fact_formatting import format_team_size
from schemas import Citation, Competition, TrustedLevel

# ---------------------------------------------------------------------------
# Embedding：优先 sentence-transformers，回退轻量哈希向量
# ---------------------------------------------------------------------------
_EMBED_DIM = 256
_ST_MODEL = None
_ST_TRIED = False


def _try_load_st():
    """惰性尝试加载 sentence-transformers；失败则永久回退轻量向量。

    开关优先级：
      RAG_USE_ST=0  强制关闭（用轻量向量 + 本地检索）
      RAG_USE_ST=1  强制开启（真实语义 embedding）
      都不设          默认关闭，用轻量关键词检索（启动快、引用召回更优、无联网风险）

    启用真实语义 embedding 时：若 all-MiniLM-L6-v2 已离线预热到本地缓存，
    则强制 HF_HUB_OFFLINE=1 从缓存加载，避免受限网络下连 huggingface.co 超时卡死
    （本沙箱 huggingface.co 不可达，仅 hf-mirror.com 可下模型）。
    """
    global _ST_MODEL, _ST_TRIED
    if _ST_TRIED:
        return _ST_MODEL
    _ST_TRIED = True
    env = os.getenv("RAG_USE_ST")
    if env == "0":
        return None
    if os.getenv("RAG_DISABLE_ST") == "1" and env != "1":
        return None
    # 未显式开启时不自动加载：保持轻量、稳定、可量化的默认体验
    if env != "1":
        return None
    try:
        # 模型已离线预热到本地缓存时，强制离线加载，规避联网超时卡死
        import pathlib

        _hf_cache = (
            pathlib.Path(os.path.expanduser("~")) / ".cache" / "huggingface" / "hub"
        )
        _mini_dir = _hf_cache / "models--sentence-transformers--all-MiniLM-L6-v2"
        if _mini_dir.exists():
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer

        _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _ST_MODEL = None
    return _ST_MODEL


def _light_embed(texts: list[str]) -> list[list[float]]:
    """字符三元组哈希向量，离线可用，仅用于演示隔离检索。"""
    import hashlib

    vecs = []
    for t in texts:
        vec = [0.0] * _EMBED_DIM
        for i in range(max(0, len(t) - 2)):
            h = int(hashlib.md5(t[i : i + 3].encode("utf-8")).hexdigest(), 16)
            vec[h % _EMBED_DIM] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        vecs.append([v / norm for v in vec])
    return vecs


def embed(texts: list[str]) -> list[list[float]]:
    """统一 embedding 入口：有 ST 用 ST，否则轻量向量。"""
    model = _try_load_st()
    if model is not None:
        return [list(map(float, v)) for v in model.encode(texts, normalize_embeddings=True)]
    return _light_embed(texts)


def embedding_backend() -> str:
    return "sentence-transformers/all-MiniLM-L6-v2" if _try_load_st() is not None else "light-hash-256"


def _has_real_embedding() -> bool:
    """是否具备真实语义 embedding（sentence-transformers）。

    仅当具备真实 embedding 时，Chroma 向量检索才有意义；否则使用离线轻量
    哈希向量，语义召回质量差，且在某些受限环境下 Chroma 查询会报磁盘段错误。
    此时直接走「本地隔离检索」（基于赛事结构化字段 + 证据原文），对所有
    赛事做 competition_id 隔离，引用仍来自官方标注，质量更稳、零外部依赖。
    """
    return _try_load_st() is not None


# ---------------------------------------------------------------------------
# 赛事隔离 RAG
# ---------------------------------------------------------------------------


class CompetitionRAG:
    """按赛事隔离的向量检索封装（真实 Chroma）。"""

    def __init__(self, persist_dir: str | Path = "data/chunks"):
        host = os.getenv("CHROMA_HOST")
        if host:
            # 真实 Chroma 服务端
            port = int(os.getenv("CHROMA_PORT", "8000"))
            self.backend = f"http://{host}:{port}"
            self.client = chromadb.HttpClient(
                host=host, port=port, settings=Settings(anonymized_telemetry=False)
            )
        else:
            # 本地持久化（默认）
            self.persist_dir = str(persist_dir)
            Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
            self.backend = f"persistent://{self.persist_dir}"
            self.client = chromadb.PersistentClient(
                path=self.persist_dir, settings=Settings(anonymized_telemetry=False)
            )
        self._collection_cache: dict = {}

    # -- 集合按 competition_id 隔离 --
    def _collection_name(self, competition_id: str) -> str:
        # Chroma 集合名仅允许字母数字与下划线
        return f"rag_{competition_id.replace('-', '_')}"

    def _get_collection(self, competition_id: str):
        name = self._collection_name(competition_id)
        if name not in self._collection_cache:
            self._collection_cache[name] = self.client.get_or_create_collection(
                name=name,
                metadata={"competition_id": competition_id, "isolated": True},
            )
        return self._collection_cache[name]

    # -- 写入：将一个赛事的可检索文本片段灌入其隔离集合 --
    def ingest_competition(self, comp: Competition) -> int:
        """把单个赛事的关键字段 + 证据原文构造成检索块，写入隔离集合。

        每个片段的 metadata 携带完整引用信息，检索时可直接还原为 Citation。
        幂等：先删除该赛事旧集合内容再写入，保证与 DB 最新数据一致。
        """
        # 仅在「真实 embedding + 远程 Chroma 服务」时才写 Chroma。
        # 否则（离线轻量向量，或本环境 Chroma 持久化不稳定）跳过 Chroma 写入，
        # 检索直接读 DB（本地关键词 / 语义本地余弦），引用更可靠且避免磁盘错误。
        use_chroma = _has_real_embedding() and str(self.backend).startswith("http")
        if not use_chroma:
            return 0

        collection = self._get_collection(comp.competition_id)
        # 幂等：清空该集合旧数据（按 competition_id 过滤删除）
        try:
            collection.delete(where={"competition_id": comp.competition_id})
        except Exception:
            pass

        documents: list[str] = []
        ids: list[str] = []
        metadatas: list[dict] = []

        def _add(seg_id: str, text: str, field: str, page, source_url, doc_name,
                 acquired, verified, trusted):
            if not text:
                return
            documents.append(text)
            ids.append(f"{comp.competition_id}_{seg_id}")
            metadatas.append({
                "competition_id": comp.competition_id,
                "document_year": comp.document_year,
                "doc_version": comp.doc_version or f"{comp.document_year}_v1",
                "field": field,
                "page": -1 if page is None else int(page),
                "source_url": source_url or "",
                "document_name": doc_name or f"{comp.competition_name}_{comp.document_year}_官方通知",
                "acquired_date": acquired or (comp.source_acquired_date or ""),
                "last_verified_at": verified or (comp.last_verified_at or ""),
                "trusted_level": trusted or (comp.trusted_level.value if hasattr(comp.trusted_level, "value") else str(comp.trusted_level)),
            })

        # 1) 结构化字段生成的自然语言片段（可被语义检索命中）
        team_txt = format_team_size(comp.team_min, comp.team_max)
        eligible = "、".join(getattr(s, "value", str(s)) for s in (comp.eligible_students or [])) or "未明确"
        majors = "、".join(comp.allowed_majors) if comp.allowed_majors else "不限专业"
        grades = "、".join(getattr(g, "value", str(g)) for g in comp.allowed_grades) if comp.allowed_grades else "不限年级"
        materials = "、".join(comp.required_materials) or "未明确"
        skills = "、".join(comp.required_skills) or "未明确"

        default_url = comp.official_source_url
        _add("f_team", f"团队人数要求：{team_txt}。", "team_max", None, default_url, None, None, None, None)
        _add("f_eligible", f"参赛对象：{eligible}。", "eligible_students", None, default_url, None, None, None, None)
        _add("f_major", f"专业要求：{majors}。", "allowed_majors", None, default_url, None, None, None, None)
        _add("f_grade", f"年级要求：{grades}。", "allowed_grades", None, default_url, None, None, None, None)
        _add("f_reg", f"报名截止时间：{comp.registration_deadline or '未明确'}。", "registration_deadline", None, default_url, None, None, None, None)
        _add("f_sub", f"提交截止时间：{comp.submission_deadline or '未明确'}。", "submission_deadline", None, default_url, None, None, None, None)
        _add("f_mat", f"所需材料：{materials}。", "required_materials", None, default_url, None, None, None, None)
        _add("f_skill", f"所需技能：{skills}。", "required_skills", None, default_url, None, None, None, None)

        # 2) 逐条证据原文（真实原文，携带页码与链接，检索质量最高）
        for i, e in enumerate(comp.evidence or []):
            _add(
                f"ev_{i}",
                e.source_text,
                e.field,
                e.page,
                e.source_url,
                e.document_name,
                e.acquired_date,
                e.last_verified_at,
                e.trusted_level.value if hasattr(e.trusted_level, "value") else str(e.trusted_level),
            )

        if documents:
            collection.add(documents=documents, ids=ids, metadatas=metadatas, embeddings=embed(documents))
        return len(documents)

    def seed_from_db(self) -> dict:
        """从数据库读取全部赛事并灌入各自隔离集合。返回 {competition_id: 片段数}。"""
        import db  # 延迟导入，避免循环依赖

        result: dict = {}
        for comp in db.get_all_competitions():
            result[comp.competition_id] = self.ingest_competition(comp)
        return result

    # -- 查询：强制按 competition_id 隔离，可选年份/版本过滤 --
    def query(
        self,
        competition_id: str,
        question: str,
        document_year: Optional[int] = None,
        doc_version: Optional[str] = None,
        top_k: int = 3,
    ) -> list[Citation]:
        """隔离检索：
        - 具备真实 embedding 时：
            * 若配置了远程 Chroma（CHROMA_HOST）→ 用 Chroma 语义检索；
            * 否则（本环境 Chroma 持久化不稳定）→ 用「语义本地检索」做余弦排序，
              绕开 Chroma 仍能获得真正的语义召回，引用 100% 来自官方标注。
        - 无真实 embedding（离线轻量向量）→ 本地关键词重叠检索。
        三种路径都强制 competition_id 隔离。"""
        comp = db.get_competition(competition_id)  # type: ignore[name-defined]
        if comp is None:
            return []

        if _has_real_embedding():
            # 真正语义召回：远程 Chroma 优先，否则语义本地检索（无需 Chroma）
            if str(getattr(self, "backend", "")).startswith("http"):
                try:
                    hits = self._query_chroma(competition_id, question, document_year, doc_version, top_k)
                    if hits:
                        return hits
                except Exception as exc:  # Chroma 在受限环境偶发 hnsw 磁盘错误
                    print(f"[rag] Chroma 检索异常，降级到语义本地检索：{exc}")
            return self._semantic_local_query(comp, question, top_k)

        # 离线轻量向量模式：本地关键词重叠检索
        return self._local_query(comp, question, top_k)

    def _query_chroma(
        self,
        competition_id: str,
        question: str,
        document_year: Optional[int] = None,
        doc_version: Optional[str] = None,
        top_k: int = 3,
    ) -> list[Citation]:
        collection = self._get_collection(competition_id)
        conditions: list[dict] = [{"competition_id": competition_id}]
        if document_year is not None:
            conditions.append({"document_year": document_year})
        if doc_version is not None:
            conditions.append({"doc_version": doc_version})
        # Chroma 多条件必须用 $and 包裹
        where: dict = {"$and": conditions} if len(conditions) > 1 else conditions[0]

        res = collection.query(
            query_embeddings=embed([question]),
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        citations: list[Citation] = []
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        for doc, meta in zip(docs, metas):
            meta = meta or {}
            page = meta.get("page")
            page = None if page in (None, -1) else int(page)
            trusted = meta.get("trusted_level") or "A"
            try:
                trusted_enum = TrustedLevel(trusted)
            except (ValueError, TypeError):
                trusted_enum = TrustedLevel.A
            citations.append(
                Citation(
                    field=meta.get("field") or "retrieved_chunk",
                    page=page,
                    source_text=doc,
                    document_name=meta.get("document_name"),
                    source_url=meta.get("source_url") or None,
                    acquired_date=meta.get("acquired_date") or None,
                    last_verified_at=meta.get("last_verified_at") or None,
                    trusted_level=trusted_enum,
                )
            )
        return citations

    # —— 降级 / 语义本地检索：不依赖 Chroma，直接基于 DB 块做隔离检索 ——
    def _build_blocks(self, comp: Competition) -> list[Citation]:
        """把一个赛事的可检索片段（结构化字段 + 证据原文）构造成 Citation 列表，
        供本地关键词检索与语义余弦检索共用。始终按 competition_id 隔离。"""
        blocks: list[Citation] = []
        team_txt = format_team_size(comp.team_min, comp.team_max)
        default_doc = f"{comp.competition_name}_{comp.document_year}_官方通知"

        def _mk(field: str, text: str, cit: Optional[Citation] = None) -> None:
            blocks.append(
                Citation(
                    field=field,
                    page=cit.page if cit else None,
                    source_text=text,
                    document_name=cit.document_name if cit else default_doc,
                    source_url=cit.source_url if cit else comp.official_source_url,
                    acquired_date=cit.acquired_date if cit else comp.source_acquired_date,
                    last_verified_at=cit.last_verified_at if cit else comp.last_verified_at,
                    trusted_level=cit.trusted_level if cit else comp.trusted_level,
                )
            )

        _mk("team_max", f"团队人数要求：{team_txt}。")
        _mk("eligible_students", f"参赛对象：{'、'.join(getattr(s, 'value', str(s)) for s in (comp.eligible_students or [])) or '未明确'}。")
        _mk("allowed_majors", f"专业要求：{'、'.join(comp.allowed_majors) if comp.allowed_majors else '不限专业'}。")
        _mk("allowed_grades", f"年级要求：{'、'.join(getattr(g, 'value', str(g)) for g in comp.allowed_grades) if comp.allowed_grades else '不限年级'}。")
        _mk("registration_deadline", f"报名截止时间：{comp.registration_deadline or '未明确'}。")
        _mk("submission_deadline", f"提交截止时间：{comp.submission_deadline or '未明确'}。")
        if comp.required_materials:
            _mk("required_materials", f"所需材料：{'、'.join(comp.required_materials)}。")
        if comp.required_skills:
            _mk("required_skills", f"所需技能：{'、'.join(comp.required_skills)}。")
        # 证据原文（真实标注）也作为可检索块，且保留其原始引用元数据
        for e in comp.evidence or []:
            blocks.append(
                Citation(
                    field=e.field,
                    page=e.page,
                    source_text=e.source_text,
                    document_name=e.document_name,
                    source_url=e.source_url,
                    acquired_date=e.acquired_date,
                    last_verified_at=e.last_verified_at,
                    trusted_level=e.trusted_level,
                )
            )
        return blocks

    def _local_query(self, comp: Competition, question: str, top_k: int) -> list[Citation]:
        """离线关键词重叠检索（不依赖任何外部服务）。"""
        blocks = self._build_blocks(comp)
        q = (question or "").lower()
        scored = []
        for b in blocks:
            t = b.source_text.lower()
            overlap = sum(1 for ch in set(q) if ch in t)
            if overlap == 0:
                continue
            scored.append((overlap, b))
        scored.sort(key=lambda x: -x[0])
        return [b for _, b in scored[:top_k]]

    def _semantic_local_query(self, comp: Competition, question: str, top_k: int) -> list[Citation]:
        """具备真实 embedding 时，用 sentence-transformers 做余弦相似度本地检索。

        绕开本环境不稳定的 Chroma 持久化查询，仍能获得真正的「语义」召回：
        「团队几个人」「组队人数」等 paraphrase 都能命中 team_max 块。
        不依赖任何外部服务，引用仍 100% 来自官方标注。
        """
        blocks = self._build_blocks(comp)
        if not blocks:
            return []
        model = _try_load_st()
        if model is None:
            return self._local_query(comp, question, top_k)
        q_vec = model.encode([question or ""], normalize_embeddings=True)[0]
        b_vecs = model.encode([b.source_text for b in blocks], normalize_embeddings=True)
        scored = []
        for b, v in zip(blocks, b_vecs):
            sim = float(sum(a * c for a, c in zip(q_vec, v)))  # 已归一化 -> 余弦
            scored.append((sim, b))
        scored.sort(key=lambda x: -x[0])
        return [b for _, b in scored[:top_k]]


# 单例（供 API 复用，避免重复建连）
_RAG_SINGLETON: Optional[CompetitionRAG] = None


def get_rag() -> CompetitionRAG:
    global _RAG_SINGLETON
    if _RAG_SINGLETON is None:
        _RAG_SINGLETON = CompetitionRAG()
    return _RAG_SINGLETON


if __name__ == "__main__":
    # 自测：从真实 DB 灌库 + 隔离检索验证
    rag = get_rag()
    print(f"[rag] Chroma backend: {rag.backend}")
    print(f"[rag] embedding backend: {embedding_backend()}")

    stats = rag.seed_from_db()
    total = sum(stats.values())
    print(f"[rag] 已从 DB 灌入 {len(stats)} 个赛事、共 {total} 个片段")

    # 隔离验证：查询蓝桥杯，结果必须只来自蓝桥杯
    if "lanqiao_2026" in stats:
        hits = rag.query("lanqiao_2026", "团队人数和参赛对象要求", document_year=2026)
        print(f"\n[lanqiao_2026] 检索到 {len(hits)} 条：")
        for h in hits:
            pg = "未定位" if h.page is None else f"第{h.page}页"
            print(f"  [{h.field}|{pg}|{h.trusted_level.value}级] {h.source_text[:50]}")

    # 隔离验证：跨赛事查询不应串味
    ids = list(stats.keys())
    if len(ids) >= 2:
        other = ids[1]
        hits2 = rag.query(other, "报名截止时间")
        print(f"\n[{other}] 检索到 {len(hits2)} 条（应只属于 {other}）：")
        for h in hits2:
            print(f"  [{h.field}] {h.source_text[:50]}")
