from __future__ import annotations

from typing import Callable, Iterable
import argostranslate.translate
import re


CONTROL_CODE = re.compile(
    r"(?:(?:\{[^{}]*\}|〔[^〕]*〕|%[0-9]+|\\[A-Za-z]+(?:\[[^\]]*\])?|\\[{}.$|!><^]|\\\\|\x1b[A-Za-z]+(?:\[[^\]]*\])?))+"
)


JAPANESE_CHARACTER = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")


INNER_SENTENCE_BREAK = re.compile(r"[.!?。！？…‼⁉]+[\"'”’」』)\]）]*\s*\w")


LATIN_LINE_END = ".!?…:;\"”»)]"


JAPANESE_LINE_END = "。！？!?…」』）)】♪～"


JAPANESE_LINE_START = "「『【（("


NO_SPACE_LANGUAGES = {"ja", "zh"}


SENTENCE = re.compile(r".*?(?:[.!?。！？…‼⁉]+[\"'”’」』)\]）]*(?=\s|$)|[。！？]+[」』）)]*|$)\s*", re.S)


def _has_letter(value: str) -> bool:
    return any(character.isalpha() for character in value)


def _needs_translation(text: str, from_code: str) -> bool:
    if not _has_letter(text):
        return False
    return from_code != "ja" or JAPANESE_CHARACTER.search(text) is not None


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
