# MOT-PaperClaw Pipeline SOP

1. Run `python3 scripts/cli.py doctor`.
2. Run a dated `filter --dry-run` and inspect candidates.
3. Run `python3 scripts/cli.py run --date YYYYMMDD --no-notify`.
4. Confirm paper Issues contain MOT labels, metrics, datasets, and non-placeholder metadata.
5. Confirm the digest Issue and `daily_reports/YYYYMM/YYYYMMDD.md` contain the same paper set.
6. Enable notification only after the report is correct.

On failure, inspect `memory/mot_daily_stats_YYYYMMDD.json` and `memory/pipeline_state/YYYYMMDD.json` before retrying.
