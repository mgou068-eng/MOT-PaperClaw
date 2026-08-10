# MOT-PaperClaw

Automated discovery, analysis, and daily digests for multi-object tracking research.

MOT-PaperClaw is adapted from [RS-PaperClaw](https://github.com/thinson/RS-PaperClaw). The discovery queries, hard filters, semantic filter, controlled tags, analysis prompts, digest editor, notifications, documentation, and web reader now target multi-object tracking.

## Scope

Included: 2D/3D MOT, multi-camera tracking, online/offline tracking, tracking-by-detection, end-to-end MOT, and MOT-specific detection, ReID, motion, association, occlusion, and trajectory reasoning.

Excluded: single-object tracking, plain detection, ReID without MOT evaluation, SLAM, pose estimation, and trajectory forecasting without multi-identity tracking.

## Quick start

```bash
cd skills/mot-paper-pipeline
./bootstrap.sh
```

Set `GITHUB_TOKEN`, `LLM_API_KEY`, and `MOT_GITHUB_REPO` in `.env`, then run:

```bash
python3 scripts/cli.py doctor
python3 scripts/cli.py filter --dry-run --date 20260730
python3 scripts/cli.py run --no-notify
```

Filtering rules are in `scripts/config/filter_keywords.json` and `scripts/prompts/filter_cross_prompt.md`. New deployments should use `MOT_*` variables; legacy `RS_*` names remain compatible.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Licensed under MIT. See `skills/mot-paper-pipeline/LICENSE`.
