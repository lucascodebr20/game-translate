from __future__ import annotations

import json
from game_translate.paths import SETTINGS_FILE
from game_translate.translation.catalog import DEFAULT_ENGINE, ENGINES


def load_settings() -> dict:
    try:
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    if settings.get("engine") not in ENGINES:
        settings["engine"] = DEFAULT_ENGINE
    return settings


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
