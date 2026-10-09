from __future__ import annotations

from pathlib import Path
import os


APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "TradutorRPGMaker"


CACHE_FILE = APP_DIR / "translation_cache.sqlite3"


SETTINGS_FILE = APP_DIR / "settings.json"


MODELS_DIR = APP_DIR / "models"
