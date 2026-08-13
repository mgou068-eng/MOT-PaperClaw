#!/usr/bin/env python3
from __future__ import annotations

import re
import time

from pipeline_config import load_config


CONFIG = load_config()


def extract_arxiv_id_from_text(text: str) -> str | None:
    match = re.search(r"arxiv\.org/abs/([^\)\s]+)", text or "")
    return match.group(1).strip() if match else None


def extract_arxiv_id_from_issue(issue) -> str | None:
    return extract_arxiv_id_from_text(issue.body or "")


def get_today_digest_issue(repo, date_str: str):
    title = f"日报 {date_str}"
    for issue in repo.get_issues(state="open"):
        if issue.title.strip() == title:
            return issue
    return None


def daily_report_file_exists(repo, date_str: str) -> bool:
    ym = date_str[:6]
    path = f"daily_reports/{ym}/{date_str}.md"
    try:
        repo.get_contents(path)
        return True
    except Exception:
        return False


def load_existing_arxiv_ids(repo) -> set[str]:
    from services.issue_index import ensure_index
    index = ensure_index(repo)
    return set(index.keys())


def _github_status(exc: Exception) -> int | None:
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def upsert_repo_file(repo, path: str, content: str, message: str, retries: int = 4) -> None:
    data = content.encode("utf-8")
    for attempt in range(retries):
        try:
            existing = repo.get_contents(path)
        except Exception as exc:
            if _github_status(exc) != 404:
                raise
            try:
                repo.create_file(path=path, message=message, content=data)
                print(f"CREATED {path}")
                return
            except Exception as create_exc:
                if _github_status(create_exc) not in {409, 422} or attempt == retries - 1:
                    raise
                time.sleep(attempt + 1)
                continue

        existing_text = existing.decoded_content.decode("utf-8")
        if existing_text == content:
            print(f"UNCHANGED {path}")
            return
        try:
            repo.update_file(path=path, message=message, content=data, sha=existing.sha)
            print(f"UPDATED {path}")
            return
        except Exception as exc:
            if _github_status(exc) not in {409, 422} or attempt == retries - 1:
                raise
            time.sleep(attempt + 1)

    raise RuntimeError(f"failed to update {path} after {retries} attempts")


def cleanup_legacy_daily_reports(repo, base_dir: str = "daily_reports") -> None:
    try:
        entries = repo.get_contents(base_dir)
    except Exception:
        return

    for entry in entries:
        if entry.type == "file" and re.fullmatch(r"\d{8}\.md", entry.name):
            repo.delete_file(
                path=entry.path,
                message=f"cleanup legacy daily report file {entry.name}",
                sha=entry.sha,
            )
            print(f"DELETED {entry.path}")
