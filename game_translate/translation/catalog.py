from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from game_translate.paths import MODELS_DIR


HUGGING_FACE = "https://huggingface.co/{repo}/resolve/{revision}/{name}"


NLLB_TOKENIZER = HUGGING_FACE.format(
    repo="facebook/nllb-200-distilled-600M",
    revision="f8d333a098d19b4fd9a8b18f94170487ad3f821d",
    name="sentencepiece.bpe.model",
)


NLLB_CODES = {
    "de": "deu_Latn",
    "en": "eng_Latn",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "ja": "jpn_Jpan",
    "pt": "por_Latn",
}


@dataclass(frozen=True)
class EngineInfo:
    id: str
    name: str
    description: str
    size: str
    files: tuple[tuple[str, str], ...] = ()

    @property
    def folder(self) -> Path:
        return MODELS_DIR / self.id

    def is_installed(self) -> bool:
        return all((self.folder / name).is_file() for name, _url in self.files)


def _hugging_face_files(repo: str, revision: str, *names: str) -> tuple[tuple[str, str], ...]:
    return tuple((name, HUGGING_FACE.format(repo=repo, revision=revision, name=name)) for name in names)


DEFAULT_ENGINE = "argos"


ENGINES = {
    "argos": EngineInfo(
        "argos",
        "Argos Translate",
        "O mais rápido. Bom para inglês; fraco para japonês, que passa pelo inglês.",
        "~100 MB por idioma",
    ),
    "nllb-600m": EngineInfo(
        "nllb-600m",
        "NLLB-200 600M (Meta)",
        "Traduz japonês direto, sem passar pelo inglês. De 4 a 7× mais lento que o Argos. "
        "Licença CC-BY-NC: somente uso não comercial.",
        "620 MB",
        _hugging_face_files(
            "JustFrederik/nllb-200-distilled-600M-ct2-int8",
            "302d78f00e6fdb50a1064059df7c392b735e9d05",
            "config.json",
            "model.bin",
            "shared_vocabulary.txt",
        )
        + (("sentencepiece.bpe.model", NLLB_TOKENIZER),),
    ),
    "nllb-1.3b": EngineInfo(
        "nllb-1.3b",
        "NLLB-200 1.3B (Meta)",
        "A melhor qualidade, principalmente em japonês. De 7 a 13× mais lento que o Argos. "
        "Licença CC-BY-NC: somente uso não comercial.",
        "1,4 GB",
        _hugging_face_files(
            "OpenNMT/nllb-200-distilled-1.3B-ct2-int8",
            "70f572adafa4794890ce7826156a4209717855af",
            "config.json",
            "model.bin",
            "shared_vocabulary.json",
        )
        + (("sentencepiece.bpe.model", NLLB_TOKENIZER),),
    ),
}
