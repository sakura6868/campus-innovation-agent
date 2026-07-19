from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import api  # noqa: E402
import db  # noqa: E402
from agent.graph import run_agent  # noqa: E402
from schemas import (  # noqa: E402
    Citation,
    Competition,
    CompetitionCategory,
    DataStatus,
    EducationLevel,
    Grade,
    ProjectItemStatus,
    ProjectItemType,
    ProjectStatus,
    TrustedLevel,
    UserProfile,
)


class SubmissionCases(unittest.TestCase):
    OPEN_COMPETITION_ID = "test_open_project_2099"
    EXPIRED_COMPETITION_ID = "test_expired_project_2000"

    @classmethod
    def setUpClass(cls) -> None:
        db.init_db()
        checked_at = "2026-07-19"
        source_url = "https://example.edu/project-test"
        evidence = [
            Citation(
                field=field,
                source_text=f"项目测试官方原文：{field}",
                document_name="project-test.html",
                source_url=source_url,
                acquired_date=checked_at,
                last_verified_at=checked_at,
            )
            for field in ("registration_deadline", "eligible_students", "team_min", "team_max", "required_materials")
        ]
        base = dict(
            competition_name="项目工作台测试赛事",
            document_year=2099,
            category=CompetitionCategory.SOFTWARE,
            eligible_students=[EducationLevel.UNDERGRADUATE],
            team_required=True,
            team_min=1,
            team_max=3,
            required_materials=["报名表"],
            official_source_url=source_url,
            source_acquired_date=checked_at,
            trusted_level=TrustedLevel.A,
            data_status=DataStatus.VERIFIED,
            last_verified_at=checked_at,
            official_source_status="found",
            evidence=evidence,
        )
        db.upsert_competition(
            Competition(competition_id=cls.OPEN_COMPETITION_ID, registration_deadline=date(2099, 7, 20), **base)
        )
        db.upsert_competition(
            Competition(
                competition_id=cls.EXPIRED_COMPETITION_ID,
                registration_deadline=date(2000, 1, 1),
                **{**base, "competition_name": "已截止项目测试赛事", "document_year": 2000},
            )
        )

    @classmethod
    def tearDownClass(cls) -> None:
        with db.session_scope() as session:
            for competition_id in (cls.OPEN_COMPETITION_ID, cls.EXPIRED_COMPETITION_ID):
                row = session.get(db.CompetitionModel, competition_id)
                if row is not None:
                    session.delete(row)

    def setUp(self) -> None:
        self.user_id = f"case_{self._testMethodName}"
        db.save_user_profile(
            UserProfile(
                user_id=self.user_id,
                education_level=EducationLevel.UNDERGRADUATE,
                grade=Grade.SOPHOMORE,
                major="软件工程",
                skills=["Python"],
                weekly_available_hours=12,
                expected_team_size=3,
                privacy_consent=True,
            )
        )

    def tearDown(self) -> None:
        db.delete_user_profile(self.user_id)

    def test_01_join_verified_open_competition(self) -> None:
        project = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        self.assertEqual(project.competition_id, self.OPEN_COMPETITION_ID)
        self.assertTrue(project.items)

    def test_02_join_is_idempotent(self) -> None:
        first = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        second = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        self.assertEqual(first.project_id, second.project_id)
        self.assertEqual(len(db.list_user_projects(self.user_id)), 1)

    def test_03_unverified_competition_cannot_become_project(self) -> None:
        with self.assertRaisesRegex(ValueError, "competition_unverified"):
            db.create_user_project(self.user_id, "accounting_2026")

    def test_04_expired_competition_cannot_become_project(self) -> None:
        with self.assertRaisesRegex(ValueError, "competition_expired"):
            db.create_user_project(self.user_id, self.EXPIRED_COMPETITION_ID)

    def test_05_project_deadline_is_read_from_competition(self) -> None:
        project = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        comp = db.get_competition(self.OPEN_COMPETITION_ID)
        self.assertEqual(project.registration_deadline, comp.registration_deadline)
        self.assertEqual(project.submission_deadline, comp.submission_deadline)

    def test_06_update_project_status(self) -> None:
        project = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        updated = db.update_user_project(self.user_id, project.project_id, ProjectStatus.IN_PROGRESS)
        self.assertEqual(updated.status, ProjectStatus.IN_PROGRESS)

    def test_07_complete_project_item(self) -> None:
        project = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        item = project.items[0]
        updated = db.update_project_item(
            self.user_id, project.project_id, item.item_id,
            title=None, due_date=None, status=ProjectItemStatus.DONE,
        )
        self.assertEqual(updated.status, ProjectItemStatus.DONE)

    def test_08_add_and_delete_material(self) -> None:
        project = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        item = db.add_project_item(
            self.user_id, project.project_id, ProjectItemType.MATERIAL,
            "补充测试报告", date(2026, 7, 19),
        )
        self.assertEqual(item.item_type, ProjectItemType.MATERIAL)
        self.assertTrue(db.delete_project_item(self.user_id, project.project_id, item.item_id))

    def test_09_project_delete_is_owner_scoped(self) -> None:
        project = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        self.assertFalse(db.delete_user_project("another_user", project.project_id))
        self.assertIsNotNone(db.get_user_project(self.user_id, project.project_id))

    def test_10_ics_contains_official_deadline(self) -> None:
        project = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        response = api.export_project_calendar(self.user_id, project.project_id)
        content = response.body.decode("utf-8")
        self.assertIn("BEGIN:VCALENDAR", content)
        self.assertIn("DTSTART;VALUE=DATE:20990720", content)

    def test_11_profile_delete_cascades_projects(self) -> None:
        db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        result = db.delete_user_profile(self.user_id)
        self.assertTrue(result["deleted"])
        self.assertEqual(result["projects_deleted"], 1)
        self.assertEqual(db.list_user_projects(self.user_id), [])

    def test_12_same_name_defaults_to_latest_verified_version(self) -> None:
        result = run_agent("高教社杯全国大学生数学建模竞赛报名截止")
        self.assertEqual(result["resolved_competition"], "mcm_cn_2026")
        self.assertIn("最新官网来源已确认版本：2026年", result["answer"])
        # 截止日期事实须来自 evidence（确定性字段），不校验 LLM 自由措辞
        self.assertTrue(any(c["field"] == "registration_deadline" for c in result["citations"]))
        self.assertTrue(result["citations"])

    def test_13_no_year_resolves_latest_verified_version(self) -> None:
        # 同名多年份且存在「已锚定官方来源」版本时，未指定年份默认按最新届作答
        # （不再卡在「请明确年份」，避免常见赛事无法触发润色与引用）。
        result = run_agent("蓝桥杯报名截止")
        self.assertEqual(result["resolved_competition"], "lanqiao_2026")
        self.assertTrue(any(c["field"] == "registration_deadline" for c in result["citations"]))
        self.assertTrue(result["answer"].strip())

    def test_14_explicit_year_resolves_requested_version(self) -> None:
        result = run_agent("2026年蓝桥杯报名截止")
        self.assertEqual(result["resolved_competition"], "lanqiao_2026")
        # 截止日期事实须来自 evidence（确定性字段），不校验 LLM 自由措辞
        self.assertTrue(any(c["field"] == "registration_deadline" for c in result["citations"]))
        self.assertTrue(result["answer"].strip())

    def test_15_missing_project_returns_none(self) -> None:
        self.assertIsNone(db.get_user_project(self.user_id, 99999999))

    def test_16_empty_ics_project_is_still_valid_calendar(self) -> None:
        project = db.create_user_project(self.user_id, self.OPEN_COMPETITION_ID)
        for item in project.items:
            db.delete_project_item(self.user_id, project.project_id, item.item_id)
        content = api.export_project_calendar(self.user_id, project.project_id).body.decode("utf-8")
        self.assertTrue(content.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(content.endswith("END:VCALENDAR\r\n"))


if __name__ == "__main__":
    unittest.main()
