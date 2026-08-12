from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from top_venue_daily import (
    already_published_today,
    canonical_venue,
    choose_candidate,
    extract_arxiv_id,
    is_mot_candidate,
)


VENUES = {
    "CVPR": ["computer vision and pattern recognition", "cvpr"],
    "ICCV": ["international conference on computer vision", "iccv"],
    "TIP": ["transactions on image processing", "tip"],
    "PR": ["pattern recognition"],
}


class TopVenueDailyTest(unittest.TestCase):
    def test_canonicalizes_full_venue_names(self):
        self.assertEqual(
            canonical_venue(
                "IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
                VENUES,
            ),
            "CVPR",
        )
        self.assertEqual(canonical_venue("IEEE Transactions on Image Processing", VENUES), "TIP")

    def test_pattern_recognition_requires_exact_journal_name(self):
        self.assertEqual(canonical_venue("Pattern Recognition", VENUES), "PR")
        self.assertIsNone(canonical_venue("International Journal of Pattern Recognition", VENUES))

    def test_does_not_confuse_visapp_with_iccv(self):
        self.assertIsNone(
            canonical_venue(
                "International Conference on Computer Vision Theory and Applications",
                VENUES,
            )
        )

    def test_extracts_arxiv_id_from_supported_external_ids(self):
        self.assertEqual(extract_arxiv_id({"externalIds": {"ArXiv": "2601.12345"}}), "2601.12345")
        self.assertEqual(
            extract_arxiv_id({"externalIds": {"DBLP": "journals/corr/abs-2602-05037"}}),
            "2602.05037",
        )

    def test_requires_explicit_mot_signal(self):
        self.assertTrue(
            is_mot_candidate(
                {
                    "title": "Robust Multi-Object Tracking",
                    "abstract": "Identity association under occlusion.",
                }
            )
        )
        self.assertFalse(
            is_mot_candidate(
                {
                    "title": "Object Detection in Images",
                    "abstract": "A detector for static images.",
                }
            )
        )

    def test_selects_only_first_unpublished_candidate(self):
        queue = {
            "items": [
                {"arxiv_id": "2601.00001", "status": "pending"},
                {"arxiv_id": "2601.00002", "status": "pending"},
            ]
        }
        chosen = choose_candidate(queue, {"2601.00001"})
        self.assertEqual(chosen["arxiv_id"], "2601.00002")
        self.assertEqual(queue["items"][0]["status"], "published")

    def test_detects_top_venue_paper_already_published_today(self):
        class Repo:
            def get_issues(self, **kwargs):
                return [
                    type(
                        "Issue",
                        (),
                        {
                            "number": 7,
                            "title": "[20260812] MOT paper",
                            "body": "| **Venue** | CVPR |",
                        },
                    )()
                ]

        self.assertTrue(already_published_today(Repo(), "20260812"))


if __name__ == "__main__":
    unittest.main()
