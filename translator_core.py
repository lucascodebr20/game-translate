from __future__ import annotations

import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import argostranslate.package
import argostranslate.translate
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


def _has_letter(value: str) -> bool:
    return any(character.isalpha() for character in value)


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


def _add_string(container: dict | list, key: str | int, refs: list[TextReference]) -> None:
    value = container[key]
    if isinstance(value, str) and value.strip() and _has_letter(value):
        refs.append(TextReference(container, key))


def _collect_event_commands(commands: object, refs: list[TextReference]) -> None:
    if not isinstance(commands, list):
        return
    for command in commands:
        if not isinstance(command, dict):
            continue
        code = command.get("code")
        params = command.get("parameters")
        if not isinstance(params, list):
            continue
        if code in {401, 405} and params:
            _add_string(params, 0, refs)
        elif code == 102 and params and isinstance(params[0], list):
            for index in range(len(params[0])):
                _add_string(params[0], index, refs)
        elif code == 402 and len(params) > 1:
            _add_string(params, 1, refs)
        elif code in {320, 324} and len(params) > 1:
            _add_string(params, 1, refs)


def _walk_event_lists(value: object, refs: list[TextReference]) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("list"), list):
            _collect_event_commands(value["list"], refs)
        for child in value.values():
            _walk_event_lists(child, refs)
    elif isinstance(value, list):
        for child in value:
            _walk_event_lists(child, refs)


def collect_references(filename: str, data: object) -> list[TextReference]:
    refs: list[TextReference] = []

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
        _walk_event_lists(data.get("events"), refs)

    if filename in EVENT_FILES:
        _walk_event_lists(data, refs)

    return refs


def _protect_codes(text: str) -> tuple[str, list[str]]:
    codes: list[str] = []

    def replace(match: re.Match[str]) -> str:
        codes.append(match.group(0))
        return f"ZXQCONTROL{len(codes) - 1}QXZ"

    return CONTROL_CODE.sub(replace, text), codes


def _restore_codes(text: str, codes: list[str]) -> str:
    for index, code in enumerate(codes):
        token = re.compile(rf"ZXQCONTROL\s*{index}\s*QXZ", re.IGNORECASE)
        text = token.sub(lambda _match, value=code: value, text)
    return text.strip()


def translate_text(
    text: str,
    from_code: str,
    to_code: str,
    translate_function: Callable[[str], str] | None = None,
) -> str:
    def translate_segment(segment: str) -> str:
        prefix = segment[: len(segment) - len(segment.lstrip())]
        suffix = segment[len(segment.rstrip()) :]
        body = segment.strip()
        if not body or not _has_letter(body):
            return segment
        translated = (
            translate_function(body)
            if translate_function
            else argostranslate.translate.translate(body, from_code, to_code)
        ).strip()
        return prefix + (translated or body) + suffix

    result: list[str] = []
    position = 0
    for match in CONTROL_CODE.finditer(text):
        result.append(translate_segment(text[position : match.start()]))
        result.append(match.group(0))
        position = match.end()
    result.append(translate_segment(text[position:]))
    return "".join(result)


def get_translation_engine(from_code: str, to_code: str):
    direct = _find_installed_translation(from_code, to_code)
    if direct is not None:
        return direct

    first = _find_installed_translation(from_code, "en")
    second = _find_installed_translation("en", to_code)
    if first is None or second is None:
        raise RuntimeError(
            f"Modelos de tradução {from_code} → en → {to_code} não estão instalados."
        )

    class PivotTranslation:
        def translate(self, text: str) -> str:
            return second.translate(first.translate(text))

    return PivotTranslation()


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

    documents: list[tuple[Path, object, list[TextReference]]] = []
    unique_texts: dict[str, None] = {}
    for path in iter_json_files(data_folder):
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        refs = collect_references(path.name, data)
        documents.append((path, data, refs))
        for ref in refs:
            unique_texts.setdefault(ref.text, None)

    translations: dict[str, str] = {}
    texts = list(unique_texts)
    total = len(texts)
    cpu_count = os.cpu_count() or 2
    worker_count = workers or min(4, max(1, cpu_count // 2))
    worker_count = max(1, min(worker_count, 8))
    argos_settings.inter_threads = worker_count
    argos_settings.intra_threads = max(1, cpu_count // worker_count)
    engine = get_translation_engine(from_code, to_code)

    if texts:
        first = texts[0]
        translations[first] = translate_text(
            first, from_code, to_code, engine.translate
        )
        completed = 1
        if progress:
            progress(completed, total, f"Traduzindo com {worker_count} threads: {completed} de {total}")

        def translate_one(source_text: str) -> tuple[str, str]:
            return source_text, translate_text(
                source_text, from_code, to_code, engine.translate
            )

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(translate_one, text) for text in texts[1:]]
            for future in as_completed(futures):
                if is_cancelled and is_cancelled():
                    for pending in futures:
                        pending.cancel()
                    raise TranslationCancelled()
                original, translated = future.result()
                translations[original] = translated
                completed += 1
                if progress:
                    progress(
                        completed,
                        total,
                        f"Traduzindo com {worker_count} threads: {completed} de {total}",
                    )

    shutil.copytree(data_folder, output)
    changed_files = 0
    for source, data, refs in documents:
        if not refs:
            continue
        for ref in refs:
            ref.set(translations[ref.text])
        with (output / source.name).open("w", encoding="utf-8", newline="") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        changed_files += 1
    return output, len(translations), changed_files


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
