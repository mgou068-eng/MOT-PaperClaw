# MOT-PaperClaw Agent Guide

## Invariants

- Do not admit a paper without explicit multi-object, multi-target, multi-camera, or equivalent MOT evidence in its title or abstract.
- Do not treat detection, SOT, ReID, SLAM, or trajectory forecasting as MOT unless multi-identity tracking is an evaluated task.
- Keep deterministic query/regex rules in `scripts/config/filter_keywords.json`, not in Python.
- Keep semantic boundaries in `scripts/prompts/filter_cross_prompt.md`.
- Preserve one arXiv paper per Issue and use `papers/issue_index.json` for deduplication.
- Never hardcode credentials or a personal repository name.
- Run unit tests and a dated filter dry-run after filter changes.

## Expected report analysis

Reports should identify the setting (2D/3D, online/offline, single/multi-camera), detector assumptions, appearance/ReID representation, motion model, association mechanism, occlusion handling, datasets, metrics, runtime, and ablations. Do not collapse HOTA, IDF1, MOTA, or AMOTA into a generic accuracy claim.

## Verification

```bash
cd skills/mot-paper-pipeline
python3 -m unittest discover -s tests -v
python3 scripts/cli.py filter --dry-run --date YYYYMMDD
```
