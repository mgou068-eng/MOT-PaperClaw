# MOT Paper Pipeline

This directory contains the operational pipeline behind MOT-PaperClaw.

## Commands

```bash
./bootstrap.sh
python3 scripts/cli.py doctor
python3 scripts/cli.py filter --dry-run --date YYYYMMDD
python3 scripts/cli.py run --no-notify
python3 scripts/cli.py reconcile --date YYYYMMDD --dry-run
```

Required environment variables are `GITHUB_TOKEN`, `LLM_API_KEY`, and `MOT_GITHUB_REPO`. Copy `.env.example` to `.env` and replace the repository placeholder before running.

## Domain configuration

- Discovery and hard-filter rules: `scripts/config/filter_keywords.json`
- Semantic inclusion/exclusion contract: `scripts/prompts/filter_cross_prompt.md`
- Controlled MOT labels: `scripts/prompts/tags_prompt.md`
- MOT-specific paper analysis: `scripts/prompts/summarize_prompt.md`

The hard filter always runs after the LLM filter. A malformed or over-broad LLM response cannot admit a paper without explicit MOT evidence.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
