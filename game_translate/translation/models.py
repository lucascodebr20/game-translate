from __future__ import annotations

from argostranslate import settings as argos_settings
from pathlib import Path
from typing import Callable
import argostranslate.package
import argostranslate.translate
import ctranslate2
import sentencepiece
import urllib.request
from game_translate.common import ProgressCallback, TranslationCancelled
from game_translate.translation.catalog import EngineInfo, NLLB_CODES
from game_translate.translation.text import INNER_SENTENCE_BREAK, SENTENCE


SENTENCES_PER_CALL = 512


MAX_BATCH_TOKENS = 256


def _find_installed_translation(from_code: str, to_code: str):
    installed = argostranslate.translate.get_installed_languages()
    source = next((lang for lang in installed if lang.code == from_code), None)
    target = next((lang for lang in installed if lang.code == to_code), None)
    if source is None or target is None:
        return None
    return source.get_translation(target)


def ensure_engine_files(
    engine: EngineInfo,
    progress: ProgressCallback | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    engine.folder.mkdir(parents=True, exist_ok=True)
    for name, url in engine.files:
        target = engine.folder / name
        if target.is_file():
            continue
        partial = target.with_name(target.name + ".part")
        try:
            with urllib.request.urlopen(url) as response, partial.open("wb") as handle:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                while chunk := response.read(1 << 20):
                    if is_cancelled and is_cancelled():
                        raise TranslationCancelled()
                    handle.write(chunk)
                    done += len(chunk)
                    if progress:
                        size = max(total, done)
                        progress(done, size, f"Baixando {engine.name} ({name}): {done >> 20} de {size >> 20} MB")
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        partial.replace(target)


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


def _load_ctranslate_model(folder: Path, inter_threads: int, intra_threads: int) -> ctranslate2.Translator:
    key = (str(folder), inter_threads, intra_threads)
    if key not in _ctranslate_models:
        _ctranslate_models[key] = ctranslate2.Translator(
            str(folder),
            device=argos_settings.device,
            inter_threads=inter_threads,
            intra_threads=intra_threads,
            compute_type=argos_settings.compute_type,
        )
    return _ctranslate_models[key]


def _translate_batch(translator: ctranslate2.Translator, tokenized: list[list[str]], target_prefix=None) -> list:
    return translator.translate_batch(
        tokenized,
        target_prefix=target_prefix,
        replace_unknowns=True,
        max_batch_size=MAX_BATCH_TOKENS,
        batch_type="tokens",
        beam_size=max(1, argos_settings.beam_size),
        num_hypotheses=1,
        length_penalty=0.2,
    )


class BatchModel:
    """Translates many paragraphs with one Argos model, sending sentences in batches."""

    def __init__(self, package_translation, inter_threads: int, intra_threads: int) -> None:
        self.pkg = package_translation.pkg
        self.sentencizer = package_translation.sentencizer
        self.translator = _load_ctranslate_model(self.pkg.package_path / "model", inter_threads, intra_threads)

    def split_sentences(self, paragraph: str) -> list[str]:
        if not paragraph.strip():
            return []
        if not INNER_SENTENCE_BREAK.search(paragraph):
            return [paragraph]
        return [sentence for sentence in self.sentencizer.split_sentences(paragraph) if sentence.strip()]

    def translate_sentences(self, sentences: list[str]) -> list[list[str]]:
        tokenized = [self.pkg.tokenizer.encode(sentence) for sentence in sentences]
        prefix = self.pkg.target_prefix
        results = _translate_batch(
            self.translator, tokenized, [[prefix]] * len(tokenized) if prefix else None
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


class NllbModel(BatchModel):
    """Translates directly between any two languages with an NLLB-200 model."""

    def __init__(
        self, engine: EngineInfo, from_code: str, to_code: str, inter_threads: int, intra_threads: int
    ) -> None:
        self.tokenizer = sentencepiece.SentencePieceProcessor(
            model_file=str(engine.folder / "sentencepiece.bpe.model")
        )
        self.source_language = NLLB_CODES[from_code]
        self.target_language = NLLB_CODES[to_code]
        self.translator = _load_ctranslate_model(engine.folder, inter_threads, intra_threads)

    def split_sentences(self, paragraph: str) -> list[str]:
        return [sentence.strip() for sentence in SENTENCE.findall(paragraph) if sentence.strip()]

    def translate_sentences(self, sentences: list[str]) -> list[list[str]]:
        tokenized = [
            [self.source_language] + self.tokenizer.encode(sentence, out_type=str) + ["</s>"]
            for sentence in sentences
        ]
        results = _translate_batch(self.translator, tokenized, [[self.target_language]] * len(tokenized))
        return [result.hypotheses[0][1:] for result in results]

    def decode(self, tokens: list[str]) -> str:
        return self.tokenizer.decode(tokens) if tokens else ""


def _create_models(
    engine: EngineInfo, from_code: str, to_code: str, inter_threads: int, intra_threads: int
) -> list[BatchModel]:
    if from_code == to_code:
        return []
    if engine.id == "argos":
        return [
            BatchModel(translation, inter_threads, intra_threads)
            for translation in _get_package_translations(from_code, to_code)
        ]
    return [NllbModel(engine, from_code, to_code, inter_threads, intra_threads)]
