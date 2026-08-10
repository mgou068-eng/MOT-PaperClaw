from pathlib import Path
from unittest.mock import patch
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clients.arxiv_client import has_multi_object_tracking_signal
from daily_arxiv_cross_filter import passes_mot_hard_gate
from pipeline_config import load_config
from services.filter_assets import load_filter_keywords, render_filter_prompt
from services.paper_analysis import extract_tags


class MotFilterTest(unittest.TestCase):
    def test_accepts_explicit_mot_phrases(self):
        positives = [
            "A transformer for multi-object tracking under long occlusion",
            "Multiple object trackers with learned data association",
            "LiDAR-based 3D multi-object tracking for autonomous driving",
            "Multi-camera tracking with cross-view identity association",
            "Joint detection and tracking of pedestrians in crowded videos",
            "A tracking-by-detection system for multiple pedestrians",
            "A MOT benchmark for tracking vehicles in traffic videos",
        ]
        for text in positives:
            with self.subTest(text=text):
                self.assertTrue(has_multi_object_tracking_signal(text))

    def test_rejects_neighboring_non_mot_tasks(self):
        negatives = [
            "Single-object tracking with a visual transformer",
            "Object detection in crowded street scenes",
            "Person re-identification with metric learning",
            "Visual SLAM for autonomous robots",
            "Multi-agent trajectory prediction in urban traffic",
            "The role of mot genes in cell migration",
            "Camera pose tracking from monocular video",
        ]
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(has_multi_object_tracking_signal(text))

    def test_hard_gate_rejects_sot_title_with_related_work_mot_mention(self):
        self.assertFalse(
            passes_mot_hard_gate(
                "Single-Object Tracking with Long-Term Memory",
                "We compare visual trackers with multi-object tracking baselines.",
            )
        )
        self.assertTrue(
            passes_mot_hard_gate(
                "Unified Single- and Multi-Object Tracking",
                "We evaluate identity association on MOT17.",
            )
        )

    @patch("services.paper_analysis.call_llm")
    def test_tags_are_deduplicated_and_limited_to_mot_taxonomy(self, call_llm):
        call_llm.return_value = (
            "3d mot, Multi-Object Tracking, Data Association, "
            "Made Up Label, Data Association"
        )

        self.assertEqual(
            extract_tags("Example", "Example abstract"),
            ["Multi-Object Tracking", "3D MOT", "Data Association"],
        )

    def test_filter_assets_have_mot_contract(self):
        config = load_filter_keywords()
        self.assertIn("multi-object tracking", config["mot_query_terms"])
        self.assertGreaterEqual(len(config["mot_signal_patterns"]), 8)
        prompt = render_filter_prompt(["[1] id=2607.12345 | title=Example MOT Paper"])
        self.assertIn("2607.12345", prompt)
        self.assertNotIn("{{candidate_lines}}", prompt)

    def test_mot_environment_names_override_legacy_aliases(self):
        env = {
            "MOT_GITHUB_REPO": "new-owner/MOT-PaperClaw",
            "RS_GITHUB_REPO": "legacy-owner/RS-PaperClaw",
            "MOT_TEMP_DIR": "/tmp/mot-paperclaw-test",
            "RS_TEMP_DIR": "/tmp/rs-paperclaw-test",
        }
        with patch.dict("os.environ", env, clear=False):
            config = load_config()

        self.assertEqual(config.github_repo, "new-owner/MOT-PaperClaw")
        self.assertEqual(config.temp_dir, Path("/tmp/mot-paperclaw-test"))


if __name__ == "__main__":
    unittest.main()
