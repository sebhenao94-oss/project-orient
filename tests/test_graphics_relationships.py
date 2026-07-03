"""Offline tests for pipeline/graphics_relationships.py (no network, no DB)."""

import unittest
from pathlib import Path

from pipeline.graphics_relationships import (
    CONF_EXTRAPOLATED,
    CONF_LIVE,
    CONF_OFFLINE,
    CONF_VALVE_AHU,
    CONF_VALVE_TERMINAL,
    EvidenceRow,
    build_snapshot_document,
    classify_widget_kind,
    evidence_rows_from_payload,
    extract_evidence,
    fuse_evidence,
    merge_tiling_edges,
)


def row(kind, page, obj="", state="offline", image="page.png", detail=""):
    return EvidenceRow(
        source_image=image, page_title=page, evidence_kind=kind,
        subject_raw=page, object_raw=obj, link_state=state, detail=detail)


def edges_by(result, ref_type=None):
    edges = result.edges
    if ref_type:
        edges = [e for e in edges if e["ref_type"] == ref_type]
    return {(e["child"], e["parent"]): e for e in edges}


class ClassifyWidgetKindTests(unittest.TestCase):
    def test_prefixes(self):
        self.assertEqual(classify_widget_kind("AHU 02 A"), "linked_widget_ahu")
        self.assertEqual(classify_widget_kind("OAVAV_02_04"), "linked_widget_oavav")
        self.assertEqual(classify_widget_kind("DOAS_22_1"), "linked_widget_doas")
        self.assertEqual(classify_widget_kind("CHW-PLANT_1"), "linked_widget_other")


class PayloadFlatteningTests(unittest.TestCase):
    def test_widgets_and_valves(self):
        payload = {
            "page_title": "FCU_02_3",
            "linked_widgets": [
                {"label": "OAVAV_02_06", "points_shown": ["Airflow 103.7 cfm"],
                 "values_live": True},
            ],
            "water_valves": {"chilled_water": True, "hot_water": False,
                             "detail": "CHWR Vlv Cmd, WWR Vlv Pos"},
        }
        rows = evidence_rows_from_payload("fcu_02_3.png", payload)
        kinds = [r.evidence_kind for r in rows]
        self.assertEqual(kinds, ["linked_widget_oavav", "valve_points"])
        self.assertEqual(rows[0].link_state, "live_synced")
        # WW token in the detail forces hot_water even when the flag is missed
        self.assertEqual(rows[1].object_raw, "CHW+WW")

    def test_no_widget_row(self):
        rows = evidence_rows_from_payload("x.png", {"page_title": "AHU 02 C"})
        self.assertEqual(rows[-1].evidence_kind, "no_linked_widget")


class FusionTests(unittest.TestCase):
    def test_linked_ahu_live_edge(self):
        result = fuse_evidence([
            row("linked_widget_ahu", "VAV_2_01", "AHU 02 A", "live_synced", "vav_2_1.png"),
        ])
        edge = edges_by(result)[("VAV_2-01", "AHU_2-A")]
        self.assertEqual(edge["ref_type"], "airRef")
        self.assertEqual(edge["confidence"], CONF_LIVE)
        self.assertFalse(edge["review_required"])
        self.assertEqual(edge["source_drawing"], "vav_2_1.png")

    def test_offline_link_still_yields_edge(self):
        result = fuse_evidence([
            row("linked_widget_ahu", "VAV_2_05", "AHU 02 A", "offline"),
        ])
        edge = edges_by(result)[("VAV_2-05", "AHU_2-A")]
        self.assertEqual(edge["confidence"], CONF_OFFLINE)

    def test_oavav_doas_extrapolation(self):
        rows = [
            row("linked_widget_doas", "OAVAV_02_01", "DOAS_22_1"),
            row("linked_widget_doas", "OAVAV_02_09", "DOAS_22_1"),
            row("linked_widget_oavav", "FCU_02_3", "OAVAV_02_06", "live_synced"),
        ]
        result = fuse_evidence(rows)
        air = edges_by(result, "airRef")
        self.assertIn(("OAVAV_2-01", "DOAS_22_1"), air)
        extrapolated = air[("OAVAV_2-06", "DOAS_22_1")]
        self.assertEqual(extrapolated["confidence"], CONF_EXTRAPOLATED)
        self.assertTrue(extrapolated["review_required"])
        self.assertEqual(extrapolated["evidence_kind"], "pattern_extrapolation")

    def test_extrapolation_needs_two_observed_pages(self):
        result = fuse_evidence([
            row("linked_widget_doas", "OAVAV_02_01", "DOAS_22_1"),
            row("linked_widget_oavav", "FCU_02_3", "OAVAV_02_06"),
        ])
        self.assertNotIn(
            ("OAVAV_2-06", "DOAS_22_1"), edges_by(result, "airRef"))

    def test_extrapolation_can_be_disabled(self):
        result = fuse_evidence([
            row("linked_widget_doas", "OAVAV_02_01", "DOAS_22_1"),
            row("linked_widget_doas", "OAVAV_02_09", "DOAS_22_1"),
            row("linked_widget_oavav", "FCU_02_3", "OAVAV_02_06"),
        ], extrapolate_oavav_doas=False)
        self.assertNotIn(("OAVAV_2-06", "DOAS_22_1"), edges_by(result, "airRef"))

    def test_valve_points_make_plant_edges(self):
        result = fuse_evidence([
            row("valve_points", "AHU 02 A", "CHW+WW"),
            row("valve_points", "FCU_02_3", "CHW+WW"),
        ])
        chw = edges_by(result, "chilledWaterRef")
        hot = edges_by(result, "hotWaterRef")
        self.assertEqual(chw[("AHU_2-A", "CHW-PLANT_1")]["confidence"], CONF_VALVE_AHU)
        self.assertEqual(hot[("FCU_2-03", "HW-PLANT_1")]["confidence"], CONF_VALVE_TERMINAL)

    def test_unresolved_type_routes_to_review(self):
        # the API pass once misread OAVAV as QAVAV; normalization must flag it
        result = fuse_evidence([
            row("linked_widget_doas", "QAVAV_02_01", "DOAS_22_1"),
        ])
        (edge,) = result.edges
        self.assertTrue(edge["review_required"])
        self.assertIn("unrecognized raw type", edge["review_reason"])

    def test_no_link_rows_become_review_notes(self):
        result = fuse_evidence([
            row("no_oa_link", "FCU_02_6", detail="no OAVAV widget; unlinked MA Temp"),
        ])
        self.assertEqual(result.edges, [])
        self.assertEqual(result.review_notes[0]["item"], "FCU_02_6")


class TilingMergeTests(unittest.TestCase):
    def test_merge_adds_and_dedups(self):
        result = fuse_evidence([
            row("linked_widget_ahu", "VAV_2_01", "AHU 02 A", "live_synced"),
        ])
        tiling_doc = {"relationships": [
            {"child": "VAVRH_2_1", "parent": "AHU_02A", "ref_type": "airRef",
             "confidence": 0.6, "conflict": True,
             "conflict_reason": "AHU tag ambiguous on sheet",
             "source_drawing": "Floor_2A.pdf"},
            {"child": "VAV_2_01", "parent": "AHU_02A", "ref_type": "airRef",
             "confidence": 0.5},
        ]}
        merge_tiling_edges(result, tiling_doc)
        air = edges_by(result, "airRef")
        merged = air[("VAV-RH-HW_2-01", "AHU_2-A")]
        self.assertTrue(merged["conflict"])
        self.assertTrue(merged["review_required"])
        # the graphics edge for VAV_2_01 wins; the weaker tiling duplicate is dropped
        self.assertEqual(air[("VAV_2-01", "AHU_2-A")]["confidence"], CONF_LIVE)
        self.assertEqual(len(air), 2)


class ExtractionHarnessTests(unittest.TestCase):
    def test_failures_are_preserved_not_repaired(self):
        def broken(_path):
            raise ValueError("boom")

        rows = extract_evidence([Path("a.png")], broken)
        self.assertEqual(rows[0].evidence_kind, "parse_failure")
        self.assertEqual(rows[0].page_title, "EXTRACTION_FAILED")

    def test_snapshot_document_shape(self):
        result = fuse_evidence([
            row("linked_widget_ahu", "VAV_2_01", "AHU 02 A", "live_synced"),
        ])
        document = build_snapshot_document(
            result, property_id="pid", property_name="pname", floor="Floor_02",
            snapshot_version="w06", model_id="test")
        self.assertEqual(document["relationship_count"], 1)
        self.assertEqual(document["prompt_version"], "relationship_graphics_v1")
        edge = document["relationships"][0]
        for key in ("child", "parent", "ref_type", "confidence", "conflict",
                    "conflict_reason", "review_required", "source_drawing"):
            self.assertIn(key, edge)


if __name__ == "__main__":
    unittest.main()
