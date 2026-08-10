# MOT-PaperClaw Pipeline Overview

## Data flow

1. `clients/arxiv_client.py` builds an arXiv query from MOT phrases and applies local strong-evidence regexes.
2. `daily_arxiv_cross_filter.py` asks the LLM to enforce the MOT task boundary, then applies the local MOT gate again.
3. `paper_processor.py` extracts metadata and previews, generates controlled tags, and creates or refreshes one Issue per paper.
4. `daily_digest_llm_upgrade.py` builds a date Issue from successful paper Issues.
5. `sync_daily_reports_to_repo.py` archives digest Issues under `daily_reports/`.
6. `run_mot_daily_workday.py` coordinates the flow and optional notifications.

## Domain boundary

An included paper must track multiple entities over time and preserve identity or trajectories. Explicit MOT/multi-target/multi-camera/tracking-by-detection evidence is required in the title or abstract. SOT, plain detection, standalone ReID, SLAM, and trajectory forecasting are excluded unless the paper also defines and evaluates an MOT task.

## Runtime state

- Filter statistics: `memory/mot_daily_stats_YYYYMMDD.json`
- Step state: `memory/pipeline_state/YYYYMMDD.json`
- Lock: `memory/mot_daily_workday.lock`
- Issue index: repository file `papers/issue_index.json`

See `RUNBOOK_MOT_PIPELINE.md` for operation and `AGENT_GUIDE_MOT_PIPELINE.md` for maintenance constraints.
