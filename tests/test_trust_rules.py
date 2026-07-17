from __future__ import annotations

import json
import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
GROUND_TRUTH_DIR = PROJECT_ROOT / "data" / "ground_truth" / "samples"
sys.path.insert(0, str(SRC_DIR))

import db  # noqa: E402
from recommendation.engine import recommend_for_user  # noqa: E402
from agent.graph import run_agent  # noqa: E402
from rag.store import get_rag  # noqa: E402
from schemas import (  # noqa: E402
    Competition,
    CompetitionCategory,
    DataStatus,
    EducationLevel,
    Grade,
    TrustedLevel,
    UserProfile,
)


def _user() -> UserProfile:
    return UserProfile(
        user_id="test_user",
        education_level=EducationLevel.UNDERGRADUATE,
        grade=Grade.SOPHOMORE,
        major="计算机科学与技术",
        weekly_available_hours=10,
        expected_team_size=1,
        privacy_consent=True,
    )


def _competition(**overrides) -> Competition:
    values = {
        "competition_id": "test_competition_2026",
        "competition_name": "测试赛事",
        "document_year": 2026,
        "category": CompetitionCategory.PROGRAMMING,
        "eligible_students": [EducationLevel.UNDERGRADUATE],
        "registration_deadline": date.today() + timedelta(days=30),
        "official_source_url": "https://example.edu/official-notice",
        "source_acquired_date": date.today().isoformat(),
        "trusted_level": TrustedLevel.A,
        "data_status": DataStatus.VERIFIED,
        "last_verified_at": date.today().isoformat(),
    }
    values.update(overrides)
    return Competition(**values)


class TrustRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        db.init_db()

    def test_database_deadlines_match_ground_truth(self) -> None:
        files = sorted(GROUND_TRUTH_DIR.glob("*.json"))
        self.assertGreaterEqual(len(files), 12)

        for path in files:
            raw = json.loads(path.read_text(encoding="utf-8"))
            comp = db.get_competition(path.stem)
            self.assertIsNotNone(comp, path.name)
            self.assertEqual(
                comp.registration_deadline.isoformat() if comp.registration_deadline else None,
                raw.get("registration_deadline"),
                f"{path.name} 报名截止日期与 Ground Truth 不一致",
            )
            self.assertEqual(
                comp.submission_deadline.isoformat() if comp.submission_deadline else None,
                raw.get("submission_deadline"),
                f"{path.name} 提交截止日期与 Ground Truth 不一致",
            )

    def test_expired_competition_has_null_score(self) -> None:
        cases = (
            (_competition(registration_deadline=date.today() - timedelta(days=1)), "报名已经截止"),
            (
                _competition(
                    registration_deadline=None,
                    submission_deadline=date.today() - timedelta(days=1),
                ),
                "作品提交已经截止",
            ),
        )
        for expired, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                result = recommend_for_user(_user(), [expired], date.today())[0]
                self.assertEqual(result.recommendation_status, "ineligible")
                self.assertFalse(result.eligible)
                self.assertIsNone(result.score)
                self.assertIsNone(result.match_breakdown)
                self.assertIn(expected_reason, [reason.reason for reason in result.gate_reasons])

    def test_unverified_competition_is_candidate_without_score(self) -> None:
        candidate = _competition(
            data_status=DataStatus.UNVERIFIED,
            trusted_level=TrustedLevel.B,
            last_verified_at=None,
        )
        result = recommend_for_user(_user(), [candidate], date.today())[0]

        self.assertEqual(result.recommendation_status, "candidate_only")
        self.assertFalse(result.eligible)
        self.assertTrue(result.pending_review)
        self.assertIsNone(result.score)
        self.assertIsNone(result.match_breakdown)

    def test_education_levels_are_complete_and_unknown_values_fail(self) -> None:
        for path in sorted(GROUND_TRUTH_DIR.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            for value in raw.get("eligible_students", []):
                EducationLevel(value)

        model = db.CompetitionModel(
            competition_id="invalid_education",
            competition_name="未知学历测试",
            document_year=2026,
            category="programming",
            eligible_students=json.dumps(["未知学历"], ensure_ascii=False),
            allowed_grades=None,
            allowed_majors=None,
            team_required=False,
            team_min=None,
            team_max=None,
            registration_deadline=date.today() + timedelta(days=30),
            submission_deadline=None,
            required_materials="[]",
            evaluation_dimensions="[]",
            required_skills="[]",
            official_source_url="https://example.edu/notice",
            source_acquired_date=date.today().isoformat(),
            trusted_level="C",
            data_status="unverified",
            last_verified_at=None,
            doc_version="2026_v1",
        )
        with self.assertRaises(ValueError):
            db._competition_to_pydantic(model)

    def test_verified_core_competitions_have_page_level_evidence(self) -> None:
        required_fields = {"registration_deadline", "eligible_students", "team_min", "team_max", "required_materials"}
        verified_records = []

        for path in sorted(GROUND_TRUTH_DIR.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("data_status") == "verified":
                verified_records.append((path.stem, raw))

        self.assertGreaterEqual(len(verified_records), 12)

        for competition_id, raw in verified_records:
            self.assertEqual(raw["data_status"], "verified")
            self.assertEqual(raw["trusted_level"], "A")
            by_field = {field: [] for field in required_fields}
            for evidence in raw["evidence"]:
                if evidence["field"] in by_field:
                    by_field[evidence["field"]].append(evidence)
            for field, evidence_items in by_field.items():
                self.assertTrue(evidence_items, f"{competition_id}.{field} 缺少证据")
                for evidence in evidence_items:
                    self.assertIsInstance(evidence["page"], int)
                    self.assertTrue(evidence["source_text"])
                    self.assertTrue(evidence["source_url"].startswith("http"))
                    self.assertEqual(evidence["acquired_date"], "2026-07-16")
                    self.assertEqual(evidence["last_verified_at"], "2026-07-16")

    def test_rag_and_agent_use_one_canonical_registration_deadline(self) -> None:
        core_ids = (
            "china_softcup_2026",
            "fwb_2026",
            "mathorcup_2026",
            "mcm_cn_2026",
            "mai_qihang_2026",
            "sanchuang_2026",
        )
        for competition_id in core_ids:
            comp = db.get_competition(competition_id)
            self.assertIsNotNone(comp)
            expected = comp.registration_deadline.isoformat()

            citations = get_rag().query(competition_id, "报名截止日期是什么时候", top_k=4)
            self.assertTrue(any(c.field == "registration_deadline" for c in citations))

            result = run_agent("报名截止日期是什么时候", competition_id=competition_id, top_k=4)
            canonical = re.findall(r"报名截止日期：(\d{4}-\d{2}-\d{2})", result["answer"])
            self.assertEqual(canonical, [expected], f"{competition_id} 出现非唯一截止日期")
            self.assertTrue(result["citations"])
            self.assertEqual({c["field"] for c in result["citations"]}, {"registration_deadline"})

    def test_competition_without_national_registration_deadline_does_not_invent_one(self) -> None:
        result = run_agent("报名截止日期是什么时候", competition_id="jsj_sj_2026", top_k=4)
        self.assertIn("未给出全国统一报名截止日期", result["answer"])
        self.assertNotRegex(result["answer"], r"报名截止日期：\d{4}-\d{2}-\d{2}")

    def test_team_query_uses_team_evidence_without_inventing_minimum(self) -> None:
        result = run_agent("MathorCup 团队几人", competition_id="mathorcup_2026", top_k=4)
        self.assertTrue(result["citations"])
        self.assertTrue({c["field"] for c in result["citations"]} & {"team_min", "team_max"})
        citation_text = " ".join(c["source_text"] for c in result["citations"])
        self.assertNotIn("1至3", citation_text)

        detail = db.get_competition_detail("mathorcup_2026")
        self.assertIsNotNone(detail)
        self.assertIn("最多 3 人", detail.requirements[0].text)


if __name__ == "__main__":
    unittest.main()
