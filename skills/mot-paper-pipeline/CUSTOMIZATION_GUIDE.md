# MOT-PaperClaw Customization Guide

## Change subdomain coverage

Edit `scripts/config/filter_keywords.json`:

- `mot_query_terms`: phrases sent to arXiv.
- `mot_signal_patterns`: strong local inclusion evidence.
- `tracking_method_patterns`: association/motion/benchmark evidence used by the no-LLM fallback.
- `exclude_patterns`: nearby tasks that are out of scope without explicit MOT evidence.

Add narrow phrases such as `3D multi-object tracking` or `multi-camera tracking` rather than generic terms such as `object tracking`, `tracking`, or `detection`.

## Change semantic policy

Edit `scripts/prompts/filter_cross_prompt.md`. Keep the output contract as a strict JSON array of arXiv IDs because the parser depends on it. The local MOT gate remains authoritative after LLM selection.

## Change labels and analysis

Edit `tags_prompt.md` to adjust the controlled taxonomy and `summarize_prompt.md` to change report questions. Keep `Multi-Object Tracking` as the first label so downstream browsing remains consistent.

## Change deployment target

Set `MOT_GITHUB_REPO=owner/repository`; do not edit Python constants. Legacy `RS_GITHUB_REPO`, `RS_PROXY_URL`, `RS_WORKSPACE`, and filter-path variables are accepted only as compatibility aliases.

## Minimum validation

```bash
python3 -m unittest discover -s tests -v
python3 scripts/cli.py filter --dry-run --date YYYYMMDD
```

Manually verify at least one true MOT paper and representative negatives for SOT, plain detection, standalone ReID, SLAM, and trajectory forecasting.
