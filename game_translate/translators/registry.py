"""Select an adapter; format-specific detection belongs to each adapter."""
from pathlib import Path

from game_translate.translators.base import GameTranslator
from game_translate.translators.pac import PacTranslator
from game_translate.translators.rpg_maker import RpgMakerTranslator
from game_translate.translators.tyrano import TyranoTranslator
from game_translate.translators.vnm import VnmTranslator
from game_translate.translators.web import WebTranslator
from game_translate.translators.renpy import RenpyTranslator

TRANSLATORS: tuple[GameTranslator, ...] = (
    RenpyTranslator(),
    TyranoTranslator(), PacTranslator(), VnmTranslator(), RpgMakerTranslator(), WebTranslator(),
)


def resolve_game(selected: str | Path) -> tuple[GameTranslator, Path]:
    selected = Path(selected).expanduser().resolve()
    for translator in TRANSLATORS:
        folder = translator.resolve(selected)
        if folder is not None:
            return translator, folder
    raise ValueError(
        "Jogo não encontrado. Selecione a pasta do jogo, 'www' ou 'www/data'. "
        'Formatos aceitos: Ren’Py, RPG Maker MV, HTML/JavaScript, TyranoScript, VNM e PAC de cenários (srp.pac).'
    )
