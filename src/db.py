"""真实数据访问层（替换 mock_data）。

默认使用 SQLite（零外部依赖、易部署）；通过环境变量 DATABASE_URL
切换到 PostgreSQL 等生产数据库（SQLAlchemy 统一接口，无需改业务代码）。

数据来源：data/ground_truth/samples/*.json（官方材料人工核验冷启动集）。
seed 为幂等 upsert，重复运行不会重复插入，也不会丢失人工修正。

提供能力：
  - init_db()            建表 + 首次 seed（赛事 + 演示用户）
  - list_competitions()  列表（按类别/年份过滤）
  - get_competition()    单条 Competition（含 evidence）
  - get_competition_detail()  统一 CompetitionDetail（含 verification）
  - get_user_profile() / save_user_profile()  用户画像读写（真正持久化）
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import (
    DateTime,
    Date,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from schemas import (
    Citation,
    Competition,
    CompetitionCategory,
    CompetitionDetail,
    DataStatus,
    EducationLevel,
    FactTag,
    Grade,
    RequirementItem,
    SourceItem,
    TimelineItem,
    TrustedLevel,
    UserProfile,
    UserProject,
    ProjectItem,
    ProjectItemStatus,
    ProjectItemType,
    ProjectStatus,
    Verification,
)
from fact_formatting import format_team_size

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH_DIR = PROJECT_ROOT / "data" / "ground_truth" / "samples"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "campus_agent.db"

# Render / 部分云厂商注入的 DATABASE_URL 使用 postgres:// 协议头，
# 而 SQLAlchemy 2.0 只认 postgresql://，需在此统一归一化，否则连库失败。
_DATABASE_URL_RAW = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH.as_posix()}")
if _DATABASE_URL_RAW.startswith("postgres://"):
    DATABASE_URL = _DATABASE_URL_RAW.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = _DATABASE_URL_RAW


# ---------------------------------------------------------------------------
# ORM 模型
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class CompetitionModel(Base):
    __tablename__ = "competitions"

    competition_id: Mapped[str] = mapped_column(String, primary_key=True)
    competition_name: Mapped[str] = mapped_column(String, nullable=False)
    document_year: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    organizer: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 资格相关
    eligible_students: Mapped[list] = mapped_column(String, nullable=False, default="[]")  # JSON list[str]
    allowed_grades: Mapped[Optional[list]] = mapped_column(String, nullable=True)  # JSON list[str] | None
    allowed_majors: Mapped[Optional[list]] = mapped_column(String, nullable=True)  # JSON list[str] | None
    team_required: Mapped[bool] = mapped_column(default=False)
    team_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    team_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 时间相关
    registration_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    submission_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # 材料与能力
    required_materials: Mapped[list] = mapped_column(String, nullable=False, default="[]")
    evaluation_dimensions: Mapped[list] = mapped_column(String, nullable=False, default="[]")
    required_skills: Mapped[list] = mapped_column(String, nullable=False, default="[]")

    # 来源与可信
    official_source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_acquired_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trusted_level: Mapped[str] = mapped_column(String, default="C")
    data_status: Mapped[str] = mapped_column(String, default="unverified")
    last_verified_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    doc_version: Mapped[str] = mapped_column(String, default="1.0")

    citations: Mapped[list["CitationModel"]] = relationship(
        back_populates="competition",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CitationModel(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competition_id: Mapped[str] = mapped_column(
        String, ForeignKey("competitions.competition_id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(String, nullable=False, default="")
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_text: Mapped[str] = mapped_column(String, nullable=False, default="")
    document_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    acquired_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_verified_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trusted_level: Mapped[str] = mapped_column(String, default="C")

    competition: Mapped["CompetitionModel"] = relationship(back_populates="citations")


class UserProfileModel(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    education_level: Mapped[str] = mapped_column(String, nullable=False)
    grade: Mapped[str] = mapped_column(String, nullable=False)
    major: Mapped[str] = mapped_column(String, nullable=False)
    skills: Mapped[list] = mapped_column(String, nullable=False, default="[]")
    experiences: Mapped[list] = mapped_column(String, nullable=False, default="[]")
    weekly_available_hours: Mapped[int] = mapped_column(Integer, default=10)
    expected_team_size: Mapped[int] = mapped_column(Integer, default=1)
    privacy_consent: Mapped[bool] = mapped_column(default=False)

    # 登录/展示用（可选）
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    persona: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    avatar: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class UserProjectModel(Base):
    __tablename__ = "user_projects"

    project_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    competition_id: Mapped[str] = mapped_column(
        String, ForeignKey("competitions.competition_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="planned")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    competition: Mapped["CompetitionModel"] = relationship(lazy="joined")
    items: Mapped[list["ProjectItemModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )


class ProjectItemModel(Base):
    __tablename__ = "project_items"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_projects.project_id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String, nullable=False, default="task")
    title: Mapped[str] = mapped_column(String, nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="todo")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped["UserProjectModel"] = relationship(back_populates="items")


# ---------------------------------------------------------------------------
# 引擎与会话
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
        _engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


_initialized = False


def init_db() -> None:
    """建表并首次 seed（幂等，可重复调用）。可在应用启动时或首次 DB 访问时触发。"""
    global _initialized
    if _initialized:
        return
    get_engine()
    Base.metadata.create_all(_engine)
    _migrate_user_profile_columns()
    # 必须在 seed 之前置位，避免 seed -> session_scope -> init_db 递归
    _initialized = True
    seed_all()


def _migrate_user_profile_columns() -> None:
    """幂等增量迁移：为已存在的 user_profiles 表补齐新增展示列。

    SQLAlchemy 的 create_all 不会向已存在的表添加新列，因此这里用
    PRAGMA 检查缺失列并 ALTER TABLE 补齐（仅 SQLite；PostgreSQL 走正常建表）。
    """
    if not DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import text

    wanted = {"display_name", "persona", "avatar"}
    with _engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(user_profiles)")).fetchall()
        existing = {r[1] for r in rows}
        for col in wanted - existing:
            conn.execute(text(f"ALTER TABLE user_profiles ADD COLUMN {col} VARCHAR"))


@contextmanager
def session_scope() -> Iterator[object]:
    if not _initialized:
        init_db()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# JSON 列辅助（SQLite 存文本，PostgreSQL 可改 JSON 类型）
# ---------------------------------------------------------------------------


def _dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_json(text: Optional[str]):
    if text is None or text == "":
        return []
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []


def _to_date(v: Optional[str]) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except (ValueError, TypeError):
        return None


def _to_enum(cls, v, default=None):
    try:
        return cls(v)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# 转换：ORM -> Pydantic
# ---------------------------------------------------------------------------


def _citation_to_pydantic(m: CitationModel) -> Citation:
    return Citation(
        field=m.field,
        page=m.page,
        source_text=m.source_text,
        document_name=m.document_name,
        source_url=m.source_url,
        acquired_date=m.acquired_date,
        last_verified_at=m.last_verified_at,
        trusted_level=_to_enum(TrustedLevel, m.trusted_level, TrustedLevel.C),
    )


def _competition_to_pydantic(m: CompetitionModel) -> Competition:
    allowed_grades = None
    if m.allowed_grades is not None:
        raw = _load_json(m.allowed_grades)
        allowed_grades = [_to_enum(Grade, g, Grade.FRESHMAN) for g in raw]
    allowed_majors = _load_json(m.allowed_majors) if m.allowed_majors is not None else None
    return Competition(
        competition_id=m.competition_id,
        competition_name=m.competition_name,
        document_year=m.document_year,
        category=_to_enum(CompetitionCategory, m.category, CompetitionCategory.PROGRAMMING),
        organizer=m.organizer,
        # 学历属于资格门控字段，未知值必须显式失败，不能静默降级成本科生。
        eligible_students=[EducationLevel(s) for s in _load_json(m.eligible_students)],
        allowed_grades=allowed_grades,
        allowed_majors=allowed_majors,
        team_required=m.team_required,
        team_min=m.team_min,
        team_max=m.team_max,
        registration_deadline=m.registration_deadline,
        submission_deadline=m.submission_deadline,
        required_materials=_load_json(m.required_materials),
        evaluation_dimensions=_load_json(m.evaluation_dimensions),
        required_skills=_load_json(m.required_skills),
        official_source_url=m.official_source_url,
        source_acquired_date=m.source_acquired_date,
        trusted_level=_to_enum(TrustedLevel, m.trusted_level, TrustedLevel.C),
        data_status=_to_enum(DataStatus, m.data_status, DataStatus.UNVERIFIED),
        last_verified_at=m.last_verified_at,
        doc_version=m.doc_version,
        evidence=[_citation_to_pydantic(c) for c in m.citations],
    )


# ---------------------------------------------------------------------------
# Seed（幂等）
# ---------------------------------------------------------------------------

DEMO_USER = UserProfile(
    user_id="mock_user_001",
    education_level=EducationLevel.UNDERGRADUATE,
    grade=Grade.SOPHOMORE,
    major="计算机科学与技术",
    skills=["Python", "前端", "算法"],
    experiences=["蓝桥杯省赛"],
    weekly_available_hours=12,
    expected_team_size=3,
    privacy_consent=True,
    display_name="示例用户",
    persona="综合型 · 计算机大二",
    avatar="🙂",
)

# 特色鲜明的示例用户：登录后画像/推荐/问答结果各不相同，直观体现「千人千面」
DEMO_USERS: list[UserProfile] = [
    DEMO_USER,
    UserProfile(
        user_id="stu_algo",
        education_level=EducationLevel.UNDERGRADUATE,
        grade=Grade.JUNIOR,
        major="计算机科学与技术",
        skills=["C++", "算法", "数据结构", "动态规划", "Python"],
        experiences=["蓝桥杯省一等奖", "ACM-ICPC 区域赛"],
        weekly_available_hours=22,
        expected_team_size=1,
        privacy_consent=True,
        display_name="算法卷王",
        persona="算法竞赛型 · 偏好个人赛，冲省一冲金牌",
        avatar="👨‍💻",
    ),
    UserProfile(
        user_id="stu_model",
        education_level=EducationLevel.UNDERGRADUATE,
        grade=Grade.SOPHOMORE,
        major="信息与计算科学",
        skills=["MATLAB", "数学建模", "论文写作", "Python", "数据分析"],
        experiences=["数学建模校赛二等奖"],
        weekly_available_hours=15,
        expected_team_size=3,
        privacy_consent=True,
        display_name="建模选手",
        persona="数学建模型 · 三人队，重论文与数据",
        avatar="📐",
    ),
    UserProfile(
        user_id="stu_maker",
        education_level=EducationLevel.UNDERGRADUATE,
        grade=Grade.SENIOR,
        major="工商管理",
        skills=["商业计划书", "路演演讲", "项目管理", "市场调研"],
        experiences=["互联网+ 校赛", "大创项目负责人"],
        weekly_available_hours=10,
        expected_team_size=4,
        privacy_consent=True,
        display_name="创业先锋",
        persona="创新创业型 · 组大队，主打商业落地",
        avatar="🚀",
    ),
    UserProfile(
        user_id="stu_dev",
        education_level=EducationLevel.UNDERGRADUATE,
        grade=Grade.JUNIOR,
        major="软件工程",
        skills=["Java", "Spring", "前端", "数据库", "Git"],
        experiences=["中国软件杯"],
        weekly_available_hours=18,
        expected_team_size=3,
        privacy_consent=True,
        display_name="全栈开发",
        persona="软件作品型 · 三人队，做完整产品",
        avatar="🛠️",
    ),
    UserProfile(
        user_id="stu_rookie",
        education_level=EducationLevel.UNDERGRADUATE,
        grade=Grade.FRESHMAN,
        major="电子信息工程",
        skills=["C语言"],
        experiences=[],
        weekly_available_hours=8,
        expected_team_size=1,
        privacy_consent=True,
        display_name="科创萌新",
        persona="入门探索型 · 大一，找门槛低的比赛练手",
        avatar="🌱",
    ),
    UserProfile(
        user_id="stu_grad",
        education_level=EducationLevel.POSTGRADUATE,
        grade=Grade.SENIOR,
        major="人工智能",
        skills=["深度学习", "PyTorch", "论文写作", "Python", "NLP"],
        experiences=["发表 SCI 论文", "研究生数学建模竞赛"],
        weekly_available_hours=20,
        expected_team_size=3,
        privacy_consent=True,
        display_name="AI研究生",
        persona="研究生 · AI方向，偏研究型高含金量赛事",
        avatar="🧠",
    ),
]


def _upsert_competition_from_raw(raw: dict, session) -> None:
    cid = raw.get("competition_id") or Path(raw.get("_source_file", "")).stem
    if not cid:
        return
    cols = {
        "competition_id": cid,
        "competition_name": raw["competition_name"],
        "document_year": int(raw["document_year"]),
        "category": raw["category"],
        "organizer": raw.get("organizer"),
        "eligible_students": _dump_json(raw.get("eligible_students", [])),
        "allowed_grades": None if raw.get("allowed_grades") is None else _dump_json(raw["allowed_grades"]),
        "allowed_majors": None if raw.get("allowed_majors") is None else _dump_json(raw["allowed_majors"]),
        "team_required": bool(raw.get("team_required", False)),
        "team_min": raw.get("team_min"),
        "team_max": raw.get("team_max"),
        "registration_deadline": _to_date(raw.get("registration_deadline")),
        "submission_deadline": _to_date(raw.get("submission_deadline")),
        "required_materials": _dump_json(raw.get("required_materials") or []),
        "evaluation_dimensions": _dump_json(raw.get("evaluation_dimensions") or []),
        "required_skills": _dump_json(raw.get("required_skills") or []),
        "official_source_url": raw.get("official_source_url"),
        "source_acquired_date": raw.get("source_acquired_date"),
        "trusted_level": raw.get("trusted_level") or "C",
        "data_status": raw.get("data_status") or "unverified",
        "last_verified_at": raw.get("last_verified_at"),
        "doc_version": raw.get("doc_version") or f"{raw.get('document_year')}_v1",
    }

    # upsert 主表
    existing = session.get(CompetitionModel, cid)
    if existing is None:
        existing = CompetitionModel(competition_id=cid)
        session.add(existing)
    for k, v in cols.items():
        setattr(existing, k, v)

    # 证据：先删后插，保证与最新 JSON 一致
    for old in list(existing.citations):
        session.delete(old)
    session.flush()
    for e in raw.get("evidence", []):
        session.add(
            CitationModel(
                competition_id=cid,
                field=e.get("field", ""),
                page=e.get("page"),
                source_text=e.get("source_text", ""),
                document_name=e.get("document_name"),
                source_url=e.get("source_url"),
                acquired_date=e.get("acquired_date"),
                last_verified_at=e.get("last_verified_at"),
                trusted_level=e.get("trusted_level") or "C",
            )
        )


def seed_competitions(session) -> int:
    """从 ground_truth/samples 灌库，返回灌入条数。"""
    if not GROUND_TRUTH_DIR.exists():
        return 0
    count = 0
    for f in sorted(GROUND_TRUTH_DIR.glob("*.json")):
        raw = json.loads(f.read_text(encoding="utf-8"))
        raw.setdefault("competition_id", f.stem)
        raw["_source_file"] = str(f)
        _upsert_competition_from_raw(raw, session)
        count += 1
    return count


def seed_demo_user(session) -> None:
    """幂等 seed 多个特色用户；已存在则补齐缺失的展示字段（旧库迁移后回填）。"""
    for u in DEMO_USERS:
        existing = session.get(UserProfileModel, u.user_id)
        if existing is None:
            session.add(
                UserProfileModel(
                    user_id=u.user_id,
                    education_level=u.education_level.value,
                    grade=u.grade.value,
                    major=u.major,
                    skills=_dump_json(u.skills),
                    experiences=_dump_json(u.experiences),
                    weekly_available_hours=u.weekly_available_hours,
                    expected_team_size=u.expected_team_size,
                    privacy_consent=u.privacy_consent,
                    display_name=u.display_name,
                    persona=u.persona,
                    avatar=u.avatar,
                )
            )
        else:
            # 旧库迁移：仅当展示字段为空时回填（不覆盖用户已手动修改的画像）
            if not existing.display_name and u.display_name:
                existing.display_name = u.display_name
            if not existing.persona and u.persona:
                existing.persona = u.persona
            if not existing.avatar and u.avatar:
                existing.avatar = u.avatar


def seed_all() -> int:
    """幂等 seed：赛事 Ground Truth + 演示用户。重复运行安全。"""
    with session_scope() as session:
        n = seed_competitions(session)
        seed_demo_user(session)
    return n


# ---------------------------------------------------------------------------
# 仓储查询
# ---------------------------------------------------------------------------


def list_competitions(
    category: Optional[str] = None, year: Optional[int] = None
) -> list[Competition]:
    with session_scope() as session:
        query = session.query(CompetitionModel)
        if category:
            query = query.filter(CompetitionModel.category == category)
        if year is not None:
            query = query.filter(CompetitionModel.document_year == year)
        rows = query.order_by(CompetitionModel.document_year.desc()).all()
        # 在 session 内完成转换（避免 detached 对象）
        return [_competition_to_pydantic(m) for m in rows]


def get_competition(competition_id: str) -> Optional[Competition]:
    with session_scope() as session:
        m = session.get(CompetitionModel, competition_id)
        if m is None:
            return None
        return _competition_to_pydantic(m)


def get_all_competitions() -> list[Competition]:
    with session_scope() as session:
        rows = session.query(CompetitionModel).all()
        return [_competition_to_pydantic(m) for m in rows]


def get_competition_detail(competition_id: str) -> Optional[CompetitionDetail]:
    comp = get_competition(competition_id)
    if comp is None:
        return None

    timeline = []
    if comp.registration_deadline:
        timeline.append(TimelineItem(label="报名截止", event_date=comp.registration_deadline))
    if comp.submission_deadline:
        timeline.append(TimelineItem(label="提交截止", event_date=comp.submission_deadline))

    requirements = [
        RequirementItem(
            tag=FactTag.OFFICIAL,
            text=f"团队人数：{format_team_size(comp.team_min, comp.team_max)}"
            + ("（个人赛）" if not comp.team_required else "（组队赛）"),
        ),
        RequirementItem(
            tag=FactTag.OFFICIAL,
            text=f"所需材料：{', '.join(comp.required_materials) or '未明确'}",
        ),
    ]

    sources = [
        SourceItem(
            name=f"{comp.competition_name}_{comp.document_year}_官方通知",
            url=comp.official_source_url,
            acquired_date=comp.source_acquired_date,
            trusted_level=comp.trusted_level,
        )
    ]

    verification = Verification(
        status=comp.data_status,
        last_verified_at=comp.last_verified_at,
        trusted_level=comp.trusted_level,
        note="已人工确认" if comp.data_status == DataStatus.VERIFIED else "AI整理，待人工访问官网复核",
    )

    return CompetitionDetail(
        competition=comp,
        timeline=timeline,
        requirements=requirements,
        sources=sources,
        verification=verification,
    )


def _user_to_pydantic(m: UserProfileModel) -> UserProfile:
    return UserProfile(
        user_id=m.user_id,
        education_level=EducationLevel(m.education_level),
        grade=_to_enum(Grade, m.grade, Grade.FRESHMAN),
        major=m.major,
        skills=_load_json(m.skills),
        experiences=_load_json(m.experiences),
        weekly_available_hours=m.weekly_available_hours,
        expected_team_size=m.expected_team_size,
        privacy_consent=m.privacy_consent,
        display_name=getattr(m, "display_name", None),
        persona=getattr(m, "persona", None),
        avatar=getattr(m, "avatar", None),
    )


def get_user_profile(user_id: str) -> Optional[UserProfile]:
    with session_scope() as session:
        m = session.get(UserProfileModel, user_id)
        if m is None:
            return None
        return _user_to_pydantic(m)


def list_user_profiles() -> list[UserProfile]:
    """列出所有用户画像（用于登录页展示可选身份）。"""
    with session_scope() as session:
        rows = session.query(UserProfileModel).all()
        return [_user_to_pydantic(m) for m in rows]


def save_user_profile(profile: UserProfile) -> UserProfile:
    with session_scope() as session:
        existing = session.get(UserProfileModel, profile.user_id)
        if existing is None:
            existing = UserProfileModel(user_id=profile.user_id)
            session.add(existing)
        existing.education_level = profile.education_level.value
        existing.grade = profile.grade.value
        existing.major = profile.major
        existing.skills = _dump_json(profile.skills)
        existing.experiences = _dump_json(profile.experiences)
        existing.weekly_available_hours = profile.weekly_available_hours
        existing.expected_team_size = profile.expected_team_size
        existing.privacy_consent = profile.privacy_consent
        if profile.display_name is not None:
            existing.display_name = profile.display_name
        if profile.persona is not None:
            existing.persona = profile.persona
        if profile.avatar is not None:
            existing.avatar = profile.avatar
    return profile


def delete_user_profile(user_id: str) -> dict:
    """删除画像及其项目数据；赛事官方数据不受影响。"""
    with session_scope() as session:
        profile = session.get(UserProfileModel, user_id)
        projects = session.query(UserProjectModel).filter(UserProjectModel.user_id == user_id).all()
        project_count = len(projects)
        item_count = sum(len(p.items) for p in projects)
        for project in projects:
            session.delete(project)
        if profile is not None:
            session.delete(profile)
        return {"deleted": profile is not None, "projects_deleted": project_count, "items_deleted": item_count}


def _project_to_pydantic(m: UserProjectModel) -> UserProject:
    comp = m.competition
    return UserProject(
        project_id=m.project_id,
        user_id=m.user_id,
        competition_id=m.competition_id,
        competition_name=comp.competition_name,
        document_year=comp.document_year,
        # 截止日期始终从赛事主表读取，项目表不保存副本。
        registration_deadline=comp.registration_deadline,
        submission_deadline=comp.submission_deadline,
        status=ProjectStatus(m.status),
        created_at=m.created_at.isoformat(),
        items=[
            ProjectItem(
                item_id=i.item_id,
                item_type=ProjectItemType(i.item_type),
                title=i.title,
                due_date=i.due_date,
                status=ProjectItemStatus(i.status),
                sort_order=i.sort_order,
            )
            for i in sorted(m.items, key=lambda item: (item.sort_order, item.item_id))
        ],
    )


def list_user_projects(user_id: str) -> list[UserProject]:
    with session_scope() as session:
        rows = (
            session.query(UserProjectModel)
            .filter(UserProjectModel.user_id == user_id)
            .order_by(UserProjectModel.created_at.desc())
            .all()
        )
        return [_project_to_pydantic(row) for row in rows]


def get_user_project(user_id: str, project_id: int) -> Optional[UserProject]:
    with session_scope() as session:
        row = session.get(UserProjectModel, project_id)
        if row is None or row.user_id != user_id:
            return None
        return _project_to_pydantic(row)


def create_user_project(user_id: str, competition_id: str) -> UserProject:
    with session_scope() as session:
        if session.get(UserProfileModel, user_id) is None:
            raise ValueError("profile_required")
        comp = session.get(CompetitionModel, competition_id)
        if comp is None:
            raise ValueError("competition_not_found")
        if comp.data_status != DataStatus.VERIFIED.value:
            raise ValueError("competition_unverified")
        effective_deadline = comp.registration_deadline or comp.submission_deadline
        if effective_deadline is not None and effective_deadline < date.today():
            raise ValueError("competition_expired")
        existing = (
            session.query(UserProjectModel)
            .filter(
                UserProjectModel.user_id == user_id,
                UserProjectModel.competition_id == competition_id,
            )
            .first()
        )
        if existing is not None:
            return _project_to_pydantic(existing)

        project = UserProjectModel(
            user_id=user_id,
            competition_id=competition_id,
            status=ProjectStatus.PLANNED.value,
        )
        session.add(project)
        session.flush()

        defaults: list[tuple[str, str, Optional[date]]] = [
            (ProjectItemType.TASK.value, "核对参赛资格与官方证据", None),
        ]
        if comp.team_required:
            defaults.append((ProjectItemType.TASK.value, "确认团队成员与分工", comp.registration_deadline))
        if comp.registration_deadline:
            defaults.append((ProjectItemType.TASK.value, "完成赛事报名", comp.registration_deadline))
        material_due = comp.submission_deadline or comp.registration_deadline
        defaults.extend(
            (ProjectItemType.MATERIAL.value, material, material_due)
            for material in _load_json(comp.required_materials)
        )
        for order, (item_type, title, due_date) in enumerate(defaults):
            session.add(
                ProjectItemModel(
                    project_id=project.project_id,
                    item_type=item_type,
                    title=title,
                    due_date=due_date,
                    status=ProjectItemStatus.TODO.value,
                    sort_order=order,
                )
            )
        session.flush()
        session.refresh(project)
        session.expire(project, ["items"])
        return _project_to_pydantic(project)


def update_user_project(user_id: str, project_id: int, status: ProjectStatus) -> Optional[UserProject]:
    with session_scope() as session:
        row = session.get(UserProjectModel, project_id)
        if row is None or row.user_id != user_id:
            return None
        row.status = status.value
        session.flush()
        return _project_to_pydantic(row)


def delete_user_project(user_id: str, project_id: int) -> bool:
    with session_scope() as session:
        row = session.get(UserProjectModel, project_id)
        if row is None or row.user_id != user_id:
            return False
        session.delete(row)
        return True


def add_project_item(user_id: str, project_id: int, item_type: ProjectItemType, title: str,
                     due_date: Optional[date]) -> Optional[ProjectItem]:
    with session_scope() as session:
        project = session.get(UserProjectModel, project_id)
        if project is None or project.user_id != user_id:
            return None
        max_order = max((item.sort_order for item in project.items), default=-1)
        item = ProjectItemModel(
            project_id=project_id,
            item_type=item_type.value,
            title=title.strip(),
            due_date=due_date,
            status=ProjectItemStatus.TODO.value,
            sort_order=max_order + 1,
        )
        session.add(item)
        session.flush()
        return ProjectItem(
            item_id=item.item_id, item_type=item_type, title=item.title,
            due_date=item.due_date, status=ProjectItemStatus.TODO, sort_order=item.sort_order,
        )


def update_project_item(user_id: str, project_id: int, item_id: int, *, title: Optional[str],
                        due_date: Optional[date], status: Optional[ProjectItemStatus]) -> Optional[ProjectItem]:
    with session_scope() as session:
        project = session.get(UserProjectModel, project_id)
        item = session.get(ProjectItemModel, item_id)
        if project is None or project.user_id != user_id or item is None or item.project_id != project_id:
            return None
        if title is not None:
            item.title = title.strip()
        if due_date is not None:
            item.due_date = due_date
        if status is not None:
            item.status = status.value
        session.flush()
        return ProjectItem(
            item_id=item.item_id, item_type=ProjectItemType(item.item_type), title=item.title,
            due_date=item.due_date, status=ProjectItemStatus(item.status), sort_order=item.sort_order,
        )


def delete_project_item(user_id: str, project_id: int, item_id: int) -> bool:
    with session_scope() as session:
        project = session.get(UserProjectModel, project_id)
        item = session.get(ProjectItemModel, item_id)
        if project is None or project.user_id != user_id or item is None or item.project_id != project_id:
            return False
        session.delete(item)
        return True


def upsert_competition(comp: Competition) -> Competition:
    """创建或更新赛事（含 evidence 列表）。

    用于「上传→解析→人工确认」闭环：调用方在确认时把 data_status 置为
    verified，并把人工关联的原文块作为 evidence 写入，从而保证后续问答的
    引用可追溯到官方通知、且数据状态升级为已核验。幂等：按 competition_id 覆盖。
    """
    with session_scope() as session:
        cid = comp.competition_id
        existing = session.get(CompetitionModel, cid)
        if existing is None:
            existing = CompetitionModel(competition_id=cid)
            session.add(existing)

        existing.competition_name = comp.competition_name
        existing.document_year = comp.document_year
        existing.category = comp.category.value
        existing.organizer = comp.organizer
        existing.eligible_students = _dump_json([s.value for s in comp.eligible_students])
        existing.allowed_grades = (
            None if comp.allowed_grades is None else _dump_json([g.value for g in comp.allowed_grades])
        )
        existing.allowed_majors = (
            None if comp.allowed_majors is None else _dump_json(comp.allowed_majors)
        )
        existing.team_required = comp.team_required
        existing.team_min = comp.team_min
        existing.team_max = comp.team_max
        existing.registration_deadline = comp.registration_deadline
        existing.submission_deadline = comp.submission_deadline
        existing.required_materials = _dump_json(comp.required_materials)
        existing.evaluation_dimensions = _dump_json(comp.evaluation_dimensions)
        existing.required_skills = _dump_json(comp.required_skills)
        existing.official_source_url = comp.official_source_url
        existing.source_acquired_date = comp.source_acquired_date
        existing.trusted_level = (
            comp.trusted_level.value if isinstance(comp.trusted_level, TrustedLevel) else comp.trusted_level
        )
        existing.data_status = (
            comp.data_status.value if isinstance(comp.data_status, DataStatus) else comp.data_status
        )
        existing.last_verified_at = comp.last_verified_at
        existing.doc_version = comp.doc_version

        # evidence：先删后插，保证与本次确认一致
        for old in list(existing.citations):
            session.delete(old)
        session.flush()
        for e in comp.evidence:
            session.add(
                CitationModel(
                    competition_id=cid,
                    field=e.field,
                    page=e.page,
                    source_text=e.source_text,
                    document_name=e.document_name,
                    source_url=e.source_url,
                    acquired_date=e.acquired_date,
                    last_verified_at=e.last_verified_at,
                    trusted_level=(
                        e.trusted_level.value
                        if isinstance(e.trusted_level, TrustedLevel)
                        else e.trusted_level
                    ),
                )
            )
    return comp


if __name__ == "__main__":
    init_db()
    n = seed_all()
    print(f"[db] 初始化完成，赛事已 seed {n} 条。")
    comps = get_all_competitions()
    print(f"[db] 当前赛事总数：{len(comps)}")
    for c in comps[:5]:
        print(f"  - {c.competition_id} ({c.category.value}, {c.document_year}) evidence={len(c.evidence)}")
