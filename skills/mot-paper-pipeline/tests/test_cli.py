from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cli


class PaperCommandTest(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(
            arxiv_id="2110.06864",
            issue_number=None,
            dry_run=False,
            output_dir=None,
        )

    def test_returns_failure_when_processing_fails(self):
        with patch.object(cli.paper_processor, "process_paper", return_value=(None, "download failed")):
            self.assertEqual(cli.paper_command(self.args), 1)

    def test_returns_success_for_created_issue(self):
        issue = SimpleNamespace(number=2)
        with patch.object(cli.paper_processor, "process_paper", return_value=(issue, None)):
            self.assertEqual(cli.paper_command(self.args), 0)


if __name__ == "__main__":
    unittest.main()
