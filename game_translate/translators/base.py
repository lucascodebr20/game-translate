"""Common contract for independent game format translators."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol

from game_translate.common import ProgressCallback, TranslationCancelled
from game_translate.storage import apply_folder, copy_game


class TextReference(Protocol):
    @property
    def text(self) -> str: ...
    def set(self, value: str) -> None: ...


@dataclass
class Document:
    path: Path
    refs: list[TextReference]
    render: Callable[[], bytes]


class GameTranslator(Protocol):
    description: str

    def resolve(self, selected: Path) -> Path | None: ...
    def language(self, folder: Path) -> str | None: ...
    def documents(self, folder: Path, source_language: str) -> Iterable[Document]: ...
    def write(self, folder: Path, output: Path, documents: list[Document],
              progress: ProgressCallback | None, is_cancelled: Callable[[], bool] | None) -> int: ...
    def apply(self, original: Path, translated: Path) -> Path: ...


def check_cancelled(is_cancelled):
    if is_cancelled and is_cancelled():
        raise TranslationCancelled()


class FolderOutput:
    """Shared filesystem operations for formats that produce a full folder."""

    def write(self, folder, output, documents, progress=None, is_cancelled=None):
        check_cancelled(is_cancelled)
        copy_game(folder, output)
        changed = 0
        for document in documents:
            check_cancelled(is_cancelled)
            if document.refs:
                (output / document.path).write_bytes(document.render())
                changed += 1
        return changed

    def apply(self, original, translated):
        return apply_folder(original, translated)
