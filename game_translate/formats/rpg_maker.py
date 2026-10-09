from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from game_translate.translation.text import CONTROL_CODE, JAPANESE_LINE_END, JAPANESE_LINE_START, LATIN_LINE_END, NO_SPACE_LANGUAGES, _has_letter


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


def iter_json_files(data_folder: Path) -> Iterable[Path]:
    ignored_markers = ("_backup", ".bak", "_original")
    for path in sorted(data_folder.glob("*.json")):
        if not any(marker in path.stem.lower() for marker in ignored_markers):
            yield path
