from __future__ import annotations

from typing import Callable, Iterable


ProgressCallback = Callable[[int, int, str], None]


class TranslationCancelled(Exception):
    pass
