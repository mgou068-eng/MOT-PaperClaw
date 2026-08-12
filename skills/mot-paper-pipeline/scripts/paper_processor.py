#!/usr/bin/env python3
from __future__ import annotations

"""
论文处理脚本 v4 - 优化版
- 使用独立 prompt 文件
- LLM 调用分离（翻译、标签、总结）
- 并行信息获取
"""

import subprocess
import glob
import re
import time
from pathlib import Path
from datetime import datetime
import json
import html
import urllib.request
import urllib.parse

from clients.arxiv_client import download_pdf, download_source, extract_abs_info
from pipeline_config import get_repo, load_config
from services.paper_analysis import (
    extract_institutions_from_first_page,
    extract_institutions_from_latex_source,
    extract_tags,
    format_answer_md,
    generate_tldr,
    is_valid_institution_text,
    quality_gate,
    recover_metadata_from_pdf,
    summarize_paper,
    translate_text,
)

CONFIG = load_config()
FIGURES_DIR = CONFIG.figures_dir

# ============ 工具函数 ============

def log_step(step: str, status: str, reason: str = ""):
    msg = f"[{step}] {status}"
    if reason:
        msg += f" | {reason}"
    print(msg)


def _institution_count(text: str) -> int:
    return len([chunk for chunk in re.split(r"[；;]", text or "") if chunk.strip()])


def _safe_paper_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "paper"


def _request_bytes(url: str, timeout: int = 90) -> tuple[bytes, str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(), response.geturl(), response.headers.get_content_type()


def _extract_pdf_links(body: bytes, base_url: str) -> list[str]:
    text = body.decode("utf-8", errors="ignore")
    links: list[str] = []
    patterns = [
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            resolved = urllib.parse.urljoin(base_url, html.unescape(match.group(1)))
            if resolved not in links:
                links.append(resolved)
    for match in re.finditer(r'href=["\']([^"\']+)["\']', text, flags=re.IGNORECASE):
        raw_link = html.unescape(match.group(1))
        path = urllib.parse.urlparse(raw_link).path.lower()
        if "/article/view/" not in path and "/article/download/" not in path and not path.endswith(".pdf"):
            continue
        resolved = urllib.parse.urljoin(base_url, raw_link)
        if resolved not in links:
            links.append(resolved)
    return links


def _curl_fetch(url: str) -> tuple[bytes, str]:
    result = subprocess.run(
        [
            "curl",
            "-k",
            "-sS",
            "-L",
            "--compressed",
            "--retry",
            "2",
            "--retry-all-errors",
            "--max-time",
            "90",
            "-w",
            "\n%{url_effective}",
            url,
        ],
        check=True,
        capture_output=True,
    )
    data, separator, effective_url = result.stdout.rpartition(b"\n")
    return (data if separator else result.stdout), effective_url.decode("utf-8", errors="ignore")


def _download_public_pdf(url: str, paper_id: str) -> tuple[Path | None, str]:
    if not url:
        return None, ""
    output = CONFIG.temp_dir / f"{_safe_paper_id(paper_id)}.pdf"
    pending = [url]
    attempted: set[str] = set()
    errors: list[str] = []
    while pending and len(attempted) < 8:
        current = pending.pop(0)
        if current in attempted:
            continue
        attempted.add(current)
        for attempt in range(2):
            try:
                data, final_url, content_type = _request_bytes(current)
                if data.startswith(b"%PDF") or content_type == "application/pdf":
                    output.write_bytes(data)
                    return output, final_url
                pending.extend(link for link in _extract_pdf_links(data, final_url) if link not in attempted)
                errors.append(f"not PDF: {final_url}")
                break
            except Exception as exc:
                errors.append(f"{current}: {exc}")
                if attempt == 0:
                    time.sleep(3)
        try:
            data, final_url = _curl_fetch(current)
            if data.startswith(b"%PDF"):
                output.write_bytes(data)
                return output, final_url
            pending.extend(link for link in _extract_pdf_links(data, final_url) if link not in attempted)
        except Exception as exc:
            errors.append(f"curl {current}: {exc}")
    log_step("STEP-1", "FAILED", f"公开 PDF 下载失败: {' | '.join(errors[-3:])}")
    return None, ""

def handle_figures(arxiv_id: str, pdf_path: Path, repo=None) -> list:
    """将 PDF 前三页转 JPG 并上传，返回已上传页码列表"""
    preview_id = _safe_paper_id(arxiv_id)
    arxiv_dir = FIGURES_DIR / preview_id
    arxiv_dir.mkdir(parents=True, exist_ok=True)
    uploaded = []

    for page in [1, 2, 3]:
        out_prefix = arxiv_dir / f"page_{page}"
        jpg_path = arxiv_dir / f"page_{page}.jpg"
        try:
            # 仅转换单页为 jpg
            subprocess.run([
                "pdftoppm", "-jpeg", "-f", str(page), "-l", str(page), str(pdf_path), str(out_prefix)
            ], check=True, capture_output=True)

            candidates = sorted(glob.glob(str(arxiv_dir / f"page_{page}-*.jpg")))
            if candidates:
                Path(candidates[0]).rename(jpg_path)
            elif not jpg_path.exists():
                continue

            dest = f"papers/previews/{preview_id}/page_{page}.jpg"
            if repo is not None:
                with open(jpg_path, 'rb') as f:
                    content = f.read()
                try:
                    existing = repo.get_contents(dest)
                    repo.update_file(dest, f"Update {arxiv_id} page_{page}.jpg", content, existing.sha)
                except:
                    repo.create_file(dest, f"Add {arxiv_id} page_{page}.jpg", content)
            uploaded.append(page)
        except Exception:
            continue

    return uploaded

# ============ 主流程 ============

def process_paper(
    arxiv_id: str,
    issue_number: int | None = None,
    dry_run: bool = False,
    output_dir: str | None = None,
    target_date: str | None = None,
    publication: dict | None = None,
):
    print(f"\n{'='*60}")
    print(f"处理论文: {arxiv_id}")
    print(f"{'='*60}")

    repo = None if dry_run else get_repo(CONFIG)
    publication = publication or {}
    real_arxiv_id = arxiv_id if not arxiv_id.startswith(("doi:", "s2:")) else ""

    log_step("STEP-1", "RUNNING", "信息获取")
    
    # 1.1 下载 PDF。正式记录没有 arXiv ID 时使用来源提供的公开 PDF。
    if real_arxiv_id:
        pdf_path, pdf_ok = download_pdf(real_arxiv_id)
    else:
        pdf_path, resolved_pdf_url = _download_public_pdf(str(publication.get("pdf_url") or ""), arxiv_id)
        if resolved_pdf_url:
            publication["pdf_url"] = resolved_pdf_url
        pdf_ok = pdf_path is not None
    if not pdf_ok:
        log_step("STEP-1", "FAILED", "PDF 下载失败")
        return None, "PDF 下载失败"

    # 1.2 提取 abs 信息
    info = extract_abs_info(real_arxiv_id) if real_arxiv_id else {
        "title": str(publication.get("title") or "Unknown"),
        "authors": "待提取",
        "institutions": "待提取",
        "abstract_en": "",
        "date": str(publication.get("year") or datetime.now().year),
    }
    log_step("STEP-1", "OK", f"title={info['title'][:40]} | authors={info['authors'][:30]}")

    first_page_text = ""
    if pdf_path and pdf_path.exists():
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", "-f", "1", "-l", "1", str(pdf_path), "-"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            first_page_text = result.stdout if result.returncode == 0 else ""
        except Exception:
            pass

    pdf_text = ""
    if pdf_path and pdf_path.exists():
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", "-f", "1", "-l", "30", str(pdf_path), "-"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            pdf_text = result.stdout if result.returncode == 0 else ""
        except Exception:
            pass

    recovered = recover_metadata_from_pdf(
        info.get("title", ""),
        info.get("authors", ""),
        info.get("abstract_en", ""),
        first_page_text,
        pdf_text,
    )
    info["title"] = recovered["title"] or info.get("title", "")
    info["authors"] = recovered["authors"] or info.get("authors", "")
    info["abstract_en"] = recovered["abstract_en"] or info.get("abstract_en", "")
    log_step("STEP-1", "OK", f"recovered_title={info['title'][:40]} | recovered_authors={info['authors'][:30]}")

    pdf_institutions = extract_institutions_from_first_page(info["title"], info["authors"], first_page_text)
    source_institutions = ""
    if not is_valid_institution_text(info.get("institutions", "")):
        source_path = download_source(real_arxiv_id) if real_arxiv_id else None
        source_institutions = extract_institutions_from_latex_source(source_path)

    if is_valid_institution_text(source_institutions) and (
        not is_valid_institution_text(pdf_institutions)
        or _institution_count(source_institutions) >= _institution_count(pdf_institutions)
    ):
        info["institutions"] = source_institutions
    elif is_valid_institution_text(pdf_institutions):
        info["institutions"] = pdf_institutions
    log_step("STEP-1", "OK", f"institutions={info['institutions'][:60] if info['institutions'] else 'EMPTY'}")

    # 1.3 处理图片（PDF前三页转JPG并上传）
    uploaded = handle_figures(arxiv_id, pdf_path, repo)
    log_step("STEP-1", "OK", f"preview_images={len(uploaded)}")

    log_step("STEP-2", "RUNNING", "翻译")
    abstract_zh = translate_text(info['abstract_en'])
    log_step("STEP-2", "OK", f"abstract_len={len(abstract_zh)}")

    log_step("STEP-3", "RUNNING", "提取标签")
    tags = extract_tags(info['title'], info['abstract_en'])[:5]
    log_step("STEP-3", "OK", f"top5_tags={tags}")

    log_step("STEP-4", "RUNNING", "LLM 总结")
    
    # 调用 LLM 总结
    analysis = summarize_paper(info['title'], info['authors'], info['abstract_en'], pdf_text, retry_logger=log_step)
    log_step("STEP-4", "OK", "总结完成")

    # 质检门禁：不过则重跑一次总结，仍失败则中止更新
    ok, errors = quality_gate(info, analysis, abstract_zh, len(uploaded))
    if not ok:
        log_step("GATE", "RETRY", "; ".join(errors))
        analysis = summarize_paper(info['title'], info['authors'], info['abstract_en'], pdf_text, retry_logger=log_step)
        ok, errors = quality_gate(info, analysis, abstract_zh, len(uploaded))
    if not ok:
        log_step("GATE", "FAILED", "; ".join(errors))
        return None, f"质检未通过: {'; '.join(errors)}"
    log_step("GATE", "OK", "通过")

    log_step("STEP-5", "RUNNING", "生成报告")
    # 优先使用 target_date（pipeline 指定的业务日期），避免 arXiv API 日期漂移
    if target_date:
        title_date = target_date
        date_str = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"
    else:
        date_str = info.get('date', datetime.now().strftime("%Y-%m-%d"))
        title_date = date_str.replace("-", "")
    
    # 报告内容：PDF 前三页预览（1行3列）
    if uploaded:
        cols = []
        for p in [1, 2, 3]:
            if p in uploaded:
                preview_id = _safe_paper_id(arxiv_id)
                cols.append(f"<td><img src=\"{CONFIG.raw_content_base}/papers/previews/{preview_id}/page_{p}.jpg\" width=\"100%\"/><br/>Page {p}</td>")
            else:
                cols.append("<td>Page missing</td>")
        img_section = "<table><tr>" + "".join(cols) + "</tr></table>"
    else:
        img_section = "*预览图暂缺*"
    
    tldr = generate_tldr(info['title'], info['abstract_en'])
    abstract_short = abstract_zh[:400] + "..." if len(abstract_zh) > 400 else abstract_zh

    # Markdown 可读性优化
    qa_md = {f"q{i}": format_answer_md(analysis.get(f"q{i}", "")) for i in range(1, 11)}
    flowchart_md = analysis.get("flowchart", "").strip()
    glossary_md = analysis.get("glossary", "").strip()

    venue = str(publication.get("venue") or "-")
    publication_year = str(publication.get("year") or "-")
    doi = str(publication.get("doi") or "-")
    source_url = str(publication.get("source_url") or "")
    source_value = f"[Semantic Scholar]({source_url})" if source_url else "-"
    fulltext_value = (
        f"[abs](https://arxiv.org/abs/{real_arxiv_id}) \\| [pdf](https://arxiv.org/pdf/{real_arxiv_id})"
        if real_arxiv_id
        else f"[公开 PDF]({publication.get('pdf_url')})"
    )

    report = f"""# [{title_date}] {info['title']}

## 📋 基础信息

| 项目 | 内容 |
|------|------|
| **标题** | {info['title']} |
| **作者** | {info['authors']} |
| **单位** | {info['institutions']} |
| **日期** | {date_str} |
| **Venue** | {venue} |
| **发表年份** | {publication_year} |
| **DOI** | {doi} |
| **Venue 来源** | {source_value} |
| **全文** | {fulltext_value} |
| **TL;DR** | {tldr} |
| **摘要** | {abstract_short} |
| **标签** | {', '.join([title_date] + tags)} |

---

## 🧠 TL;DR（速览）

- {tldr}

---

## 📸 论文概览

{img_section}

---

## 🗺️ 方法流程图

```mermaid
{flowchart_md}
```

---

## 📖 关键术语

{glossary_md}

---

## 🧩 从直觉到实现：10 步读懂方法

### Q1: 一句话讲清：输入、输出与核心变化
{qa_md.get('q1', '分析中...')}

### Q2: 为什么需要它：旧方法如何失败
{qa_md.get('q2', '分析中...')}

### Q3: 完整流程：视频如何变成轨迹
{qa_md.get('q3', '分析中...')}

### Q4: 核心创新模块如何实现
{qa_md.get('q4', '分析中...')}

### Q5: 其余模块、数据关联与轨迹管理
{qa_md.get('q5', '分析中...')}

### Q6: 如何训练，推理时保留什么
{qa_md.get('q6', '分析中...')}

### Q7: 连续三帧实例：ID 如何保持
{qa_md.get('q7', '分析中...')}

### Q8: 实验真正证明了什么
{qa_md.get('q8', '分析中...')}

### Q9: 复现与实现清单
{qa_md.get('q9', '分析中...')}

### Q10: 与主流路线相比的新增点、代价与边界
{qa_md.get('q10', '分析中...')}

---

Powered by OpenClaw🦞
"""
    
    if dry_run:
        target_dir = Path(output_dir) if output_dir else (CONFIG.temp_dir / "MOT-PaperClaw" / "paper_reports")
        target_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "arxiv_id": arxiv_id,
            "issue_number": issue_number,
            "title": info["title"],
            "authors": info["authors"],
            "institutions": info["institutions"],
            "date": title_date,
            "labels": [title_date] + tags,
            "body": report,
            "html_url": f"https://github.com/{CONFIG.github_repo}/issues/{issue_number}" if issue_number else "",
            "number": issue_number or 0,
        }
        out_path = target_dir / f"{title_date}_{arxiv_id.replace('/', '_')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log_step("ISSUE", "DRY_RUN", str(out_path))
        return payload, None

    # 更新策略：指定 issue_number 时仅更新；未指定时仅匹配更新，不创建
    target_issue = None
    if issue_number is not None:
        try:
            target_issue = repo.get_issue(issue_number)
        except Exception as e:
            log_step("ISSUE", "FAILED", f"指定 Issue 不存在: {issue_number}")
            return None, f"指定 Issue #{issue_number} 不存在"
    else:
        for issue in repo.get_issues(state='all'):
            if info['title'][:30] in issue.title:
                target_issue = issue
                break

    if target_issue is not None:
        # 保留现有 issue 的日期标签，避免 arXiv API 日期漂移导致日报引用错乱
        existing_labels = [l for l in target_issue.labels]
        existing_date_label = None
        for label in existing_labels:
            if isinstance(label, str) and re.fullmatch(r"\d{8}", label):
                existing_date_label = label
                break
            name = getattr(label, "name", "")
            if re.fullmatch(r"\d{8}", name):
                existing_date_label = name
                break
        final_date = existing_date_label or title_date
        target_issue.edit(
            title=f"[{final_date}] {info['title'][:200]}",
            body=report,
            labels=[final_date] + tags,
        )
        log_step("ISSUE", "UPDATED", f"#{target_issue.number}")
        print(f"\n✅ 完成！")
        return target_issue, None

    # 未指定 issue_number 且未匹配到现有 issue -> 创建新 issue
    new_issue = repo.create_issue(
        title=f"[{title_date}] {info['title'][:200]}",
        body=report,
        labels=[title_date] + tags,
    )
    log_step("ISSUE", "CREATED", f"#{new_issue.number}")
    print(f"\n✅ 完成！")
    return new_issue, None

if __name__ == "__main__":
    import sys
    arxiv_id = sys.argv[1] if len(sys.argv) > 1 else "2603.08556"
    issue_number = int(sys.argv[2]) if len(sys.argv) > 2 else None
    result, err = process_paper(arxiv_id, issue_number)
    if err:
        print(f"❌ {err}")
    elif result and hasattr(result, "number"):
        print(f"✅ #{result.number}")
