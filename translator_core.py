from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import argostranslate.package
import argostranslate.translate
import ctranslate2
from argostranslate import settings as argos_settings


ProgressCallback = Callable[[int, int, str], None]

DATABASE_FIELDS = (
    "name",
    "nickname",
    "description",
    "profile",
    "message1",
    "message2",
    "message3",
    "message4",
)

DATABASE_FILES = {
    "Actors.json",
    "Armors.json",
    "Classes.json",
    "Enemies.json",
    "Items.json",
    "Skills.json",
    "States.json",
    "Weapons.json",
}

EVENT_FILES = {"CommonEvents.json", "Troops.json"}
CONTROL_CODE = re.compile(
    r"(?:(?:%[0-9]+|\\[A-Za-z]+(?:\[[^\]]*\])?|\\[{}.$|!><^]|\\\\|\x1b[A-Za-z]+(?:\[[^\]]*\])?))+"
)
JAPANESE_CHARACTER = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")
INNER_SENTENCE_BREAK = re.compile(r"[.!?。！？…‼⁉]+[\"'”’」』)\]）]*\s*\w")
LATIN_LINE_END = ".!?…:;\"”»)]"
JAPANESE_LINE_END = "。！？!?…」』）)】♪～"
JAPANESE_LINE_START = "「『【（("
NO_SPACE_LANGUAGES = {"ja", "zh"}

CACHE_FILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "TradutorRPGMaker" / "translation_cache.sqlite3"
SENTENCES_PER_CALL = 512
MAX_BATCH_TOKENS = 256


def _has_letter(value: str) -> bool:
    return any(character.isalpha() for character in value)


def _needs_translation(text: str, from_code: str) -> bool:
    if not _has_letter(text):
        return False
    return from_code != "ja" or JAPANESE_CHARACTER.search(text) is not None


class TranslationCancelled(Exception):
    pass


@dataclass
class TextReference:
    container: dict | list
    key: str | int

    @property
    def text(self) -> str:
        return self.container[self.key]

    def set(self, value: str) -> None:
        self.container[self.key] = value


@dataclass
class MessageGroup:
    """Consecutive message lines of one sentence, translated together and rewrapped."""

    lines: list[TextReference]
    joiner: str

    @property
    def text(self) -> str:
        return self.joiner.join(line.text.strip() for line in self.lines)

    def set(self, value: str) -> None:
        for line, wrapped in zip(self.lines, _wrap_lines(value, len(self.lines))):
            line.set(wrapped)


def _visible_length(text: str) -> int:
    return len(CONTROL_CODE.sub("", text))


def _wrap_lines(text: str, count: int) -> list[str]:
    words = text.split()
    total = sum(_visible_length(word) for word in words) + max(len(words) - 1, 0)
    target = total / count
    lines: list[str] = []
    for index in range(count - 1):
        line: list[str] = []
        length = 0
        while words and (not line or len(words) > count - index - 1):
            size = _visible_length(words[0]) + (1 if line else 0)
            if line and abs(length + size - target) >= abs(length - target):
                break
            line.append(words.pop(0))
            length += size
        lines.append(" ".join(line))
    lines.append(" ".join(words))
    return lines


def resolve_data_folder(selected: str | Path) -> Path:
    path = Path(selected).expanduser().resolve()
    candidates = (path, path / "www" / "data", path / "data")
    for candidate in candidates:
        if (candidate / "System.json").is_file() and any(candidate.glob("Map*.json")):
            return candidate
    raise ValueError(
        "Pasta de dados do RPG Maker MV não encontrada. Selecione a pasta do jogo, "
        "a pasta 'www' ou a pasta 'www/data'."
    )


def _find_installed_translation(from_code: str, to_code: str):
    installed = argostranslate.translate.get_installed_languages()
    source = next((lang for lang in installed if lang.code == from_code), None)
    target = next((lang for lang in installed if lang.code == to_code), None)
    if source is None or target is None:
        return None
    return source.get_translation(target)


def _ensure_direct_model(from_code: str, to_code: str) -> None:
    if _find_installed_translation(from_code, to_code) is not None:
        return

    argostranslate.package.update_package_index()
    package = next(
        (
            item
            for item in argostranslate.package.get_available_packages()
            if item.from_code == from_code and item.to_code == to_code
        ),
        None,
    )
    if package is None:
        raise RuntimeError(f"Modelo de tradução {from_code} → {to_code} não encontrado.")
    argostranslate.package.install_from_path(package.download())


def ensure_translation_model(from_code: str, to_code: str) -> None:
    if from_code == to_code or _find_installed_translation(from_code, to_code) is not None:
        return

    try:
        _ensure_direct_model(from_code, to_code)
        return
    except RuntimeError:
        if from_code == "en" or to_code == "en":
            raise

    _ensure_direct_model(from_code, "en")
    _ensure_direct_model("en", to_code)


def _add_string(container: dict | list, key: str | int, refs: list) -> None:
    value = container[key]
    if isinstance(value, str) and value.strip() and _has_letter(value):
        refs.append(TextReference(container, key))


def _line_continues(current: str, following: str, from_code: str) -> bool:
    current = CONTROL_CODE.sub("", current).strip()
    following = CONTROL_CODE.sub("", following).strip()
    if not current or not following:
        return False
    if from_code == "ja":
        if following[0] in JAPANESE_LINE_START or current.startswith("【"):
            return False
        if current.endswith(("、", "，")):
            return True
        return len(current) >= 6 and current[-1] not in JAPANESE_LINE_END
    if current[-1] in LATIN_LINE_END:
        return False
    first_letter = next((character for character in following if character.isalpha()), "")
    return first_letter.islower()


def _add_message_lines(lines: list[TextReference], refs: list, from_code: str) -> None:
    joiner = "" if from_code in NO_SPACE_LANGUAGES else " "
    group: list[TextReference] = []

    def flush() -> None:
        if len(group) == 1:
            refs.append(group[0])
        elif group:
            refs.append(MessageGroup(list(group), joiner))
        group.clear()

    for line in lines:
        if not (line.text.strip() and _has_letter(line.text)):
            flush()
            continue
        if group and not _line_continues(group[-1].text, line.text, from_code):
            flush()
        group.append(line)
    flush()


def _collect_event_commands(commands: object, refs: list, from_code: str) -> None:
    if not isinstance(commands, list):
        return
    message_lines: list[TextReference] = []
    message_code = None

    def flush_message() -> None:
        _add_message_lines(message_lines, refs, from_code)
        message_lines.clear()

    for command in commands:
        if not isinstance(command, dict):
            continue
        code = command.get("code")
        params = command.get("parameters")
        if not isinstance(params, list):
            continue
        if code in {401, 405} and params and isinstance(params[0], str):
            if code != message_code:
                flush_message()
                message_code = code
            message_lines.append(TextReference(params, 0))
            continue
        flush_message()
        message_code = None
        if code == 102 and params and isinstance(params[0], list):
            for index in range(len(params[0])):
                _add_string(params[0], index, refs)
        elif code == 402 and len(params) > 1:
            _add_string(params, 1, refs)
        elif code in {320, 324} and len(params) > 1:
            _add_string(params, 1, refs)
    flush_message()


def _walk_event_lists(value: object, refs: list, from_code: str) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("list"), list):
            _collect_event_commands(value["list"], refs, from_code)
        for child in value.values():
            _walk_event_lists(child, refs, from_code)
    elif isinstance(value, list):
        for child in value:
            _walk_event_lists(child, refs, from_code)


def collect_references(
    filename: str, data: object, from_code: str = "en"
) -> list[TextReference | MessageGroup]:
    refs: list[TextReference | MessageGroup] = []

    if filename in DATABASE_FILES and isinstance(data, list):
        for record in data:
            if isinstance(record, dict):
                for field in DATABASE_FIELDS:
                    if field in record:
                        _add_string(record, field, refs)

    if filename == "System.json" and isinstance(data, dict):
        for field in ("gameTitle", "currencyUnit"):
            if field in data:
                _add_string(data, field, refs)
        for field in ("armorTypes", "elements", "skillTypes", "weaponTypes"):
            values = data.get(field)
            if isinstance(values, list):
                for index in range(len(values)):
                    _add_string(values, index, refs)
        terms = data.get("terms")
        if isinstance(terms, dict):
            for values in terms.values():
                if isinstance(values, list):
                    for index in range(len(values)):
                        _add_string(values, index, refs)
                elif isinstance(values, dict):
                    for key in values:
                        _add_string(values, key, refs)

    if filename == "MapInfos.json" and isinstance(data, list):
        for record in data:
            if isinstance(record, dict) and "name" in record:
                _add_string(record, "name", refs)

    if filename.startswith("Map") and filename != "MapInfos.json" and isinstance(data, dict):
        if "displayName" in data:
            _add_string(data, "displayName", refs)
        _walk_event_lists(data.get("events"), refs, from_code)

    if filename in EVENT_FILES:
        _walk_event_lists(data, refs, from_code)

    return refs


def _map_segments(text: str, from_code: str, translate_body: Callable[[str], str]) -> str:
    """Applies translate_body to each translatable line between control codes."""

    def map_line(line: str) -> str:
        body = line.strip()
        if not _needs_translation(body, from_code):
            return line
        prefix = line[: len(line) - len(line.lstrip())]
        suffix = line[len(line.rstrip()) :]
        return prefix + (translate_body(body).strip() or body) + suffix

    def map_segment(segment: str) -> str:
        return "\n".join(map_line(line) for line in segment.split("\n"))

    result: list[str] = []
    position = 0
    for match in CONTROL_CODE.finditer(text):
        result.append(map_segment(text[position : match.start()]))
        result.append(match.group(0))
        position = match.end()
    result.append(map_segment(text[position:]))
    return "".join(result)


def _collect_bodies(texts: Iterable[str], from_code: str) -> list[str]:
    bodies: dict[str, None] = {}

    def remember(body: str) -> str:
        bodies.setdefault(body, None)
        return body

    for text in texts:
        _map_segments(text, from_code, remember)
    return list(bodies)


def translate_text(
    text: str,
    from_code: str,
    to_code: str,
    translate_function: Callable[[str], str] | None = None,
) -> str:
    translate = translate_function or (
        lambda body: argostranslate.translate.translate(body, from_code, to_code)
    )
    return _map_segments(text, from_code, translate)


def _package_translations(translation) -> list:
    if isinstance(translation, argostranslate.translate.CachedTranslation):
        return _package_translations(translation.underlying)
    if isinstance(translation, argostranslate.translate.CompositeTranslation):
        return _package_translations(translation.t1) + _package_translations(translation.t2)
    if isinstance(translation, argostranslate.translate.IdentityTranslation):
        return []
    if isinstance(translation, argostranslate.translate.PackageTranslation):
        return [translation]
    raise RuntimeError(f"Tipo de tradução não suportado: {type(translation).__name__}")


def _get_package_translations(from_code: str, to_code: str) -> list:
    direct = _find_installed_translation(from_code, to_code)
    if direct is not None:
        return _package_translations(direct)

    first = _find_installed_translation(from_code, "en")
    second = _find_installed_translation("en", to_code)
    if first is None or second is None:
        raise RuntimeError(
            f"Modelos de tradução {from_code} → en → {to_code} não estão instalados."
        )
    return _package_translations(first) + _package_translations(second)


_ctranslate_models: dict[tuple[str, int, int], ctranslate2.Translator] = {}


class BatchModel:
    """Translates many paragraphs with one Argos model, sending sentences in batches."""

    def __init__(self, package_translation, inter_threads: int, intra_threads: int) -> None:
        self.pkg = package_translation.pkg
        self.sentencizer = package_translation.sentencizer
        key = (str(self.pkg.package_path), inter_threads, intra_threads)
        if key not in _ctranslate_models:
            _ctranslate_models[key] = ctranslate2.Translator(
                str(self.pkg.package_path / "model"),
                device=argos_settings.device,
                inter_threads=inter_threads,
                intra_threads=intra_threads,
                compute_type=argos_settings.compute_type,
            )
        self.translator = _ctranslate_models[key]

    def split_sentences(self, paragraph: str) -> list[str]:
        if not paragraph.strip():
            return []
        if not INNER_SENTENCE_BREAK.search(paragraph):
            return [paragraph]
        return [sentence for sentence in self.sentencizer.split_sentences(paragraph) if sentence.strip()]

    def translate_sentences(self, sentences: list[str]) -> list[list[str]]:
        tokenized = [self.pkg.tokenizer.encode(sentence) for sentence in sentences]
        prefix = self.pkg.target_prefix
        results = self.translator.translate_batch(
            tokenized,
            target_prefix=[[prefix]] * len(tokenized) if prefix else None,
            replace_unknowns=True,
            max_batch_size=MAX_BATCH_TOKENS,
            batch_type="tokens",
            beam_size=max(1, argos_settings.beam_size),
            num_hypotheses=1,
            length_penalty=0.2,
        )
        hypotheses = [result.hypotheses[0] for result in results]
        if prefix:
            hypotheses = [tokens[1:] if tokens[:1] == [prefix] else tokens for tokens in hypotheses]
        return hypotheses

    def decode(self, tokens: list[str]) -> str:
        if not tokens:
            return ""
        value = self.pkg.tokenizer.decode(tokens)
        return value[1:] if value.startswith(" ") else value

    def translate(
        self,
        paragraphs: list[str],
        progress: Callable[[int, int], None],
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[str]:
        sentence_lists: list[list[str]] = []
        for paragraph in paragraphs:
            if is_cancelled and len(sentence_lists) % 200 == 0 and is_cancelled():
                raise TranslationCancelled()
            sentence_lists.append(self.split_sentences(paragraph))

        unique = list(dict.fromkeys(sentence for sentences in sentence_lists for sentence in sentences))
        translated: dict[str, list[str]] = {}
        progress(0, len(unique))
        for start in range(0, len(unique), SENTENCES_PER_CALL):
            if is_cancelled and is_cancelled():
                raise TranslationCancelled()
            chunk = unique[start : start + SENTENCES_PER_CALL]
            translated.update(zip(chunk, self.translate_sentences(chunk)))
            progress(len(translated), len(unique))

        return [
            self.decode([token for sentence in sentences for token in translated[sentence]])
            for sentences in sentence_lists
        ]


_CACHE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS translations ("
    "from_code TEXT NOT NULL, to_code TEXT NOT NULL, source TEXT NOT NULL, "
    "translated TEXT NOT NULL, PRIMARY KEY (from_code, to_code, source))"
)


def _load_cache(path: Path, from_code: str, to_code: str, texts: Iterable[str]) -> dict[str, str]:
    if not path.is_file():
        return {}
    wanted = set(texts)
    try:
        with closing(sqlite3.connect(path)) as db:
            db.execute(_CACHE_SCHEMA)
            rows = db.execute(
                "SELECT source, translated FROM translations WHERE from_code = ? AND to_code = ?",
                (from_code, to_code),
            )
            return {source: translated for source, translated in rows if source in wanted}
    except sqlite3.Error:
        return {}


def _save_cache(path: Path, from_code: str, to_code: str, translations: dict[str, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(_CACHE_SCHEMA)
            db.executemany(
                "INSERT OR REPLACE INTO translations VALUES (?, ?, ?, ?)",
                [(from_code, to_code, source, value) for source, value in translations.items()],
            )
    except (OSError, sqlite3.Error):
        pass


def iter_json_files(data_folder: Path) -> Iterable[Path]:
    ignored_markers = ("_backup", ".bak", "_original")
    for path in sorted(data_folder.glob("*.json")):
        if not any(marker in path.stem.lower() for marker in ignored_markers):
            yield path


def translate_game(
    selected_folder: str | Path,
    output_folder: str | Path,
    from_code: str = "en",
    to_code: str = "pt",
    progress: ProgressCallback | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    workers: int | None = None,
    cache_path: Path | None = CACHE_FILE,
) -> tuple[Path, int, int]:
    data_folder = resolve_data_folder(selected_folder)
    output = Path(output_folder).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"A pasta de saída já existe: {output}")
    if data_folder == output or data_folder in output.parents:
        raise ValueError("A saída não pode ficar dentro da pasta Data original.")

    if progress:
        progress(0, 1, "Preparando o modelo de tradução…")
    ensure_translation_model(from_code, to_code)

    documents: list[tuple[Path, object, list[TextReference | MessageGroup]]] = []
    unique_texts: dict[str, None] = {}
    for path in iter_json_files(data_folder):
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        refs = collect_references(path.name, data, from_code)
        documents.append((path, data, refs))
        for ref in refs:
            unique_texts.setdefault(ref.text, None)

    paragraphs = _collect_bodies(unique_texts, from_code)
    translations = _load_cache(cache_path, from_code, to_code, paragraphs) if cache_path else {}
    missing = [paragraph for paragraph in paragraphs if paragraph not in translations]
    if progress and translations:
        progress(0, 1, f"{len(translations)} de {len(paragraphs)} trechos recuperados do cache.")

    if missing:
        cpu_count = os.cpu_count() or 2
        inter_threads = max(1, min(workers or min(4, cpu_count // 4), 8))
        intra_threads = max(1, cpu_count // inter_threads)
        models = [
            BatchModel(translation, inter_threads, intra_threads)
            for translation in _get_package_translations(from_code, to_code)
        ]
        results = missing
        for number, model in enumerate(models, 1):
            stage = f"Etapa {number} de {len(models)} — " if len(models) > 1 else ""

            def report(done: int, total: int, stage: str = stage) -> None:
                if progress:
                    progress(done, total, f"{stage}Traduzindo: {done} de {total} frases")

            if progress:
                progress(0, 1, f"{stage}Separando frases…")
            results = model.translate(results, report, is_cancelled)
        new_translations = dict(zip(missing, results))
        translations.update(new_translations)
        if cache_path:
            _save_cache(cache_path, from_code, to_code, new_translations)

    final = {
        text: _map_segments(text, from_code, lambda body: translations.get(body, body))
        for text in unique_texts
    }

    shutil.copytree(data_folder, output)
    changed_files = 0
    for source, data, refs in documents:
        if not refs:
            continue
        for ref in refs:
            ref.set(final[ref.text])
        with (output / source.name).open("w", encoding="utf-8", newline="") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        changed_files += 1
    return output, len(final), changed_files


def apply_translation(original_data: str | Path, translated_data: str | Path) -> Path:
    original = resolve_data_folder(original_data)
    translated = Path(translated_data).expanduser().resolve()
    if not translated.is_dir():
        raise ValueError("Pasta traduzida não encontrada.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = original.parent / f"data_backup_{timestamp}"
    shutil.copytree(original, backup)
    shutil.copytree(translated, original, dirs_exist_ok=True)
    return backup
