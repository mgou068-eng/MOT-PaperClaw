# MOT-PaperClaw Runbook

## Setup

```bash
cd skills/mot-paper-pipeline
./bootstrap.sh
source .venv/bin/activate
```

Configure `.env`:

```dotenv
GITHUB_TOKEN=github_pat_xxx
LLM_API_KEY=xxx
MOT_GITHUB_REPO=your-github-user/MOT-PaperClaw
```

Optional variables include `LLM_MODEL`, `LLM_API_URL`, `MOT_PROXY_URL`, `DINGTALK_WEBHOOK`, and `FEISHU_TARGET`.

## Validate

```bash
python3 scripts/cli.py doctor
python3 -m unittest discover -s tests -v
python3 scripts/cli.py filter --dry-run --date YYYYMMDD --stats-out memory/mot_daily_stats_YYYYMMDD.json
```

Inspect every dry-run candidate for explicit multi-identity tracking. A broad detector, SOT method, or pure trajectory predictor is a false positive.

## Operate

```bash
python3 scripts/cli.py run --no-notify
python3 scripts/cli.py run --date YYYYMMDD --no-notify
python3 scripts/cli.py paper ARXIV_ID --dry-run
python3 scripts/cli.py reconcile --date YYYYMMDD --dry-run
```

## GitHub Actions

Configure repository secrets `MOT_GITHUB_TOKEN` and `LLM_API_KEY`, plus variable `MOT_GITHUB_REPO`. The workflows are `.github/workflows/mot-pipeline-schedule.yml` and `.github/workflows/mot-pipeline-manual.yml`.

## Failure triage

- Too many candidates: tighten `mot_query_terms` and `mot_signal_patterns`.
- False positives after LLM: strengthen `filter_cross_prompt.md`; the local hard gate should still reject papers without MOT evidence.
- Empty digest: inspect `memory/mot_daily_stats_YYYYMMDD.json` and paper quality-gate errors.
- Duplicate Issues: rebuild `papers/issue_index.json` with `python3 scripts/cli.py rebuild-index`.
- Missing preview images: verify `pdftoppm` and arXiv PDF access.
