#!/usr/bin/env python3
from __future__ import annotations

"""Publish at most one verified 2026 top-venue MOT paper per run."""

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

from clients.arxiv_client import has_multi_object_tracking_signal
from clients.github_ops import load_existing_arxiv_ids, upsert_repo_file
import daily_digest_llm_upgrade
from paper_processor import process_paper
from pipeline_config import get_repo, install_urllib_proxy, load_config
from services.issue_index import ensure_index, save_index, update_index_from_issue
import sync_daily_reports_to_repo


CONFIG = load_config()
install_urllib_proxy()
BEIJING_TZ = timezone(timedelta(hours=8))
QUEUE_PATH = "papers/top_venue_queue_2026.json"
VENUE_CONFIG_PATH = CONFIG.root_dir / "scripts" / "config" / "top_venues_2026.json"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
S2_FIELDS = "title,abstract,venue,year,publicationDate,externalIds,url,openAccessPdf,citationCount"
DEFAULT_DISCOVERY_MAX_PAGES = 2
DEFAULT_DISCOVERY_TARGET = 40


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def load_venue_config() -> dict:
    return json.loads(VENUE_CONFIG_PATH.read_text(encoding="utf-8"))


def canonical_venue(raw_venue: str, venues: dict[str, list[str]]) -> str | None:
    normalized = _normalize(raw_venue)
    if not normalized:
        return None
    for canonical, aliases in venues.items():
        for alias in aliases:
            needle = _normalize(alias)
            if canonical == "PR" and normalized == needle:
                return canonical
            if canonical == "PR" or not needle:
                continue
            is_acronym = " " not in needle and len(needle) <= 8
            acronym_match = is_acronym and re.search(rf"(?:^| ){re.escape(needle)}(?: |$)", normalized)
            full_name_match = (
                normalized == needle
                or normalized.endswith(f" {needle}")
                or re.search(rf"(?:^| ){re.escape(needle)} (?:print|online)$", normalized)
            )
            if acronym_match or full_name_match:
                return canonical
    return None


def extract_arxiv_id(item: dict) -> str | None:
    external_ids = item.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv")
    if arxiv_id:
        return str(arxiv_id).strip()
    dblp_id = str(external_ids.get("DBLP") or "")
    match = re.search(r"abs-(\d{4}-\d{4,5})", dblp_id)
    if match:
        return match.group(1).replace("-", ".", 1)
    doi = str(external_ids.get("DOI") or "")
    match = re.fullmatch(r"10\.48550/arXiv\.(.+)", doi, re.IGNORECASE)
    return match.group(1) if match else None


def candidate_id(item: dict) -> str:
    arxiv_id = extract_arxiv_id(item)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    external_ids = item.get("externalIds") or {}
    doi = str(external_ids.get("DOI") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    return f"s2:{item.get('paperId') or ''}"


def is_mot_candidate(item: dict) -> bool:
    title = item.get("title") or ""
    abstract = item.get("abstract") or ""
    return has_multi_object_tracking_signal(f"{title}\n{abstract}")


def _fetch_json(params: dict[str, str], retries: int = 3) -> dict:
    url = f"{S2_API}?{urllib.parse.urlencode(params)}"
    backoff = [10, 30, 60]
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": CONFIG.arxiv_user_agent})
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                break
        except Exception as exc:
            last_error = exc
            if attempt == retries - 1:
                break
        time.sleep(backoff[attempt])
    raise RuntimeError(f"Semantic Scholar request failed: {last_error}")


def discover_candidates(config: dict) -> list[dict]:
    discovered: dict[str, dict] = {}
    max_pages = max(1, int(config.get("discovery_max_pages", DEFAULT_DISCOVERY_MAX_PAGES)))
    target_count = max(1, int(config.get("discovery_target", DEFAULT_DISCOVERY_TARGET)))
    for query in config["queries"]:
        token = ""
        for page in range(max_pages):
            params = {
                "query": f'"{query}"',
                "year": str(config["year"]),
                "fields": S2_FIELDS,
                "sort": "publicationDate:desc",
            }
            if token:
                params["token"] = token
            payload = _fetch_json(params)
            for item in payload.get("data") or []:
                venue = canonical_venue(item.get("venue") or "", config["venues"])
                arxiv_id = extract_arxiv_id(item)
                pdf_url = str((item.get("openAccessPdf") or {}).get("url") or "")
                if item.get("year") != config["year"] or venue is None or not (arxiv_id or pdf_url):
                    continue
                if not is_mot_candidate(item):
                    continue
                key = candidate_id(item)
                discovered[key] = {
                    "candidate_id": key,
                    "arxiv_id": arxiv_id or "",
                    "pdf_url": pdf_url,
                    "title": item.get("title") or "Unknown",
                    "venue": venue,
                    "venue_raw": item.get("venue") or "",
                    "year": item.get("year"),
                    "publication_date": item.get("publicationDate") or "",
                    "doi": (item.get("externalIds") or {}).get("DOI") or "",
                    "semantic_scholar_url": item.get("url") or "",
                    "citation_count": item.get("citationCount") or 0,
                    "status": "pending",
                }
            if len(discovered) >= target_count:
                return list(discovered.values())
            token = str(payload.get("token") or "")
            if not token:
                break
            print(f"DISCOVERY_PAGE query={query!r} page={page + 2}")
            time.sleep(1)
        time.sleep(1)
    return list(discovered.values())


def load_queue(repo) -> dict:
    try:
        content = repo.get_contents(QUEUE_PATH)
        data = json.loads(content.decoded_content.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def merge_queue(queue: dict, discovered: list[dict], config: dict) -> dict:
    old_items = {
        item.get("candidate_id") or f"arxiv:{item.get('arxiv_id')}": item
        for item in queue.get("items") or []
        if item.get("candidate_id") or item.get("arxiv_id")
    }
    for item in discovered:
        previous = old_items.get(item["candidate_id"], {})
        old_items[item["candidate_id"]] = {**item, **previous}
    return {
        "year": config["year"],
        "venues": list(config["venues"].keys()),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": sorted(
            old_items.values(),
            key=lambda item: (
                item.get("status") != "pending",
                -(item.get("citation_count") or 0),
                item.get("publication_date") or "9999-99-99",
                item.get("title") or "",
            ),
        ),
    }


def backfill_link_only_dates(queue: dict) -> None:
    """Migrate link-only records created before failed_on was introduced."""
    updated_at = str(queue.get("updated_at") or "")
    try:
        queue_date = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).astimezone(BEIJING_TZ).strftime("%Y%m%d")
    except (TypeError, ValueError):
        queue_date = ""
    if not queue_date:
        return
    for item in queue.get("items") or []:
        if item.get("status") == "link_only" and not item.get("failed_on"):
            item["failed_on"] = queue_date


def link_only_for_date(queue: dict, date_str: str) -> list[dict]:
    return [
        item.copy()
        for item in queue.get("items") or []
        if item.get("status") == "link_only" and item.get("failed_on") == date_str
    ]


def save_queue(repo, queue: dict) -> None:
    body = json.dumps(queue, ensure_ascii=False, indent=2) + "\n"
    upsert_repo_file(repo, QUEUE_PATH, body, "refresh 2026 top venue MOT queue")


def choose_candidate(queue: dict, existing_ids: set[str], attempted: set[str] | None = None) -> dict | None:
    attempted = attempted or set()
    for item in queue.get("items") or []:
        if item.get("arxiv_id") and item.get("arxiv_id") in existing_ids:
            item["status"] = "published"
            continue
        if item.get("candidate_id") in attempted:
            continue
        if item.get("status") in {None, "pending", "retry"}:
            return item
    return None


def already_published_today(repo, date_str: str) -> bool:
    for issue in repo.get_issues(state="all", labels=[date_str]):
        if "日报" in (issue.title or ""):
            continue
        if re.search(r"\| \*\*Venue\*\* \|\s*(?!-)\S", issue.body or ""):
            print(f"ALREADY_PUBLISHED_TODAY issue=#{issue.number}")
            return True
    return False


def _failed_item(candidate: dict) -> dict:
    return {
        "title": candidate.get("title") or "Unknown",
        "arxiv_id": candidate.get("arxiv_id") or "",
        "venue": candidate.get("venue") or "-",
        "doi": candidate.get("doi") or "",
        "source_url": candidate.get("semantic_scholar_url") or "",
        "pdf_url": candidate.get("pdf_url") or "",
        "error": candidate.get("last_error") or "公开 PDF 暂不可获取",
    }


def _write_stats(
    today: str,
    candidate_count: int,
    issue_numbers: list[int],
    failed_items: list[dict],
    arxiv_ids: list[str] | None = None,
) -> Path:
    stats_path = CONFIG.memory_dir / f"top_venue_stats_{today}.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(
        json.dumps(
            {
                "date": today,
                "candidate_count": candidate_count,
                "llm_selected_count": candidate_count,
                "successful_selected_arxiv_ids": arxiv_ids or [],
                "successful_issue_numbers": issue_numbers,
                "failed_items": failed_items,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return stats_path


def _publish_digest(repo, today: str, stats_path: Path | None = None) -> None:
    daily_digest_llm_upgrade.main(
        target_date=today,
        stats_json=str(stats_path) if stats_path else None,
    )
    for attempt in range(3):
        sync_daily_reports_to_repo.main()
        try:
            repo.get_contents(f"daily_reports/{today[:6]}/{today}.md")
            return
        except Exception:
            if attempt < 2:
                time.sleep(6)


def _digest_exists(repo, today: str) -> bool:
    return any((issue.title or "").strip() == f"日报 {today}" for issue in repo.get_issues(state="open"))


def main(refresh: bool = True) -> int:
    if not CONFIG.github_token:
        raise RuntimeError("Missing required environment variable: GITHUB_TOKEN")
    if not CONFIG.llm_api_key:
        raise RuntimeError("Missing required environment variable: LLM_API_KEY")

    repo = get_repo(CONFIG)
    config = load_venue_config()
    today = datetime.now(BEIJING_TZ).strftime("%Y%m%d")
    if already_published_today(repo, today):
        if not _digest_exists(repo, today):
            print("MISSING_TODAY_DIGEST rebuilding")
            _publish_digest(repo, today)
        return 0

    queue = load_queue(repo)
    backfill_link_only_dates(queue)
    if refresh:
        try:
            discovered = discover_candidates(config)
            print(f"DISCOVERED eligible_candidates={len(discovered)}")
            queue = merge_queue(queue, discovered, config)
        except Exception as exc:
            print(f"DISCOVERY_WARNING {exc}; using cached queue")

    existing_ids = load_existing_arxiv_ids(repo)
    attempted: set[str] = set()
    failures: list[str] = []
    processing_failures: list[str] = []
    result = None
    candidate = None
    while True:
        candidate = choose_candidate(queue, existing_ids, attempted)
        if candidate is None:
            save_queue(repo, queue or merge_queue({}, [], config))
            today_link_only = link_only_for_date(queue, today)
            if processing_failures:
                raise RuntimeError("paper processing failed: " + " | ".join(processing_failures))
            failed_items = [_failed_item(item) for item in today_link_only]
            stats_path = _write_stats(today, len(today_link_only), [], failed_items)
            _publish_digest(repo, today, stats_path)
            if failures:
                print("NO_PROCESSABLE_FULLTEXT " + " | ".join(failures))
                return 0
            print("NO_ELIGIBLE_TOP_VENUE_PAPER")
            return 0

        attempted.add(candidate["candidate_id"])
        print(
            f"SELECTED {candidate['candidate_id']} | {candidate['venue']} {candidate['year']} | "
            f"{candidate['title']}"
        )
        result, error = process_paper(
            candidate.get("arxiv_id") or candidate["candidate_id"],
            target_date=today,
            publication={
                "venue": candidate["venue"],
                "year": candidate["year"],
                "doi": candidate.get("doi") or "",
                "source_url": candidate.get("semantic_scholar_url") or "",
                "pdf_url": candidate.get("pdf_url") or "",
                "title": candidate.get("title") or "",
            },
        )
        if result is not None:
            break

        is_download_failure = (error or "").startswith("PDF 下载失败")
        candidate["status"] = "link_only" if is_download_failure else "retry"
        candidate["last_error"] = error or "unknown error"
        if is_download_failure:
            candidate["failed_on"] = today
        failure = f"{candidate['candidate_id']}: {candidate['last_error']}"
        failures.append(failure)
        if not is_download_failure:
            processing_failures.append(failure)
        print(f"SKIP_FAILED {failure}")
        save_queue(repo, queue)

    candidate["status"] = "published"
    candidate["issue_number"] = result.number
    candidate["published_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    candidate.pop("last_error", None)
    candidate.pop("failed_on", None)
    index = ensure_index(repo)
    if candidate.get("arxiv_id"):
        update_index_from_issue(index, candidate["arxiv_id"], result)
    save_index(repo, index)
    save_queue(repo, queue)
    time.sleep(4)
    successful_arxiv_ids = [candidate["arxiv_id"]] if candidate.get("arxiv_id") else []
    today_link_only = link_only_for_date(queue, today)
    failed_items = [_failed_item(item) for item in today_link_only]
    stats_path = _write_stats(
        today,
        1 + len(today_link_only),
        [result.number],
        failed_items,
        successful_arxiv_ids,
    )
    _publish_digest(repo, today, stats_path)
    print(f"PUBLISHED issue=#{result.number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
