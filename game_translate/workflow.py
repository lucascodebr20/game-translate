"""Coordinate translation models and game adapters without format-specific logic."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from game_translate.common import ProgressCallback
from game_translate.paths import CACHE_FILE
from game_translate.translation.cache import _load_cache, _save_cache
from game_translate.translation.catalog import DEFAULT_ENGINE, ENGINES
from game_translate.translation.models import _create_models, ensure_engine_files, ensure_translation_model
from game_translate.translation.text import _collect_bodies, _map_segments
from game_translate.translators.base import check_cancelled
from game_translate.translators.registry import resolve_game


def resolve_data_folder(selected: str | Path) -> Path:
    return resolve_game(selected)[1]


def translate_game(
    selected_folder: str | Path,
    output_folder: str | Path,
    from_code: str = "en",
    to_code: str = "pt",
    progress: ProgressCallback | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    workers: int | None = None,
    cache_path: Path | None = CACHE_FILE,
    engine_id: str = DEFAULT_ENGINE,
) -> tuple[Path, int, int]:
    translator, data_folder = resolve_game(selected_folder)
    output = Path(output_folder).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"A pasta de saída já existe: {output}")
    if data_folder == output or data_folder in output.parents:
        raise ValueError("A saída não pode ficar dentro da pasta Data original.")

    engine = ENGINES[engine_id]
    if progress:
        progress(0, 1, f"Preparando o modelo {engine.name}…")
    if engine.id == "argos":
        ensure_translation_model(from_code, to_code)
    else:
        ensure_engine_files(engine, progress, is_cancelled)

    documents = []
    unique_texts: dict[str, None] = {}
    for document in translator.documents(data_folder, from_code):
        check_cancelled(is_cancelled)
        documents.append(document)
        for ref in document.refs:
            unique_texts.setdefault(ref.text, None)

    paragraphs = _collect_bodies(unique_texts, from_code)
    if not paragraphs:
        raise ValueError("Nenhum texto traduzível encontrado. Confira o idioma de origem selecionado.")
    translations = _load_cache(cache_path, engine.id, from_code, to_code, paragraphs) if cache_path else {}
    missing = [paragraph for paragraph in paragraphs if paragraph not in translations]
    if progress and translations:
        progress(0, 1, f"{len(translations)} de {len(paragraphs)} trechos recuperados do cache.")

    if missing:
        cpu_count = os.cpu_count() or 2
        inter_threads = max(1, min(workers or min(4, cpu_count // 4), 8))
        intra_threads = max(1, cpu_count // inter_threads)
        models = _create_models(engine, from_code, to_code, inter_threads, intra_threads)
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
            _save_cache(cache_path, engine.id, from_code, to_code, new_translations)

    final = {
        text: _map_segments(text, from_code, lambda body: translations.get(body, body))
        for text in unique_texts
    }

    check_cancelled(is_cancelled)
    for document in documents:
        for ref in document.refs:
            ref.set(final[ref.text])
    changed_files = translator.write(data_folder, output, documents, progress, is_cancelled)
    return output, len(final), changed_files


def apply_translation(original_data: str | Path, translated_data: str | Path) -> Path:
    translator, original = resolve_game(original_data)
    translated = Path(translated_data).expanduser().resolve()
    if not translated.is_dir():
        raise ValueError("Pasta traduzida não encontrada.")
    if translated == original or original in translated.parents or translated in original.parents:
        raise ValueError("Selecione uma pasta traduzida separada do jogo original.")
    return translator.apply(original, translated)
