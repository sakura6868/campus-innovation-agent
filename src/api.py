"""FastAPI 接口层 —— 接入真实数据库（SQLite / PostgreSQL 可切换）。

运行：
    uvicorn api:app --reload --port 8000

所有响应结构已在 schemas.py 冻结（competition/timeline/requirements/sources/verification）。
数据库由 db.py 管理：首次启动自动建表并 seed 21 份赛事数据；
用户画像写入真正持久化（不再原样回显）。
"""

from __future__ import annotations

import base64
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


def _load_dotenv() -> None:
    """零依赖加载项目根目录 .env（本地开发用）。

    仅在文件存在时读取，且**不覆盖已存在的环境变量**——因此 Render 等平台
    直接注入的变量优先，线上无 .env 时此函数静默跳过，绝不影响生产。
    """
    for base in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent):
        env_path = base / ".env"
        if not env_path.is_file():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:  # noqa: BLE001 - .env 解析失败不应阻断启动
            pass
        break


_load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from rag.store import get_rag, embedding_backend
from recommendation.engine import recommend_for_user
from trust import assess_recommendation_readiness, assess_source_readiness
from schemas import (
    Citation,
    Competition,
    CompetitionCategory,
    DataStatus,
    RecommendationResult,
    ProjectCreate,
    ProjectItem,
    ProjectItemCreate,
    ProjectItemUpdate,
    ProjectUpdate,
    UserProject,
    TrustedLevel,
    UserProfile,
)

import parsing.pdf_extractor as pdf_extractor
from admin import suggest as extract_suggest
from agent.graph import run_agent  # LangGraph 闭环：意图路由→隔离检索→门控→评分→组队文案
from agent.llm import is_llm_enabled  # 可选 LLM 润色开关（无 key 自动关闭）

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时建表 + seed（幂等）
    db.init_db()
    # 从 DB 灌入赛事隔离 RAG（幂等：按 competition_id 覆盖），保证启动即可检索
    try:
        stats = get_rag().seed_from_db()
        print(f"[rag] 启动灌库完成：{len(stats)} 个赛事、{sum(stats.values())} 个片段，backend={embedding_backend()}")
    except Exception as exc:  # RAG 失败不应阻断主服务
        print(f"[rag] 启动灌库失败（不影响主服务）：{exc}")
    yield


app = FastAPI(title="校园科创导航智能体", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["系统"])
def health() -> dict:
    """后端健康检查。"""
    try:
        with db.get_engine().connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        database_status = "connected"
    except Exception:
        database_status = "unavailable"
    return {
        "status": "ok" if database_status == "connected" else "degraded",
        "mock": False,
        "database": database_status,
        "date": date.today().isoformat(),
        "embedding_backend": embedding_backend(),
        "llm_backend": "openai-compatible" if is_llm_enabled() else "disabled",
    }


@app.get("/api/competitions", tags=["赛事"])
def list_competitions(
    category: str | None = Query(None, description="programming/modeling/innovation/software"),
    year: int | None = Query(None, description="文档年份，避免跨年混用"),
    readiness: str = Query("all", pattern="^(all|ready|candidate)$"),
) -> list[dict]:
    """赛事目录；可按类别、年份与是否具备正式推荐资格过滤。"""
    rows: list[dict] = []
    for comp in db.list_competitions(category=category, year=year):
        assessment = assess_recommendation_readiness(comp, date.today())
        if readiness == "ready" and not assessment.ready:
            continue
        if readiness == "candidate" and assessment.ready:
            continue
        payload = comp.model_dump(mode="json")
        payload["recommendation_ready"] = assessment.ready
        payload["readiness_reasons"] = list(assessment.reasons)
        rows.append(payload)
    return rows


@app.get("/api/competitions/{competition_id}", tags=["赛事"])
def competition_detail(competition_id: str) -> dict:
    """赛事详情 —— 统一返回 competition/timeline/requirements/sources/verification。"""
    detail = db.get_competition_detail(competition_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return detail.model_dump(mode="json")


@app.get("/api/users", tags=["用户"])
def list_users() -> list[dict]:
    """可登录用户列表（供登录页展示不同「特色」身份，一键切换体验千人千面）。

    只返回展示所需的轻量字段，不含敏感信息。
    """
    users = db.list_user_profiles()
    return [
        {
            "user_id": u.user_id,
            "display_name": u.display_name or u.user_id,
            "persona": u.persona or "",
            "avatar": u.avatar or "🙂",
            "education_level": u.education_level.value,
            "grade": u.grade.value,
            "major": u.major,
            "skills": u.skills,
            "experiences": u.experiences,
            "weekly_available_hours": u.weekly_available_hours,
            "expected_team_size": u.expected_team_size,
        }
        for u in users
    ]


@app.get("/api/users/{user_id}/profile", response_model=UserProfile, tags=["用户"])
def get_profile(user_id: str) -> UserProfile:
    """获取用户画像（来自数据库）。"""
    profile = db.get_user_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return profile


@app.post("/api/users/{user_id}/profile", response_model=UserProfile, tags=["用户"])
def save_profile(user_id: str, profile: UserProfile) -> UserProfile:
    """保存用户画像；未勾选隐私授权时拒绝保存个性化数据。写入真正持久化。"""
    if user_id != profile.user_id:
        raise HTTPException(status_code=400, detail="路径 user_id 与请求体不一致")
    if not profile.can_store_profile():
        raise HTTPException(
            status_code=403,
            detail="未勾选隐私授权，仅可浏览公开赛事，不能保存个性化画像",
        )
    return db.save_user_profile(profile)


@app.delete("/api/users/{user_id}/profile", tags=["用户"])
def delete_profile(user_id: str) -> dict:
    """删除个人画像及其项目数据，不删除任何赛事或官方证据。"""
    result = db.delete_user_profile(user_id)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="用户画像不存在")
    return {"user_id": user_id, **result}


@app.get(
    "/api/users/{user_id}/recommendations",
    response_model=list[RecommendationResult],
    tags=["推荐"],
)
def recommendations(user_id: str) -> list[RecommendationResult]:
    """只返回通过可信门控并完成评分的正式推荐。"""
    profile = db.get_user_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    comps = db.get_all_competitions()
    return [
        item
        for item in recommend_for_user(profile, comps, date.today())
        if item.eligible and item.score is not None
    ]


# ---------------------------------------------------------------------------
# 我的项目：任务计划、材料清单、完成状态、ICS
# ---------------------------------------------------------------------------
@app.get("/api/users/{user_id}/projects", response_model=list[UserProject], tags=["我的项目"])
def list_projects(user_id: str) -> list[UserProject]:
    if db.get_user_profile(user_id) is None:
        raise HTTPException(status_code=404, detail="用户画像不存在")
    return db.list_user_projects(user_id)


@app.post("/api/users/{user_id}/projects", response_model=UserProject, tags=["我的项目"])
def join_project(user_id: str, payload: ProjectCreate) -> UserProject:
    try:
        return db.create_user_project(user_id, payload.competition_id)
    except ValueError as exc:
        errors = {
            "profile_required": (404, "请先保存个人画像"),
            "competition_not_found": (404, "赛事不存在"),
            "competition_unverified": (409, "未核验赛事不能加入正式项目"),
            "competition_expired": (409, "赛事报名已经截止，不能新建参赛项目"),
        }
        status, message = errors.get(str(exc), (400, "无法加入项目"))
        raise HTTPException(status_code=status, detail=message)


@app.patch("/api/users/{user_id}/projects/{project_id}", response_model=UserProject, tags=["我的项目"])
def update_project(user_id: str, project_id: int, payload: ProjectUpdate) -> UserProject:
    project = db.update_user_project(user_id, project_id, payload.status)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@app.delete("/api/users/{user_id}/projects/{project_id}", tags=["我的项目"])
def delete_project(user_id: str, project_id: int) -> dict:
    if not db.delete_user_project(user_id, project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": True, "project_id": project_id}


@app.post(
    "/api/users/{user_id}/projects/{project_id}/items",
    response_model=ProjectItem,
    tags=["我的项目"],
)
def add_project_item(user_id: str, project_id: int, payload: ProjectItemCreate) -> ProjectItem:
    item = db.add_project_item(user_id, project_id, payload.item_type, payload.title, payload.due_date)
    if item is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return item


@app.patch(
    "/api/users/{user_id}/projects/{project_id}/items/{item_id}",
    response_model=ProjectItem,
    tags=["我的项目"],
)
def update_project_item(
    user_id: str, project_id: int, item_id: int, payload: ProjectItemUpdate
) -> ProjectItem:
    item = db.update_project_item(
        user_id, project_id, item_id,
        title=payload.title, due_date=payload.due_date, status=payload.status,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="任务或材料不存在")
    return item


@app.delete("/api/users/{user_id}/projects/{project_id}/items/{item_id}", tags=["我的项目"])
def delete_project_item(user_id: str, project_id: int, item_id: int) -> dict:
    if not db.delete_project_item(user_id, project_id, item_id):
        raise HTTPException(status_code=404, detail="任务或材料不存在")
    return {"deleted": True, "item_id": item_id}


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@app.get("/api/users/{user_id}/projects/{project_id}/calendar.ics", tags=["我的项目"])
def export_project_calendar(user_id: str, project_id: int) -> Response:
    project = db.get_user_project(user_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    events: list[tuple[str, date, str]] = []
    if project.registration_deadline:
        events.append(("赛事报名截止", project.registration_deadline, "来自已核验赛事主表"))
    if project.submission_deadline:
        events.append(("作品提交截止", project.submission_deadline, "来自已核验赛事主表"))
    for item in project.items:
        if item.due_date:
            events.append((item.title, item.due_date, "项目任务" if item.item_type.value == "task" else "材料准备"))

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Campus Innovation Agent//CN", "CALSCALE:GREGORIAN"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for index, (title, event_date, description) in enumerate(events):
        start = event_date.strftime("%Y%m%d")
        end = (event_date + timedelta(days=1)).strftime("%Y%m%d")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:project-{project_id}-{index}@campus-agent",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start}",
            f"DTEND;VALUE=DATE:{end}",
            f"SUMMARY:{_ics_escape(project.competition_name + ' · ' + title)}",
            f"DESCRIPTION:{_ics_escape(description)}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    content = "\r\n".join(lines) + "\r\n"
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="project-{project_id}.ics"'},
    )


# ---------------------------------------------------------------------------
# 赛事隔离 RAG 检索
# ---------------------------------------------------------------------------
@app.get("/api/rag/search", response_model=list[Citation], tags=["RAG"])
def rag_search(
    competition_id: str = Query(..., description="必填：限定检索的赛事，强制隔离"),
    q: str = Query(..., description="自然语言问题，如「团队人数要求」"),
    year: int | None = Query(None, description="可选：文档年份过滤，避免跨年混用"),
    doc_version: str | None = Query(None, description="可选：文档版本过滤"),
    top_k: int = Query(3, ge=1, le=10, description="返回条数"),
) -> list[Citation]:
    """在指定赛事范围内做隔离检索，返回带页码/原文/官方链接的引用证据。

    检索范围被 competition_id 强制隔离（独立集合 + metadata 三重过滤），
    不会串入其他赛事或其他年份的规则。
    """
    if db.get_competition(competition_id) is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return get_rag().query(competition_id, q, document_year=year, doc_version=doc_version, top_k=top_k)


@app.post("/api/rag/reseed", tags=["RAG"])
def rag_reseed() -> dict:
    """从数据库重新灌库（幂等，按 competition_id 覆盖）。人工修订标注后可调用。"""
    stats = get_rag().seed_from_db()
    return {
        "competitions": len(stats),
        "chunks": sum(stats.values()),
        "embedding_backend": embedding_backend(),
        "detail": stats,
    }


@app.post("/api/competitions/{competition_id}/ingest", tags=["RAG"])
def rag_ingest_one(competition_id: str) -> dict:
    """把单个赛事重新灌入其隔离集合（人工修订某赛事后局部刷新）。"""
    comp = db.get_competition(competition_id)
    if comp is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    n = get_rag().ingest_competition(comp)
    return {"competition_id": competition_id, "chunks": n}


# ---------------------------------------------------------------------------
# LangGraph Agent 闭环（意图路由 → 隔离检索 → 门控 → 评分 → 组队文案）
# ---------------------------------------------------------------------------
@app.get("/api/agent/ask", tags=["Agent"])
def agent_ask(
    question: str = Query(..., description="用户自然语言问题"),
    user_id: str | None = Query(None, description="用户ID，用于画像驱动的推荐/门控/文案"),
    competition_id: str | None = Query(None, description="可选：前端直接指定目标赛事，否则由路由自动锁定"),
    top_k: int = Query(4, ge=1, le=10, description="隔离检索返回条数"),
    model: str | None = Query(None, description="可选：请求级覆盖默认 LLM 模型（如 qwen-plus/qwen-max/qwen-turbo），仅同源 key 可用"),
) -> dict:
    """走完整 Agent 闭环，返回意图、答案、引用证据、门控/评分/推荐结果、执行轨迹。

    问答自动带引用：答案文本内嵌 [1][2]… 角标，citations 提供可点击来源。
    """
    try:
        return run_agent(question, user_id=user_id, competition_id=competition_id, top_k=top_k, model=model)
    except Exception as exc:  # 闭环异常不应崩服务
        raise HTTPException(status_code=500, detail=f"Agent 执行异常：{exc}")


# ---------------------------------------------------------------------------
# 数据维护闭环（上传 → 解析 → 来源确认 → 入库）
# ---------------------------------------------------------------------------
_ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "").strip()
_ADMIN_API_KEY = APIKeyHeader(name="X-Admin-Token", auto_error=False)


def _require_admin_token(token: str | None = Depends(_ADMIN_API_KEY)) -> None:
    if not _ADMIN_API_TOKEN:
        raise HTTPException(status_code=503, detail="数据维护接口未启用")
    if not token or not secrets.compare_digest(token, _ADMIN_API_TOKEN):
        raise HTTPException(status_code=401, detail="管理员令牌无效")


def _classify_submitted_competition(comp: Competition) -> tuple[Competition, list[str]]:
    """Normalize evidence metadata, then derive trust status from the shared rules."""
    checked_at = date.today().isoformat()
    comp.official_source_status = "found" if comp.official_source_url else "not_found"
    comp.last_verified_at = checked_at
    for item in comp.evidence:
        item.source_url = item.source_url or comp.official_source_url
        item.acquired_date = item.acquired_date or comp.source_acquired_date or checked_at
        item.last_verified_at = item.last_verified_at or checked_at

    # Assess the strongest possible state; incomplete evidence is immediately downgraded.
    comp.data_status = DataStatus.VERIFIED
    comp.trusted_level = TrustedLevel.A
    assessment = assess_source_readiness(comp)
    if not assessment.ready:
        comp.data_status = DataStatus.UNVERIFIED
        comp.trusted_level = TrustedLevel.B if comp.official_source_status == "found" else TrustedLevel.C
    return comp, list(assessment.reasons)


class AdminUploadPayload(BaseModel):
    filename: str
    content_base64: str


@app.post("/api/admin/upload", tags=["数据维护"])
def admin_upload(payload: AdminUploadPayload, _: None = Depends(_require_admin_token)) -> dict:
    """上传官方通知 PDF/Word（前端 base64 上传，避免依赖 python-multipart），落盘到 data/uploads。"""
    ext = Path(payload.filename or "file.bin").suffix.lower()
    if ext not in (".pdf", ".docx", ".doc"):
        raise HTTPException(status_code=400, detail="仅支持 PDF / Word(.docx) 文件")
    try:
        raw = base64.b64decode(payload.content_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="文件内容 base64 解码失败")
    if not raw:
        raise HTTPException(status_code=400, detail="文件内容为空")
    file_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    save_path = UPLOAD_DIR / (file_id + ext)
    save_path.write_bytes(raw)
    return {"file_id": file_id, "filename": payload.filename, "ext": ext, "saved_as": save_path.name}


@app.post("/api/admin/parse", tags=["数据维护"])
def admin_parse(payload: dict, _: None = Depends(_require_admin_token)) -> dict:
    """解析已上传文件，返回带页码文本块 + 字段抽取建议（含证据块 index）。"""
    file_id = payload.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="缺少 file_id，请先上传")
    candidates = sorted(UPLOAD_DIR.glob(f"{file_id}.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="上传文件不存在，请重新上传")
    path = candidates[0]
    try:
        cat_enum = CompetitionCategory(payload.get("category", "programming"))
    except ValueError:
        cat_enum = CompetitionCategory.PROGRAMMING
    document_year = int(payload.get("document_year", 2026) or 2026)
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            result = pdf_extractor.parse_pdf(path, cat_enum, document_year, competition_id=file_id)
        else:
            result = pdf_extractor.parse_docx(path, cat_enum, document_year, competition_id=file_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"解析失败：{exc}")
    blocks = [
        {"index": i, "page": b.page, "paragraph_index": b.paragraph_index, "text": b.text}
        for i, b in enumerate(result.blocks)
    ]
    suggestions = extract_suggest.suggest_fields(blocks)
    return {
        "document_name": result.document_name,
        "category": cat_enum.value,
        "document_year": document_year,
        "block_count": len(blocks),
        "blocks": blocks,
        "suggestions": suggestions,
    }


@app.post("/api/admin/competitions", tags=["数据维护"])
def admin_confirm_competition(
    comp: Competition, _: None = Depends(_require_admin_token)
) -> dict:
    """关联官方来源后入库；可信等级由统一证据完整性规则自动决定。"""
    comp, readiness_reasons = _classify_submitted_competition(comp)
    db.upsert_competition(comp)
    try:
        n = get_rag().ingest_competition(comp)
    except Exception as exc:
        n = -1
        print(f"[rag] 入库后刷新隔离集合失败（不影响数据）：{exc}")
    return {
        "competition_id": comp.competition_id,
        "data_status": comp.data_status.value,
        "trusted_level": comp.trusted_level.value,
        "evidence_count": len(comp.evidence),
        "recommendation_ready": not readiness_reasons,
        "readiness_reasons": readiness_reasons,
        "rag_chunks": n,
    }


# ---------------------------------------------------------------------------
# 定时自动发现：批量入库（不强制 verified/A）
# ---------------------------------------------------------------------------
class AdminBulkIngestPayload(BaseModel):
    competitions: list[Competition]


@app.post("/api/admin/competitions/bulk", tags=["数据维护"])
def admin_bulk_ingest(
    payload: AdminBulkIngestPayload, _: None = Depends(_require_admin_token)
) -> dict:
    """批量自动入库；每条记录按官方来源证据重新计算可信状态。

    用于定时发现的新赛事：若库中已存在同 ID 且已通过统一来源规则，则跳过，避免自动
    流程覆盖推荐级证据。随后刷新对应赛事的隔离 RAG 集合（失败不影响数据）。
    """
    results: list[dict] = []
    for comp in payload.competitions:
        existing = db.get_competition(comp.competition_id)
        if existing is not None and assess_source_readiness(existing).ready:
            results.append({"competition_id": comp.competition_id, "status": "skipped_verified"})
            continue
        comp, readiness_reasons = _classify_submitted_competition(comp)
        db.upsert_competition(comp)
        try:
            n = get_rag().ingest_competition(comp)
        except Exception as exc:  # RAG 失败不应阻断主服务
            n = -1
            print(f"[rag] 批量入库后刷新隔离集合失败（不影响数据）：{exc}")
        results.append({
            "competition_id": comp.competition_id,
            "status": "upserted",
            "recommendation_ready": not readiness_reasons,
            "readiness_reasons": readiness_reasons,
            "rag_chunks": n,
        })
    return {"count": len(results), "results": results}


# ---------------------------------------------------------------------------
# 前端静态资源（同源部署，避免 CORS）
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", tags=["页面"])
def index() -> FileResponse:
    """前端单页应用入口。"""
    return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
