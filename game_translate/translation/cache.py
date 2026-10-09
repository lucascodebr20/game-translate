from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Callable, Iterable
import sqlite3


_CACHE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS engine_translations ("
    "engine TEXT NOT NULL, from_code TEXT NOT NULL, to_code TEXT NOT NULL, source TEXT NOT NULL, "
    "translated TEXT NOT NULL, PRIMARY KEY (engine, from_code, to_code, source))"
)


def _open_cache(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute(_CACHE_SCHEMA)
    legacy = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'translations'").fetchone()
    if legacy:
        with db:
            db.execute("INSERT OR IGNORE INTO engine_translations SELECT 'argos', * FROM translations")
            db.execute("DROP TABLE translations")
    return db


def _load_cache(
    path: Path, engine: str, from_code: str, to_code: str, texts: Iterable[str]
) -> dict[str, str]:
    if not path.is_file():
        return {}
    wanted = set(texts)
    try:
        with closing(_open_cache(path)) as db:
            rows = db.execute(
                "SELECT source, translated FROM engine_translations "
                "WHERE engine = ? AND from_code = ? AND to_code = ?",
                (engine, from_code, to_code),
            )
            return {source: translated for source, translated in rows if source in wanted}
    except sqlite3.Error:
        return {}


def _save_cache(
    path: Path, engine: str, from_code: str, to_code: str, translations: dict[str, str]
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(_open_cache(path)) as db, db:
            db.executemany(
                "INSERT OR REPLACE INTO engine_translations VALUES (?, ?, ?, ?, ?)",
                [(engine, from_code, to_code, source, value) for source, value in translations.items()],
            )
    except (OSError, sqlite3.Error):
        pass
