#!/usr/bin/env python3
from __future__ import annotations

import json
import re

from clients.llm_client import call_llm
from services.paper_analysis import is_valid_institution_text


def extract_author(body: str) -> str:
    match = re.search(r"\| \*\*作者\*\* \|([^|]+)\|", body or "")
    return match.group(1).strip() if match else "-"


def extract_institution(body: str) -> str:
    match = re.search(r"\| \*\*(?:单位|机构)\*\* \|([^|]+)\|", body or "")
    return match.group(1).strip() if match else "-"


def is_invalid_digest_field(value: str) -> bool:
    normalized = (value or "").strip()
    return normalized in {"", "-", "待提取", "未知", "Unknown", "N/A"}


def is_invalid_digest_institution(value: str) -> bool:
    return not is_valid_institution_text(value)


def validate_papers_for_digest(papers: list[dict]) -> list[str]:
    errors: list[str] = []
    for paper in papers:
        title = extract_report_title(paper)
        authors = extract_author(paper.get("body") or "")
        institution = extract_institution(paper.get("body") or "")
        if is_invalid_digest_field(authors) or "et al." in authors:
            errors.append(f"{title}: 作者信息不合格")
        if is_invalid_digest_institution(institution):
            errors.append(f"{title}: 单位信息不合格")
    return errors


def extract_report_title(issue: dict) -> str:
    body = issue.get("body") or ""
    match = re.search(r"^#\s*\[(\d{8})\]\s+(.+)$", body, re.MULTILINE)
    if match:
        return f"[{match.group(1)}] {match.group(2).strip()}"
    return issue.get("title") or ""


def extract_paper_date(issue: dict) -> str | None:
    for label in issue.get("labels", []):
        name = label.get("name", "") if isinstance(label, dict) else ""
        if re.fullmatch(r"\d{8}", name):
            return name

    body = issue.get("body") or ""
    body_match = re.search(r"\[(\d{8})\]", body)
    if body_match:
        return body_match.group(1)

    title_match = re.match(r"^\[(\d{8})\]\s+", issue.get("title") or "")
    return title_match.group(1) if title_match else None


def build_digest_with_llm(date: str, papers: list, stats: dict | None = None, failed_items: list[dict] | None = None) -> str:
    items = []
    for i, paper in enumerate(papers, 1):
        labels = [label["name"] for label in paper.get("labels", []) if label["name"] not in [date, "日报"]]
        items.append(
            {
                "idx": i,
                "issue": paper["number"],
                "title": extract_report_title(paper),
                "authors": extract_author(paper.get("body") or ""),
                "institution": extract_institution(paper.get("body") or ""),
                "labels": labels,
                "url": paper["html_url"],
            }
        )

    if not items:
        candidate_count = (stats or {}).get("candidate_count", 0)
        llm_selected_count = (stats or {}).get("llm_selected_count", len(failed_items or []))
        overview_text = (
            f"今日共检索候选论文 {candidate_count} 篇；"
            f"关键词+LLM 智能匹配 MOT 论文 {llm_selected_count} 篇；"
            "最终纳入日报 0 篇。\n\n"
        )
        if llm_selected_count:
            overview_text += "当日筛中论文均未通过处理或质检，未纳入日报。"
        else:
            overview_text += "当日未检索到符合条件并纳入日报的论文。"

        lines = [f"# 日报 {date}", "", "## 📌 今日概况", "", overview_text, ""]
        append_failed_items(lines, failed_items)
        if failed_items:
            observations = [
                "- 当日候选符合 MOT 与 venue 条件，但没有可供可靠深度解读的全文。",
                "- 系统已保留来源链接，等待开放 PDF、arXiv 版本或后续人工补充全文。",
            ]
        else:
            observations = [
                "- 当日未发现可纳入的 2026 顶会顶刊 MOT 论文。",
                "- 若连续出现空日报，应复核候选来源、venue 元数据和 MOT 筛选条件。",
            ]
        lines += ["## 🔎 观察", "", *observations, "", "---", "", "Powered by OpenClaw🦞"]
        return "\n".join(lines)

    prompt = (
        "你是多目标跟踪论文日报编辑。请基于给定论文列表输出严格JSON：\n"
        "{\n"
        '  "overview": "120-180字，概述今日研究趋势",\n'
        '  "highlights": ["3条，每条20-40字"],\n'
        '  "one_liners": [{"idx":1,"summary":"每篇一句话，25-45字"}],\n'
        '  "observations": ["2条，偏分析判断，每条24-48字"]\n'
        "}\n"
        "要求：中文、客观、不要编造细节；优先总结跟踪范式、数据关联、遮挡处理、数据集与 HOTA/IDF1/MOTA 等指标趋势。\n\n"
        f"日期: {date}\n候选: {json.dumps(items, ensure_ascii=False)}"
    )
    output = call_llm(prompt, max_tokens=1800, timeout=240)
    match = re.search(r"\{[\s\S]*\}", output)
    data = {"overview": "", "highlights": [], "one_liners": []}
    if match:
        try:
            data = json.loads(match.group(0))
        except Exception:
            pass

    one_liners = {
        item.get("idx"): item.get("summary", "")
        for item in data.get("one_liners", [])
        if isinstance(item, dict)
    }

    overview_text = data.get("overview") or "今日论文围绕多目标跟踪的数据关联、运动建模与身份保持展开。"
    candidate_count = (stats or {}).get("candidate_count")
    llm_selected_count = (stats or {}).get("llm_selected_count")
    included_count = len(items)

    if candidate_count is None:
        candidate_count = included_count
    if llm_selected_count is None:
        llm_selected_count = included_count

    overview_text = (
        f"今日共检索候选论文 {candidate_count} 篇；"
        f"关键词+LLM 智能匹配 MOT 论文 {llm_selected_count} 篇；"
        f"最终纳入日报 {included_count} 篇。\n\n{overview_text}"
    )

    lines = [f"# 日报 {date}", "", "## 📌 今日概况", "", overview_text, ""]

    highlights = data.get("highlights") or []
    if highlights:
        lines += ["## ✨ 今日亮点", ""]
        for highlight in highlights[:3]:
            lines.append(f"- {highlight}")
        lines.append("")

    lines += ["## 🗂 今日文章列表", "", "| 标题 | 作者 | 单位 | 一句话概括 | Issue |", "|---|---|---|---|---|"]
    for i, paper in enumerate(items, 1):
        summary = one_liners.get(i) or (
            f"聚焦{('、'.join(paper['labels'][:2]) if paper['labels'] else '多目标跟踪')}，给出可复现的关联方法与评测方案。"
        )
        lines.append(
            f"| {paper['title']} | {paper['authors']} | {paper['institution']} | {summary} | [#{paper['issue']}]({paper['url']}) |"
        )

    append_failed_items(lines, failed_items)

    observations = data.get("observations") or [
        "数据关联与长时遮挡后的身份恢复仍是 MOT 的主要差异化方向。",
        "建议结合 HOTA、IDF1、MOTA 与推理速度评估准确性和工程可用性。",
    ]
    lines += ["", "## 🔎 观察", ""]
    for observation in observations[:2]:
        lines.append(f"- {observation}")

    lines += ["", "---", "", "Powered by OpenClaw🦞"]
    return "\n".join(lines)


def append_failed_items(lines: list[str], failed_items: list[dict] | None) -> None:
    if not failed_items:
        return

    lines += ["", "## ⚠️ 未纳入日报的匹配论文", ""]
    lines.append("以下论文通过筛选，但因全文不可用或处理失败而未纳入深度解读。可通过来源链接查看原始记录。")
    lines.append("")
    lines.append("| 标题 | Venue | 来源链接 | 未纳入原因 |")
    lines.append("|------|-------|----------|------------|")
    for item in failed_items:
        title = item.get("title", "Unknown")
        aid = item.get("arxiv_id", "")
        error = item.get("error") or item.get("reason") or "未知"
        venue = item.get("venue") or "-"
        links: list[str] = []
        if aid:
            links.append(f"[arXiv](https://arxiv.org/abs/{aid})")
        doi = str(item.get("doi") or "").strip()
        if doi:
            links.append(f"[DOI](https://doi.org/{doi})")
        source_url = str(item.get("source_url") or item.get("semantic_scholar_url") or "").strip()
        if source_url:
            links.append(f"[Semantic Scholar]({source_url})")
        pdf_url = str(item.get("pdf_url") or "").strip()
        if pdf_url:
            links.append(f"[公开 PDF]({pdf_url})")
        lines.append(f"| {title} | {venue} | {' · '.join(links) or '-'} | {error} |")
    lines.append("")
