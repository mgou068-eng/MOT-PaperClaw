#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import tarfile
import gzip
from pathlib import Path

from clients.llm_client import call_llm, load_prompt


def has_bad_placeholder(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return False

    def compact_value(value: str) -> str:
        return re.sub(r"[\s:：,，。.!！?？;；()（）\[\]【】\"'`]+", "", value).casefold()

    exact_placeholders = {
        "-",
        "--",
        "待提取",
        "未知",
        "分析中",
        "暂无",
        "无",
        "未提供",
        "未说明",
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "notprovided",
        "notavailable",
        "notspecified",
        "notmentioned",
    }
    compact = compact_value(normalized)
    if compact in exact_placeholders:
        return True

    field_prefix = re.match(
        r"(?i)^(?:title|author|authors|institution|institutions|affiliation|abstract|date|info|information)"
        r"\s*(?:is|are|:|：)?\s*(.+)$",
        normalized,
    )
    if field_prefix and compact_value(field_prefix.group(1)) in exact_placeholders:
        return True

    zh_prefix = re.match(r"^(?:标题|作者|单位|机构|摘要|日期|信息)\s*(?:[:：]|为|是)?\s*(.+)$", normalized)
    return bool(zh_prefix and compact_value(zh_prefix.group(1)) in exact_placeholders)


def dedupe_bullets(text: str) -> str:
    lines = (text or "").splitlines()
    seen = set()
    output = []
    for line in lines:
        normalized = re.sub(r"\s+", "", line.lower())
        if line.strip().startswith(("-", "*")):
            if normalized in seen:
                continue
            seen.add(normalized)
        output.append(line)
    return "\n".join(output)


def format_answer_md(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return stripped

    if any(token in stripped for token in ["\n- ", "\n* ", "\n1.", "\n##", "\n###", "**"]):
        stripped = re.sub(r"\n{3,}", "\n\n", stripped)
        return dedupe_bullets(stripped)

    parts = [part.strip() for part in re.split(r"[。；]\s*", stripped) if part.strip()]
    if len(parts) >= 2:
        return dedupe_bullets("\n".join([f"- {part}。" for part in parts]))

    return stripped


def normalize_mermaid_flowchart(text: str) -> str:
    """Keep only renderable Mermaid flowchart source returned by the LLM."""
    stripped = (text or "").strip()
    stripped = re.sub(r"^```(?:mermaid)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"(?im)^flowchart\s+(?:LR|TD|RL|BT)\b", stripped)
    if not match:
        return ""
    return stripped[match.start():].strip()


def normalize_glossary(text: str) -> str:
    """Normalize common bullet variants without inventing missing terms."""
    output: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```") or line.upper().startswith("GLOSSARY"):
            continue
        bullet = re.match(r"^(?:[-*•]|\d+[.)、])\s*(.+)$", line)
        if bullet:
            output.append(f"- {bullet.group(1).strip()}")
    return dedupe_bullets("\n".join(output))


def quality_gate(info: dict, analysis: dict, abstract_zh: str, uploaded_images: int) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not info.get("title") or has_bad_placeholder(info.get("title")):
        errors.append("标题为空或无效")
    if not info.get("authors") or has_bad_placeholder(info.get("authors")):
        errors.append("作者为空或无效")
    if not is_valid_institution_text(info.get("institutions", "")):
        errors.append("单位为空或无效")
    if not info.get("date"):
        errors.append("日期为空")
    if not abstract_zh or len(abstract_zh.strip()) < 20:
        errors.append("摘要为空或无效")
    if uploaded_images < 1:
        errors.append("图片数量不足（至少1张）")
    flowchart = normalize_mermaid_flowchart(analysis.get("flowchart", ""))
    if not flowchart or len(re.findall(r"-->", flowchart)) < 4:
        errors.append("方法流程图为空或节点不足")
    glossary = normalize_glossary(analysis.get("glossary", ""))
    if len(re.findall(r"^- ", glossary, flags=re.MULTILINE)) < 5:
        errors.append("关键术语不足（至少5项）")
    for i in range(1, 11):
        answer = analysis.get(f"q{i}", "")
        if not answer or has_bad_placeholder(answer):
            errors.append(f"Q{i} 未通过质检")
        elif i in {3, 4, 5, 6, 7} and len(answer.strip()) < 140:
            errors.append(f"Q{i} 实现说明过短")
    return len(errors) == 0, errors


def translate_text(text: str) -> str:
    if not text:
        return ""
    template = load_prompt("translate_prompt.md")
    return call_llm(template.replace("{content}", text), max_tokens=2000, timeout=60)


def extract_tags(title: str, abstract: str) -> list[str]:
    template = load_prompt("tags_prompt.md")
    prompt = template.replace("{title}", title).replace("{abstract}", abstract[:1000])
    result = call_llm(prompt, max_tokens=200, timeout=30)

    controlled_tags = (
        "Multi-Object Tracking",
        "2D MOT",
        "3D MOT",
        "Multi-Camera",
        "Online Tracking",
        "Offline Tracking",
        "End-to-End",
        "Tracking-by-Detection",
        "Data Association",
        "Re-Identification",
        "Motion Modeling",
        "Trajectory Reasoning",
        "Occlusion",
        "Open-Vocabulary",
        "Pedestrian Tracking",
        "Vehicle Tracking",
        "Aerial Tracking",
        "Cell Tracking",
        "Benchmark",
    )
    canonical = {tag.casefold(): tag for tag in controlled_tags}
    tags = ["Multi-Object Tracking"]
    for raw_tag in result.split(","):
        tag = canonical.get(raw_tag.strip().casefold())
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:6]


def generate_tldr(title: str, abstract_en: str) -> str:
    prompt = (
        "请为下面论文生成中文 TL;DR，仅1句，控制在50字以内，不要换行，不要项目符号，不要前缀。\n"
        f"标题：{title}\n"
        f"摘要：{abstract_en[:1200]}"
    )
    output = (call_llm(prompt, max_tokens=120, timeout=60) or "").strip()
    output = re.sub(r"\s+", " ", output)
    output = re.sub(r"^(TL;DR[:：]?\s*)", "", output, flags=re.IGNORECASE)
    return output or "面向多目标跟踪，改进时序关联与身份保持并完成实验验证。"


def _dedupe_institutions(institutions: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in institutions:
        text = re.sub(r"\s+", " ", item or "").strip(" ,;:，；：")
        if not text:
            continue
        if re.search(r"@", text):
            continue
        lowered = text.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(text)
    return cleaned


INSTITUTION_KEYWORD_PATTERN = re.compile(
    r"(universit|univ\b|college|school|institut|academy|laborator|centre|center|"
    r"department|hospital|faculty|laboratory|lab\b|research|hochschule|fraunhofer|"
    r"dlr\b|cnrs\b|enpc\b|国家|大学|学院|研究所|实验室|中心|医院)",
    re.IGNORECASE,
)


def _strip_email_tail(text: str) -> str:
    """Remove email lists that commonly follow affiliation text."""
    cleaned = re.split(
        r"\b(?:Correspondence|Corresponding author|E-?mail|Emails?)[:：]?\b",
        text or "",
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = re.split(
        r"\s+[A-Za-z0-9._%+-]*\.[A-Za-z0-9._%+-]*"
        r"(?:,\s*[A-Za-z0-9._%+-]*\.[A-Za-z0-9._%+-]*)*\s*@\s*\S+",
        cleaned,
        maxsplit=1,
    )[0]
    cleaned = re.split(r"\s+[A-Za-z0-9._%+-]+\s*@\s*\S+", cleaned, maxsplit=1)[0]
    return cleaned.strip(" ,;:，；：")


def is_valid_institution_text(text: str) -> bool:
    normalized = (text or "").strip()
    if normalized in {"", "-"} or has_bad_placeholder(normalized):
        return False

    # Affiliation extraction can occasionally bleed into the abstract/body when
    # PDF text columns are interleaved. Treat sentence-like research prose as
    # invalid so contaminated metadata is refreshed instead of entering reports.
    strong_prose_pattern = re.compile(
        r"\b("
        r"abstract|introduction|keywords?|while|whereas|however|therefore|"
        r"paper|propos(?:e|ed|es|ing)|method|approach|dataset|"
        r"experiments?|results?|capture|learn(?:ing)?|strategy|benchmark|supported|grants?|"
        r"tasks?|inference|applying|transformers?|tokens?|speeds?|impractical|"
        r"foundation|funds?|project|computational|constraints?|resources?"
        r")\b",
        re.IGNORECASE,
    )
    domain_prose_pattern = re.compile(
        r"\b(network|model|images?|pixels?|patch|patches|segmentation|"
        r"classification|detection|performance)\b",
        re.IGNORECASE,
    )
    for chunk in re.split(r"[；;]", normalized):
        part = re.sub(r"\s+", " ", chunk).strip(" ,;:，；：")
        if not part:
            continue
        if re.search(r"https?://|www\.|github\.com|arxiv\.org", part, re.IGNORECASE):
            return False
        if len(part) > 180:
            return False
        if strong_prose_pattern.search(part):
            return False
        if domain_prose_pattern.search(part) and not INSTITUTION_KEYWORD_PATTERN.search(part):
            return False
        if re.search(r"\.\s+[A-Z][a-z]+", part):
            return False
    return True


def _clean_institution_candidate(text: str) -> str:
    cleaned = _strip_email_tail(text or "")
    cleaned = re.split(
        r"\b(?:"
        r"project\s+page|source\s+code|code|homepage|website|"
        r"corresponding\s+author|these\s+authors\s+contributed|"
        r"this\s+work\s+was\s+supported|the\s+work\s+was\s+supported|"
        r"acknowledg(?:e)?ments?"
        r")\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = re.sub(r"^\s*(?:[•*\-]\s*)+", "", cleaned)
    cleaned = re.sub(r"^\s*(?:\$?\^?\\?dag(?:ger)?\$?\s*)+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:[\d*†‡§¶]+\s*)+", "", cleaned)
    cleaned = re.sub(r"(?<=\d)(?=[A-Z])", " ", cleaned)
    cleaned = re.sub(r"\s+([,;:.])", r"\1", cleaned)
    cleaned = re.sub(
        r"^(?:the\s+)(?=(?:department|state|qian|school|college|university|academy|laboratory|institute)\b)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" ,;:.，；：⋆•†‡§¶")


def _looks_like_institution_candidate(text: str) -> bool:
    cleaned = text or ""
    if not cleaned or re.search(r"@|https?://|www\.|github\.com|arxiv\.org", cleaned, re.IGNORECASE):
        return False
    if re.search(r"\b(?:project\s+page|github|corresponding\s+author)\b", cleaned, re.IGNORECASE):
        return False
    if not INSTITUTION_KEYWORD_PATTERN.search(cleaned):
        return False
    return is_valid_institution_text(cleaned)


def _append_institution_candidate(institutions: list[str], text: str) -> None:
    cleaned = _clean_institution_candidate(text)
    if _looks_like_institution_candidate(cleaned):
        institutions.append(cleaned)


def _heuristic_institutions(first_page_text: str) -> list[str]:
    parsed_ieee = _parse_ieee_footnote(first_page_text, "")
    if parsed_ieee:
        return parsed_ieee

    generic_institution_terms = {
        "academy",
        "center",
        "centre",
        "college",
        "department",
        "faculty",
        "hospital",
        "institute",
        "lab",
        "laboratory",
        "school",
        "university",
    }
    lines = []
    pending_prefix = ""
    normalized_text = re.sub(r"([A-Za-z])-\s*\n\s*([a-z])", r"\1\2", first_page_text or "")
    for raw_line in normalized_text.splitlines():
        left_column = re.split(r"\s{8,}(?=[a-z•])", raw_line.strip(), maxsplit=1)[0]
        line = re.sub(r"\s+", " ", left_column).strip()
        if not line or len(line) < 6:
            continue
        if re.search(r"^(abstract|摘要|keywords?|index terms|introduction)\b", line, re.IGNORECASE):
            continue
        line = _strip_email_tail(line)
        if INSTITUTION_KEYWORD_PATTERN.search(line) and not re.search(r"@", line):
            parts = re.split(r"\s+(?=\d+\s+[A-Z])", line)
            for part in parts:
                cleaned = _clean_institution_candidate(re.sub(r"^\d+\s*", "", part).strip(" ."))
                if pending_prefix and cleaned.casefold() in generic_institution_terms:
                    cleaned = f"{pending_prefix} {cleaned}"
                    pending_prefix = ""
                elif cleaned.casefold() in generic_institution_terms:
                    continue
                if _looks_like_institution_candidate(cleaned):
                    lines.append(cleaned)
                    continue
                if re.fullmatch(r"[A-Z][A-Za-z&.-]+(?:\s+[A-Z][A-Za-z&.-]+){0,3}", cleaned):
                    pending_prefix = cleaned
    return _dedupe_institutions(lines)


def _extract_footnote_block(first_page_text: str) -> str:
    """Extract IEEE-style footnote block from the bottom of first page.

    IEEE Trans templates place author affiliations in a footnote starting with
    lines like "This work was supported..." or "(Corresponding author: ...)".
    This block sits below the abstract and is often missed by top-down scraping.
    """
    text = first_page_text or ""
    footnote_markers = [
        r"This work was supported",
        r"\(Corresponding author[:：]",
        r"Manuscript received",
        r"Digital Object Identifier",
    ]
    earliest = len(text)
    for marker in footnote_markers:
        m = re.search(marker, text, re.IGNORECASE)
        if m and m.start() < earliest:
            earliest = m.start()

    if earliest >= len(text):
        return ""
    return text[earliest:]


def _compact_pdf_left_column(text: str) -> str:
    lines: list[str] = []
    for raw_line in (text or "").splitlines():
        left_column = re.split(r"\s{8,}(?=[a-z•])", raw_line.strip(), maxsplit=1)[0]
        line = re.sub(r"\s+", " ", left_column).strip()
        if line:
            lines.append(line)
    return " ".join(lines)


def _parse_ieee_footnote(footnote: str, known_authors: str) -> list[str]:
    """Parse IEEE-style "is with / was with" affiliation sentences."""
    institutions: list[str] = []
    compact = _compact_pdf_left_column(footnote)
    with_lead = (
        r"(?:(?:are|is|was|were)\s+(?:all\s+)?(?:also\s+)?"
        r"(?:currently\s+)?(?:now\s+)?with|(?:while|now)\s+with)"
    )

    lead_pattern = re.compile(with_lead + r"\s+", re.IGNORECASE)
    sentences = re.split(r"(?<=[.!?])\s+(?=(?:[•*]|\$|\(?[A-Z]))", compact)
    for sentence in sentences:
        if re.match(r"(?i)^\s*(?:this|the)\s+work\s+was\s+supported\b", sentence):
            continue
        match = lead_pattern.search(sentence)
        if not match:
            continue
        chunk = sentence[match.end() :].strip().rstrip(" ,;.")
        chunk = re.split(
            r"\b(?:these\s+authors\s+contributed|corresponding\s+author|e-?mail|email)\b",
            chunk,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        chunk = re.sub(r"\b\d{4,6}\b", "", chunk)
        chunk = re.sub(r"\s+", " ", chunk)
        for phrase in re.split(
            r",?\s+and\s+(?:is\s+)?(?:also\s+)?(?:now\s+)?with\s+|"
            r",?\s+and\s+also\s+with\s+|"
            r",?\s+and\s+with\s+",
            chunk,
            flags=re.IGNORECASE,
        ):
            phrase = re.sub(r"^(?:also\s+)?(?:now\s+)?with\s+", "", phrase.strip(), flags=re.IGNORECASE)
            _append_institution_candidate(institutions, phrase)

    return _dedupe_institutions(institutions)


def _latex_without_comments(text: str) -> str:
    cleaned_lines = []
    for line in (text or "").splitlines():
        cleaned_lines.append(re.sub(r"(?<!\\)%.*$", "", line))
    return "\n".join(cleaned_lines)


def _extract_latex_command_bodies(text: str, command: str) -> list[str]:
    bodies: list[str] = []
    pattern = re.compile(r"\\" + re.escape(command) + r"(?:\[[^\]]*\])?\s*\{")
    for match in pattern.finditer(text or ""):
        start = match.end()
        depth = 1
        i = start
        while i < len(text) and depth:
            char = text[i]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            i += 1
        if depth == 0:
            bodies.append(text[start : i - 1])
    return bodies


def _extract_latex_command_arg_groups(text: str, command: str, min_args: int) -> list[list[str]]:
    groups: list[list[str]] = []
    pattern = re.compile(r"\\" + re.escape(command) + r"(?:\[[^\]]*\])?")
    for match in pattern.finditer(text or ""):
        args: list[str] = []
        i = match.end()
        while i < len(text):
            while i < len(text) and text[i].isspace():
                i += 1
            if i >= len(text) or text[i] != "{":
                break
            start = i + 1
            depth = 1
            i = start
            while i < len(text) and depth:
                char = text[i]
                if char == "\\":
                    i += 2
                    continue
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                i += 1
            if depth != 0:
                break
            args.append(text[start : i - 1])
        if len(args) >= min_args:
            groups.append(args)
    return groups


def _latex_to_plain(text: str) -> str:
    plain = text or ""
    accent_map = {
        '\\"a': "ä",
        '\\"o': "ö",
        '\\"u': "ü",
        '\\"A': "Ä",
        '\\"O': "Ö",
        '\\"U': "Ü",
        "\\'e": "é",
        "\\'E": "É",
        "\\'a": "á",
        "\\'A": "Á",
        "\\'i": "í",
        "\\'I": "Í",
        "\\'o": "ó",
        "\\'O": "Ó",
        "\\'u": "ú",
        "\\'U": "Ú",
        "\\`e": "è",
        "\\`E": "È",
    }
    for latex, unicode_char in accent_map.items():
        plain = plain.replace(latex, unicode_char)
    plain = re.sub(r"\\\{[^{}]*\\\}\s*@\s*[\w.\-]+", " ", plain)
    plain = re.sub(r"\\(?:tt|small|footnotesize|scriptsize|hspace\*?)\s*(?:\{[^{}]*\})?", " ", plain)
    plain = re.sub(r"\\(?:url|href|email)\s*\{[^{}]*\}(?:\{[^{}]*\})?", " ", plain)
    plain = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", plain)
    plain = re.sub(r"[{}]", "", plain)
    plain = re.sub(r"[$^_~]", " ", plain)
    plain = re.sub(r"\\[\\,;:! ]", " ", plain)
    plain = re.sub(r"(?<=\d)(?=[A-Z])", " ", plain)
    return re.sub(r"\s+", " ", plain).strip()


def _extract_latex_key_values(text: str, key: str) -> list[str]:
    values: list[str] = []
    pattern = re.compile(r"\b" + re.escape(key) + r"\s*=\s*\{")
    for match in pattern.finditer(text or ""):
        start = match.end()
        depth = 1
        i = start
        while i < len(text) and depth:
            char = text[i]
            if char == "\\":
                i += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            i += 1
        if depth == 0:
            plain = _latex_to_plain(text[start : i - 1])
            if plain:
                values.append(plain)
    return values


def _institutions_from_latex_affiliation_body(body: str) -> list[str]:
    item_parts = re.split(r"\\IEEEcompsocthanksitem\b", body or "")
    if len(item_parts) > 1:
        institutions: list[str] = []
        for item in item_parts:
            institutions.extend(_institutions_from_latex_affiliation_body(item))
        return _dedupe_institutions(institutions)

    organizations = _extract_latex_key_values(body, "organization")
    if organizations:
        institutions: list[str] = []
        for organization in organizations:
            _append_institution_candidate(institutions, organization)
        return _dedupe_institutions(institutions)

    sentinel = "\u241e"
    normalized = re.sub(r"\\\\(?:\[[^\]]*\])?", sentinel, body or "")
    normalized = re.sub(r"([A-Za-z])-\s*\n\s*([a-z])", r"\1\2", normalized)
    normalized = re.sub(r"\s*\n\s*", " ", normalized)
    plain_lines = [_latex_to_plain(part) for part in normalized.split(sentinel)]
    plain = "\n".join(line for line in plain_lines if line)
    parsed = _parse_ieee_footnote(plain, "")
    if parsed:
        return parsed
    if re.search(r"\b(?:supported|grant|foundation|funds?)\b", plain, re.IGNORECASE):
        return []
    return _heuristic_institutions(plain)


def _institutions_from_latex_author_body(body: str) -> list[str]:
    normalized = re.sub(r"\\\\(?:\[[^\]]*\])?", "\n", body or "")
    normalized = re.sub(r"\\thanks\s*\{(?:[^{}]|\{[^{}]*\})*\}", " ", normalized)
    pieces: list[str] = []
    for chunk in re.split(r"\\(?:AND|And|and)\b", normalized):
        lines = [line for line in chunk.splitlines() if line.strip()]
        pieces.extend(lines or [chunk])

    institutions: list[str] = []
    for piece in pieces:
        plain = _strip_email_tail(_latex_to_plain(piece))
        plain = re.sub(r"^(?:[\d*†‡§¶]+(?:\s*,\s*)?)+", "", plain).strip(" ,;.")
        if not INSTITUTION_KEYWORD_PATTERN.search(plain):
            continue
        institutions.extend(_heuristic_institutions(plain))

    return _dedupe_institutions(institutions)


def _read_latex_sources(source_path: Path) -> list[str]:
    if not source_path or not source_path.exists():
        return []

    sources: list[tuple[str, str]] = []
    try:
        if tarfile.is_tarfile(source_path):
            with tarfile.open(source_path) as archive:
                for member in archive.getmembers():
                    if not member.isfile() or not member.name.lower().endswith(".tex"):
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        continue
                    text = extracted.read(500_000).decode("utf-8", errors="ignore")
                    sources.append((member.name, text))
        else:
            raw = source_path.read_bytes()
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
            text = raw[:1_000_000].decode("utf-8", errors="ignore")
            sources.append((source_path.name, text))
    except Exception:
        return []

    sources.sort(key=lambda item: (0 if re.search(r"(main|root|paper)\.tex$", item[0], re.IGNORECASE) else 1, item[0]))
    return [text for _, text in sources]


def extract_institutions_from_latex_source(source_path: Path | None) -> str:
    institutions: list[str] = []
    for raw_source in _read_latex_sources(source_path) if source_path else []:
        source = _latex_without_comments(raw_source)

        for args in _extract_latex_command_arg_groups(source, "icmlaffiliation", 2):
            institutions.extend(_institutions_from_latex_affiliation_body(args[1]))

        for command in [
            "thanks",
            "affil",
            "affiliation",
            "institute",
            "address",
            "IEEEauthorblockA",
            "IEEEcompsocitemizethanks",
        ]:
            for body in _extract_latex_command_bodies(source, command):
                institutions.extend(_institutions_from_latex_affiliation_body(body))

        if not institutions:
            for body in _extract_latex_command_bodies(source, "author"):
                institutions.extend(_institutions_from_latex_author_body(body))

        if institutions:
            break

    return "；".join(_dedupe_institutions(institutions))


def extract_institutions_from_first_page(title: str, authors: str, first_page_text: str) -> str:
    if not first_page_text.strip():
        return ""

    # Strategy 1: IEEE footnote — scan the *entire* first page, especially
    # the bottom footnote block that sits below the abstract.
    footnote = _extract_footnote_block(first_page_text)
    institutions: list[str] = []
    if footnote:
        institutions = _parse_ieee_footnote(footnote, authors)

    # Strategy 2: deterministic fallback — scan the entire first page, since
    # ICML/IEEE-style affiliations often sit below the abstract.
    if not institutions:
        institutions = _heuristic_institutions(first_page_text)

    # Strategy 3: LLM extraction — feed the full first page text (not just
    # the part before abstract), since many footnotes are below the abstract.
    if not institutions:
        context = (first_page_text or "")[:6000]
        prompt = (
            "你是学术论文信息抽取助手。请根据论文首页文本，提取作者所属单位名称。\n"
            "要求：\n"
            "1. 只输出单位名称，不输出作者名、邮箱、国家、脚注编号；\n"
            "2. 去重；\n"
            "3. 若首页无法可靠判断，返回严格 JSON []，不要猜测；\n"
            "4. 返回严格 JSON 数组，例如 [\"Tsinghua University\", \"Chinese Academy of Sciences\"]。\n"
            "5. 特别注意：IEEE 等期刊模板的单位信息常出现在摘要下方的脚注区域\n"
            "   （如 \"This work was supported...\" 或 \"(Corresponding author...)\" 之后的段落）。\n"
            "   请仔细阅读该区域，提取 \"is with / are with\" 后面跟着的单位名称。\n\n"
            f"标题：{title}\n"
            f"作者：{authors}\n"
            f"首页全文：\n{context}"
        )
        output = (call_llm(prompt, max_tokens=400, timeout=120) or "").strip()

        match = re.search(r"\[[\s\S]*\]", output)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    institutions = [str(item) for item in data if isinstance(item, str)]
            except Exception:
                institutions = []

    institutions = _dedupe_institutions(institutions)
    return "；".join(institutions)


def extract_abstract_from_pdf_text(pdf_text: str) -> str:
    text = (pdf_text or "").replace("\r\n", "\n")
    match = re.search(
        r"(?is)\babstract\b[:\s]*([\s\S]*?)(?=\n\s*(?:keywords?|index terms|1[\.\s]+introduction|introduction)\b)",
        text,
    )
    if not match:
        return ""
    abstract = re.sub(r"\s+", " ", match.group(1)).strip(" -")
    return abstract


def recover_metadata_from_pdf(title: str, authors: str, abstract_en: str, first_page_text: str, pdf_text: str) -> dict[str, str]:
    safe_title = "" if has_bad_placeholder(title) else (title or "").strip()
    safe_authors = "" if has_bad_placeholder(authors) else (authors or "").strip()
    safe_abstract = "" if has_bad_placeholder(abstract_en) else (abstract_en or "").strip()
    recovered = {
        "title": safe_title,
        "authors": safe_authors,
        "abstract_en": safe_abstract,
    }
    first_page_compact = "\n".join(
        re.sub(r"\s+", " ", line).strip()
        for line in (first_page_text or "").splitlines()
        if re.sub(r"\s+", " ", line).strip()
    )

    if not recovered["abstract_en"]:
        recovered["abstract_en"] = extract_abstract_from_pdf_text(pdf_text)

    if recovered["title"] and recovered["authors"] and recovered["abstract_en"]:
        return recovered

    prompt = (
        "你是学术论文元信息抽取助手。请根据论文首页文本和正文片段，提取标题、作者、英文摘要。\n"
        "要求：\n"
        "1. 返回严格 JSON：{\"title\":\"...\",\"authors\":[\"...\"],\"abstract_en\":\"...\"}\n"
        "2. authors 必须是作者姓名数组，不要单位、邮箱、脚注编号；\n"
        "3. 如果某项无法可靠提取，对应值返回空字符串或空数组，不要猜测；\n"
        "4. 不要输出 JSON 以外的内容。\n\n"
        f"首页文本：\n{first_page_compact[:4000]}\n\n"
        f"正文片段：\n{(pdf_text or '')[:6000]}"
    )
    output = (call_llm(prompt, max_tokens=800, timeout=120) or "").strip()
    match = re.search(r"\{[\s\S]*\}", output)
    if not match:
        return recovered

    try:
        data = json.loads(match.group(0))
    except Exception:
        return recovered

    title_candidate = str(data.get("title", "")).strip()
    authors_candidate = data.get("authors", [])
    abstract_candidate = str(data.get("abstract_en", "")).strip()

    if not recovered["title"] and title_candidate and title_candidate.lower() != "unknown":
        recovered["title"] = title_candidate
    if not recovered["authors"] and isinstance(authors_candidate, list):
        from clients.arxiv_client import format_authors

        formatted_authors = format_authors([str(item) for item in authors_candidate if isinstance(item, str)])
        if formatted_authors and not has_bad_placeholder(formatted_authors):
            recovered["authors"] = formatted_authors
    if not recovered["abstract_en"] and abstract_candidate:
        recovered["abstract_en"] = abstract_candidate

    return recovered


def summarize_paper(title: str, authors: str, abstract_en: str, pdf_text: str, retry_logger=None) -> dict:
    template = load_prompt("summarize_prompt.md")
    base_prompt = template.replace("{title}", title).replace("{authors}", authors)
    base_prompt = base_prompt.replace("{abstract_en}", abstract_en[:2000]).replace("{pdf_text}", pdf_text[:20000])

    format_spec = """
请按以下格式输出（纯文本，不要 JSON，不要代码块）：
摘要翻译: <中文摘要>
FLOWCHART:
flowchart LR
  A[输入视频] --> B[论文方法中的实际模块]
GLOSSARY:
- 术语：在本文中的具体含义
A1: <回答>
A2: <回答>
A3: <回答>
A4: <回答>
A5: <回答>
A6: <回答>
A7: <回答>
A8: <回答>
A9: <回答>
A10: <回答>
要求：
1) FLOWCHART、GLOSSARY、A1-A10 每项必须非空，禁止“待提取/未知/分析中/N/A/Unknown”；
2) A3-A6 是实现核心，必须出现论文具体模块名，并按输入、运算、输出、连接位置说明；
3) A7 必须按帧顺序解释一个困难事件，不得虚构具体数值；
4) A8 必须把实验变化与方法结论对应；
5) 同一项内不要重复表达，不要为了格式堆砌空泛 bullet。
"""
    result = call_llm(base_prompt + "\n\n" + format_spec, max_tokens=7500, timeout=450)

    missing_markers = [i for i in range(1, 11) if not re.search(rf"\bA{i}[:：]", result)]
    if missing_markers:
        if retry_logger:
            retry_logger("STEP-4", "RETRY", f"缺少标记 A{missing_markers}")
        retried = call_llm(base_prompt + "\n\n" + format_spec, max_tokens=7500, timeout=450)
        if retried:
            result = retried

    analysis = {"abstract_zh": ""}
    abstract_match = re.search(r"摘要翻译[:：]\s*([\s\S]*?)(?=\nFLOWCHART[:：]|\nA1[:：])", result)
    if abstract_match:
        analysis["abstract_zh"] = abstract_match.group(1).strip()

    flowchart_match = re.search(r"FLOWCHART[:：]\s*([\s\S]*?)(?=\nGLOSSARY[:：])", result)
    glossary_match = re.search(r"GLOSSARY[:：]\s*([\s\S]*?)(?=\nA1[:：])", result)
    analysis["flowchart"] = normalize_mermaid_flowchart(flowchart_match.group(1)) if flowchart_match else ""
    analysis["glossary"] = normalize_glossary(glossary_match.group(1)) if glossary_match else ""

    def extract_answer(index: int, text: str) -> str:
        match = re.search(rf"\n?A{index}[:：]\s*([\s\S]*?)(?=\nA{index+1}[:：]|$)", text)
        return match.group(1).strip() if match else ""

    repair_questions = (
        "用通俗语言说明输入、输出和相对基线的核心新增点。",
        "用具体失败场景说明旧方法为何需要被改进。",
        "按执行顺序解释从视频输入到轨迹输出的完整流程，并区分训练与推理。",
        "按输入、具体运算、输出、作用机制解释最关键创新模块。",
        "解释其余关键模块、关联代价、匹配与轨迹管理如何实现。",
        "解释训练数据、监督信号、损失函数以及推理阶段保留的模块。",
        "用连续三帧和一个困难事件逐步走完本文方法，解释 ID 如何保持。",
        "用关键主结果与消融说明实验到底证明了什么、不能证明什么。",
        "整理复现所需实现配置、阈值、硬件、速度和代码状态。",
        "对比最相关 MOT 路线，说明真正新增点、代价、适用场景与失败边界。",
    )

    for i in range(1, 11):
        analysis[f"q{i}"] = extract_answer(i, result)

    for i in range(1, 11):
        answer = analysis.get(f"q{i}", "")
        minimum_length = 180 if i in {3, 4, 5, 6, 7} else 80
        if answer and not has_bad_placeholder(answer) and len(answer) >= minimum_length:
            continue

        repaired = ""
        for _ in range(2):
            repair_prompt = (
                f"基于以下论文信息，仅回答A{i}对应问题，180-350字，中文，不要编号前缀，不要占位词。"
                "涉及模块时必须按输入、具体运算、输出、作用机制解释；论文未说明的信息明确指出。\n"
                f"Q{i}问题：{repair_questions[i - 1]}\n"
                f"标题：{title}\n作者：{authors}\n摘要：{abstract_en[:1500]}\n正文片段：{pdf_text[:4000]}"
            )
            repaired = call_llm(repair_prompt, max_tokens=600, timeout=150).strip()
            if repaired and not has_bad_placeholder(repaired):
                break
        analysis[f"q{i}"] = repaired if repaired else "该问题在论文中信息有限，基于摘要与正文可得出初步结论。"

    if (
        not analysis.get("flowchart")
        or not re.search(r"flowchart\s+(?:LR|TD|RL|BT)", analysis["flowchart"], re.IGNORECASE)
        or len(re.findall(r"-->", analysis["flowchart"])) < 4
    ):
        flow_prompt = (
            "基于以下论文，输出一段 Mermaid flowchart LR 源码，不要代码围栏。"
            "使用5-9个简短中文节点，严格按论文的数据流覆盖输入、核心模块、关联/轨迹更新和输出；不要编造模块。\n"
            f"标题：{title}\n摘要：{abstract_en[:1500]}\n正文片段：{pdf_text[:6000]}"
        )
        analysis["flowchart"] = normalize_mermaid_flowchart(
            call_llm(flow_prompt, max_tokens=700, timeout=150)
        )

    if not analysis.get("glossary") or len(re.findall(r"^- ", analysis["glossary"], re.MULTILINE)) < 5:
        glossary_prompt = (
            "基于以下论文列出5-10个理解本文必需的术语。每行格式为“- 术语：在本文中的具体含义或作用”。"
            "只解释本文语境，不写通用百科定义，不要标题。\n"
            f"标题：{title}\n摘要：{abstract_en[:1500]}\n正文片段：{pdf_text[:6000]}"
        )
        analysis["glossary"] = normalize_glossary(
            call_llm(glossary_prompt, max_tokens=900, timeout=150)
        )

    if not analysis.get("abstract_zh"):
        analysis["abstract_zh"] = translate_text(abstract_en)

    return analysis
