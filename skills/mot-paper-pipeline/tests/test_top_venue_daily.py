from __future__ import annotations

import sys
import unittest
from unittest.mock import patch
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from top_venue_daily import (
    already_published_today,
    build_unavailable_fulltext_report,
    canonical_venue,
    choose_candidate,
    extract_arxiv_id,
    is_mot_candidate,
)
from paper_processor import _curl_fetch, _download_public_pdf, _extract_pdf_links


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

    def test_skips_candidate_already_attempted_in_same_run(self):
        queue = {
            "items": [
                {"candidate_id": "doi:first", "status": "retry"},
                {"candidate_id": "doi:second", "status": "pending"},
            ]
        }
        chosen = choose_candidate(queue, set(), {"doi:first"})
        self.assertEqual(chosen["candidate_id"], "doi:second")

    def test_skips_link_only_candidate_on_later_runs(self):
        queue = {
            "items": [
                {"candidate_id": "doi:blocked", "status": "link_only"},
                {"candidate_id": "doi:available", "status": "pending"},
            ]
        }

        chosen = choose_candidate(queue, set())

        self.assertEqual(chosen["candidate_id"], "doi:available")

    def test_extracts_ojs_pdf_link(self):
        html = b'<a href="https://ojs.aaai.org/index.php/AAAI/article/view/42500/46461">PDF</a>'
        self.assertEqual(
            _extract_pdf_links(html, "https://ojs.aaai.org/index.php/AAAI/article/view/42500"),
            ["https://ojs.aaai.org/index.php/AAAI/article/view/42500/46461"],
        )

    @patch("paper_processor._request_bytes")
    @patch("paper_processor._curl_fetch")
    def test_download_follows_pdf_link_from_curl_html(self, curl_fetch, request_bytes):
        request_bytes.side_effect = RuntimeError("blocked")
        curl_fetch.side_effect = [
            (b'<a href="/paper.pdf">PDF</a>', "https://example.test/article"),
            (b"%PDF-1.7\nexample", "https://example.test/paper.pdf"),
        ]
        path, resolved = _download_public_pdf("https://example.test/article", "doi:test")
        self.assertIsNotNone(path)
        self.assertEqual(resolved, "https://example.test/paper.pdf")
        path.unlink()

    @patch("paper_processor.subprocess.run")
    def test_curl_download_forces_http_1_1(self, run):
        run.return_value.stdout = b"%PDF-1.7\nexample\nhttps://example.test/paper.pdf"
        data, resolved = _curl_fetch("https://example.test/paper.pdf")

        command = run.call_args.args[0]
        self.assertIn("--http1.1", command)
        self.assertEqual(data, b"%PDF-1.7\nexample")
        self.assertEqual(resolved, "https://example.test/paper.pdf")

    def test_builds_link_only_report_without_claiming_analysis(self):
        report = build_unavailable_fulltext_report(
            "20260813",
            [
                {
                    "title": "A MOT Paper",
                    "venue": "AAAI",
                    "year": 2026,
                    "doi": "10.1609/test",
                    "semantic_scholar_url": "https://example.test/paper",
                    "pdf_url": "https://example.test/paper.pdf",
                }
            ],
        )

        self.assertIn("[DOI](https://doi.org/10.1609/test)", report)
        self.assertIn("[公开 PDF](https://example.test/paper.pdf)", report)
        self.assertIn("未解读", report)
        self.assertIn("`link_only`", report)

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
