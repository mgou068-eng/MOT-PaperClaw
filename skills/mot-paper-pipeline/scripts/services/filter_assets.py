#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pipeline_config import load_config


CONFIG = load_config()


def _read_text(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"Missing filter asset file: {path}")
    return path.read_text(encoding="utf-8").strip()


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"Missing filter config file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid filter config file: {path}")
    return data


def _load_string_list(data: dict, key: str, path: Path) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise RuntimeError(f"Invalid '{key}' in filter config: {path}")
    return [item.strip() for item in value]


@lru_cache(maxsize=1)
def load_filter_keywords() -> dict[str, list[str]]:
    data = _read_json(CONFIG.filter_keywords_path)
    return {
        "mot_query_terms": _load_string_list(data, "mot_query_terms", CONFIG.filter_keywords_path),
        "mot_signal_patterns": _load_string_list(data, "mot_signal_patterns", CONFIG.filter_keywords_path),
        "tracking_method_patterns": _load_string_list(data, "tracking_method_patterns", CONFIG.filter_keywords_path),
        "exclude_patterns": _load_string_list(data, "exclude_patterns", CONFIG.filter_keywords_path),
    }


@lru_cache(maxsize=1)
def load_filter_prompt_template() -> str:
    template = _read_text(CONFIG.filter_prompt_path)
    if "{{candidate_lines}}" not in template:
        raise RuntimeError(f"Filter prompt template must contain {{candidate_lines}}: {CONFIG.filter_prompt_path}")
    return template


@lru_cache(maxsize=1)
def load_mot_query_terms() -> list[str]:
    return load_filter_keywords()["mot_query_terms"]


@lru_cache(maxsize=1)
def load_mot_signal_patterns() -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in load_filter_keywords()["mot_signal_patterns"]]


@lru_cache(maxsize=1)
def load_tracking_method_patterns() -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in load_filter_keywords()["tracking_method_patterns"]]


@lru_cache(maxsize=1)
def load_exclude_patterns() -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in load_filter_keywords()["exclude_patterns"]]


def render_filter_prompt(candidate_lines: list[str]) -> str:
    template = load_filter_prompt_template()
    return template.replace("{{candidate_lines}}", "\n".join(candidate_lines))
