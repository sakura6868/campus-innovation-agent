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
    EducationLevel,
    Grade,
    ProjectItemStatus,
    ProjectItemType,
    ProjectStatus,
    UserProfile,
)


class SubmissionCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        db.init_db()

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
        project = db.create_user_project(self.user_id, "china_softcup_2026")
        self.assertEqual(project.competition_id, "china_softcup_2026")
        self.assertTrue(project.items)

    def test_02_join_is_idempotent(self) -> None:
        first = db.create_user_project(self.user_id, "china_softcup_2026")
        second = db.create_user_project(self.user_id, "china_softcup_2026")
        self.assertEqual(first.project_id, second.project_id)
        self.assertEqual(len(db.list_user_projects(self.user_id)), 1)

    def test_03_unverified_competition_cannot_become_project(self) -> None:
        with self.assertRaisesRegex(ValueError, "competition_unverified"):
            db.create_user_project(self.user_id, "lanqiao_2026")

    def test_04_expired_competition_cannot_become_project(self) -> None:
        with self.assertRaisesRegex(ValueError, "competition_expired"):
            db.create_user_project(self.user_id, "jsj_sj_2026")

    def test_05_project_deadline_is_read_from_competition(self) -> None:
        project = db.create_user_project(self.user_id, "china_softcup_2026")
        comp = db.get_competition("china_softcup_2026")
        self.assertEqual(project.registration_deadline, comp.registration_deadline)
        self.assertEqual(project.submission_deadline, comp.submission_deadline)

    def test_06_update_project_status(self) -> None:
        project = db.create_user_project(self.user_id, "china_softcup_2026")
        updated = db.update_user_project(self.user_id, project.project_id, ProjectStatus.IN_PROGRESS)
        self.assertEqual(updated.status, ProjectStatus.IN_PROGRESS)

    def test_07_complete_project_item(self) -> None:
        project = db.create_user_project(self.user_id, "china_softcup_2026")
        item = project.items[0]
        updated = db.update_project_item(
            self.user_id, project.project_id, item.item_id,
            title=None, due_date=None, status=ProjectItemStatus.DONE,
        )
        self.assertEqual(updated.status, ProjectItemStatus.DONE)

    def test_08_add_and_delete_material(self) -> None:
        project = db.create_user_project(self.user_id, "china_softcup_2026")
        item = db.add_project_item(
            self.user_id, project.project_id, ProjectItemType.MATERIAL,
            "补充测试报告", date(2026, 7, 19),
        )
        self.assertEqual(item.item_type, ProjectItemType.MATERIAL)
        self.assertTrue(db.delete_project_item(self.user_id, project.project_id, item.item_id))

    def test_09_project_delete_is_owner_scoped(self) -> None:
        project = db.create_user_project(self.user_id, "china_softcup_2026")
        self.assertFalse(db.delete_user_project("another_user", project.project_id))
        self.assertIsNotNone(db.get_user_project(self.user_id, project.project_id))

    def test_10_ics_contains_official_deadline(self) -> None:
        project = db.create_user_project(self.user_id, "china_softcup_2026")
        response = api.export_project_calendar(self.user_id, project.project_id)
        content = response.body.decode("utf-8")
        self.assertIn("BEGIN:VCALENDAR", content)
        self.assertIn("DTSTART;VALUE=DATE:20260720", content)

    def test_11_profile_delete_cascades_projects(self) -> None:
        db.create_user_project(self.user_id, "china_softcup_2026")
        result = db.delete_user_profile(self.user_id)
        self.assertTrue(result["deleted"])
        self.assertEqual(result["projects_deleted"], 1)
        self.assertEqual(db.list_user_projects(self.user_id), [])

    def test_12_same_name_defaults_to_latest_verified_version(self) -> None:
        result = run_agent("高教社杯全国大学生数学建模竞赛报名截止")
        self.assertEqual(result["resolved_competition"], "mcm_cn_2026")
        self.assertIn("最新已核验版本：2026年", result["answer"])
        self.assertIn("报名截止日期：2026-09-07", result["answer"])

    def test_13_same_name_without_verified_version_asks_for_year(self) -> None:
        result = run_agent("蓝桥杯报名截止")
        self.assertIsNone(result["resolved_competition"])
        self.assertIn("存在多个年份版本", result["answer"])
        self.assertIn("请明确年份", result["answer"])

    def test_14_explicit_year_resolves_requested_version(self) -> None:
        result = run_agent("2026年蓝桥杯报名截止")
        self.assertEqual(result["resolved_competition"], "lanqiao_2026")
        self.assertIn("2026-03-11", result["answer"])

    def test_15_missing_project_returns_none(self) -> None:
        self.assertIsNone(db.get_user_project(self.user_id, 99999999))

    def test_16_empty_ics_project_is_still_valid_calendar(self) -> None:
        project = db.create_user_project(self.user_id, "china_softcup_2026")
        for item in project.items:
            db.delete_project_item(self.user_id, project.project_id, item.item_id)
        content = api.export_project_calendar(self.user_id, project.project_id).body.decode("utf-8")
        self.assertTrue(content.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(content.endswith("END:VCALENDAR\r\n"))


if __name__ == "__main__":
    unittest.main()
