from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clients.github_ops import upsert_repo_file


class FakeGithubError(Exception):
    def __init__(self, status: int):
        super().__init__(f"GitHub status {status}")
        self.status = status


class Content:
    def __init__(self, text: str, sha: str):
        self.decoded_content = text.encode("utf-8")
        self.sha = sha


class GithubOpsTest(unittest.TestCase):
    @patch("clients.github_ops.time.sleep")
    def test_reloads_sha_after_update_conflict(self, _sleep):
        class Repo:
            def __init__(self):
                self.reads = 0
                self.updated_shas = []
                self.created = False

            def get_contents(self, _path):
                self.reads += 1
                return Content("old", f"sha-{self.reads}")

            def update_file(self, **kwargs):
                self.updated_shas.append(kwargs["sha"])
                if len(self.updated_shas) == 1:
                    raise FakeGithubError(422)

            def create_file(self, **_kwargs):
                self.created = True

        repo = Repo()
        upsert_repo_file(repo, "queue.json", "new", "update queue")

        self.assertEqual(repo.updated_shas, ["sha-1", "sha-2"])
        self.assertFalse(repo.created)

    def test_creates_only_when_get_returns_404(self):
        class Repo:
            def __init__(self):
                self.created = False

            def get_contents(self, _path):
                raise FakeGithubError(404)

            def create_file(self, **_kwargs):
                self.created = True

        repo = Repo()
        upsert_repo_file(repo, "new.json", "{}", "create")
        self.assertTrue(repo.created)

    def test_does_not_create_after_non_404_read_error(self):
        class Repo:
            def __init__(self):
                self.created = False

            def get_contents(self, _path):
                raise FakeGithubError(403)

            def create_file(self, **_kwargs):
                self.created = True

        repo = Repo()
        with self.assertRaises(FakeGithubError):
            upsert_repo_file(repo, "queue.json", "{}", "update")
        self.assertFalse(repo.created)


if __name__ == "__main__":
    unittest.main()
