"""Offline endpoint tests for the W5 Review Agent API (Track B).

Uses FastAPI's TestClient against a fresh FakeReviewStore per test (injected via
``app.dependency_overrides`` for isolation). No network, AWS, or DB.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from review_api.app import app, get_store  # noqa: E402
from review_api.fake_store import FakeReviewStore  # noqa: E402

PROPERTY_ID = "b470b97b-4ea7-481c-97b7-22a81a219587"
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


class ReviewApiTestCase(unittest.TestCase):
    def setUp(self):
        # Fresh store per test so session state never leaks between tests.
        store = FakeReviewStore()
        app.dependency_overrides[get_store] = lambda: store
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()


class ReadEndpointTests(ReviewApiTestCase):
    def test_equipment_list(self):
        resp = self.client.get("/equipment")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 56)

    def test_equipment_default_sort_confidence_asc(self):
        # Unscored items are deterministic by name under the default sort.
        names = [it["canonical_name"] for it in self.client.get("/equipment").json()]
        self.assertEqual(names, sorted(names))

    def test_equipment_filter_review_required(self):
        items = self.client.get("/equipment?review_required=true").json()
        self.assertTrue(items)
        self.assertTrue(all(it["review_required"] for it in items))

    def test_equipment_filter_status(self):
        items = self.client.get("/equipment?status=settled").json()
        self.assertEqual(len(items), 8)

    def test_relationships_w06_snapshot_renders(self):
        body = self.client.get("/relationships").json()
        # edge_count/orphan_count are plain properties (not serialized); the
        # client derives them from the lists. The W6 graphics snapshot carries
        # 44 candidate edges; unknown_node errors stand until the DOAS/plant
        # equipment candidates are reviewer-confirmed.
        self.assertEqual(len(body["edges"]), 44)
        self.assertEqual(len(body["orphans"]), 30)
        self.assertFalse(body["passed"])
        self.assertTrue(body["errors"])
        flagged = [edge for edge in body["edges"] if edge["review_required"]]
        self.assertEqual(len(flagged), 16)
        self.assertTrue(all(edge["review_reason"] for edge in flagged))

    def test_discrepancies_counts_and_rollups(self):
        body = self.client.get("/discrepancies").json()
        self.assertEqual(
            body["counts"],
            {
                "matched": 11,
                "missing_from_drawings": 19,
                "missing_from_points": 19,
                "resolved_out_of_scope": 7,
            },
        )
        self.assertIn(
            "Floor_02: 4 AHU missing from drawings (high severity)", body["rollups"]
        )

    def test_discrepancies_three_groupings(self):
        for dimension, expected in (
            ("floor", {"Floor_02"}),
            ("equipment_type", {"AHU", "VAV", "FCU", "OAVAV", "EAVAV", "FPTU", "VAV-RH-HW"}),
            ("severity_hint", {"high", "medium", "low"}),
        ):
            body = self.client.get(f"/discrepancies?group_by={dimension}").json()
            self.assertEqual(body["group_by"], dimension)
            self.assertEqual(set(body["groups"].keys()), expected)

    def test_discrepancies_status_filter(self):
        body = self.client.get("/discrepancies?status=resolved_out_of_scope").json()
        self.assertEqual(len(body["items"]), 7)
        self.assertTrue(all(it["resolved_floor"] == "1" for it in body["items"]))

    def test_zones_empty(self):
        resp = self.client.get("/zones")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])


class SessionEndpointTests(ReviewApiTestCase):
    def _open(self):
        resp = self.client.post(
            "/sessions",
            json={"property_id": PROPERTY_ID, "floor": "Floor_02", "reviewer": "tester"},
        )
        self.assertEqual(resp.status_code, 201)
        return resp.json()

    def test_full_open_action_commit_flow(self):
        session = self._open()
        self.assertGreater(session["n_pending"], 0)
        sid = session["session_id"]
        equipment = self.client.get("/equipment").json()

        approve = self.client.post(
            f"/sessions/{sid}/actions",
            json={"item_type": "equipment", "item_key": equipment[0]["canonical_name"], "action": "approve"},
        )
        self.assertEqual(approve.status_code, 200)
        self.client.post(
            f"/sessions/{sid}/actions",
            json={
                "item_type": "equipment",
                "item_key": equipment[1]["canonical_name"],
                "action": "edit",
                "payload": {"equipment_type": "AHU"},
                "reason": "corrected",
            },
        )
        self.client.post(
            f"/sessions/{sid}/actions",
            json={"item_type": "equipment", "item_key": equipment[2]["canonical_name"], "action": "reject", "reason": "misread"},
        )

        state = self.client.get(f"/sessions/{sid}").json()
        self.assertEqual(state["n_approved"], 2)
        self.assertEqual(state["n_rejected"], 1)

        commit = self.client.post(f"/sessions/{sid}/commit").json()
        self.assertTrue(commit["committed"])
        self.assertEqual(commit["n_committed"], 2)
        self.assertEqual(commit["n_corrections"], 2)

    def test_nothing_committed_until_commit_call(self):
        session = self._open()
        sid = session["session_id"]
        equipment = self.client.get("/equipment").json()
        self.client.post(
            f"/sessions/{sid}/actions",
            json={"item_type": "equipment", "item_key": equipment[0]["canonical_name"], "action": "approve"},
        )
        # Still open; no commit has happened.
        self.assertEqual(self.client.get(f"/sessions/{sid}").json()["status"], "open")

    def test_delete_one_and_all_actions_restore_server_counts(self):
        session = self._open()
        sid = session["session_id"]
        equipment = self.client.get("/equipment?review_required=true").json()
        first = equipment[0]["canonical_name"]
        second = equipment[1]["canonical_name"]
        self.client.post(
            f"/sessions/{sid}/actions",
            json={"item_type": "equipment", "item_key": first, "action": "approve"},
        )
        self.client.post(
            f"/sessions/{sid}/actions",
            json={
                "item_type": "equipment",
                "item_key": second,
                "action": "reject",
                "reason": "not present",
            },
        )

        cleared = self.client.delete(
            f"/sessions/{sid}/actions/equipment/{first}"
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["n_pending"], session["n_pending"] - 1)
        self.assertEqual(cleared.json()["n_approved"], 0)
        self.assertEqual(cleared.json()["n_rejected"], 1)

        cleared_all = self.client.delete(f"/sessions/{sid}/actions")
        self.assertEqual(cleared_all.status_code, 200)
        self.assertEqual(cleared_all.json()["n_pending"], session["n_pending"])
        self.assertEqual(cleared_all.json()["n_approved"], 0)
        self.assertEqual(cleared_all.json()["n_rejected"], 0)

    def test_delete_actions_rejects_frozen_session(self):
        sid = self._open()["session_id"]
        equipment = self.client.get("/equipment").json()
        item_key = equipment[0]["canonical_name"]
        self.client.post(
            f"/sessions/{sid}/actions",
            json={"item_type": "equipment", "item_key": item_key, "action": "approve"},
        )
        self.client.post(f"/sessions/{sid}/commit")

        self.assertEqual(
            self.client.delete(
                f"/sessions/{sid}/actions/equipment/{item_key}"
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.delete(f"/sessions/{sid}/actions").status_code, 409
        )

    def test_get_unknown_session_404(self):
        self.assertEqual(self.client.get(f"/sessions/{UNKNOWN_ID}").status_code, 404)

    def test_action_on_unknown_session_404(self):
        resp = self.client.post(
            f"/sessions/{UNKNOWN_ID}/actions",
            json={"item_type": "equipment", "item_key": "AHU_2-A", "action": "approve"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_commit_unknown_session_404(self):
        self.assertEqual(
            self.client.post(f"/sessions/{UNKNOWN_ID}/commit").status_code, 404
        )

    def test_commit_twice_conflicts(self):
        sid = self._open()["session_id"]
        self.client.post(f"/sessions/{sid}/commit")
        self.assertEqual(self.client.post(f"/sessions/{sid}/commit").status_code, 409)

    def test_invalid_action_semantics_rejected(self):
        sid = self._open()["session_id"]
        # reject without a reason violates the ActionRequest validator -> 422.
        resp = self.client.post(
            f"/sessions/{sid}/actions",
            json={"item_type": "equipment", "item_key": "AHU_2-A", "action": "reject"},
        )
        self.assertEqual(resp.status_code, 422)


class OpenApiTests(ReviewApiTestCase):
    def test_openapi_lists_all_routes(self):
        spec = self.client.get("/openapi.json").json()
        for route in (
            "/equipment",
            "/relationships",
            "/discrepancies",
            "/zones",
            "/sessions",
            "/sessions/{session_id}",
            "/sessions/{session_id}/actions",
            "/sessions/{session_id}/actions/{item_type}/{item_key}",
            "/sessions/{session_id}/commit",
        ):
            self.assertIn(route, spec["paths"])

    def test_docs_available(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)


if __name__ == "__main__":
    unittest.main()
