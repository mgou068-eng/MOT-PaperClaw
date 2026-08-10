---
name: mot-paper-pipeline
description: Operate and maintain MOT-PaperClaw, which tracks multi-object tracking papers from arXiv, creates per-paper issues, builds daily digests, and publishes daily_reports.
---

Operate this skill from `skills/mot-paper-pipeline/`.

## Required environment

- `GITHUB_TOKEN`
- `LLM_API_KEY`
- `MOT_GITHUB_REPO`

Optional settings include `LLM_MODEL`, `LLM_API_URL`, `MOT_PROXY_URL`, `DINGTALK_WEBHOOK`, and `FEISHU_TARGET`.

## Entry points

- Check the environment: `python3 scripts/cli.py doctor`
- Preview filtering: `python3 scripts/cli.py filter --dry-run --date YYYYMMDD`
- Run the pipeline: `python3 scripts/cli.py run`
- Replay a date: `python3 scripts/cli.py run --date YYYYMMDD --no-notify`
- Reconcile issues: `python3 scripts/cli.py reconcile --date YYYYMMDD --dry-run`

## Filtering contract

MOT query terms and regexes live in `scripts/config/filter_keywords.json`; semantic inclusion/exclusion rules live in `scripts/prompts/filter_cross_prompt.md`. A paper must contain explicit multi-object or multi-target tracking evidence. Single-object tracking, plain detection, ReID without MOT evaluation, SLAM, and trajectory prediction are out of scope.
