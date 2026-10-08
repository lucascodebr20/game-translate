import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import translator_core
from translator_core import (
    BatchModel,
    MessageGroup,
    _load_cache,
    _save_cache,
    _wrap_lines,
    collect_references,
    translate_game,
    translate_text,
)


class TranslateTextTests(unittest.TestCase):
    def test_collects_text_written_only_in_japanese(self) -> None:
        data = [{"name": "女神の復讐", "description": "このゲームは開発中です"}]

        references = collect_references("Items.json", data)

        self.assertEqual(
            [reference.text for reference in references],
            ["女神の復讐", "このゲームは開発中です"],
        )

    def test_preserves_rpg_maker_message_placeholders(self) -> None:
        source = "%1 has won and receives %2 %3!"

        translated = translate_text(
            source,
            "en",
            "pt",
            lambda text: text.replace("has won and receives", "venceu e recebe"),
        )

        self.assertEqual(translated, "%1 venceu e recebe %2 %3!")

    def test_preserves_placeholders_and_escape_codes_together(self) -> None:
        source = "You obtain %1\\G!"

        def translate(text: str) -> str:
            self.assertNotIn("%1", text)
            self.assertNotIn("\\G", text)
            return text.replace("You obtain", "Você obtém")

        translated = translate_text(
            source,
            "en",
            "pt",
            translate,
        )

        self.assertEqual(translated, "Você obtém %1\\G!")

    def test_keeps_source_segment_when_model_returns_empty_text(self) -> None:
        translated = translate_text("女神", "ja", "pt", lambda _text: "")

        self.assertEqual(translated, "女神")

    def test_skips_text_without_japanese_when_source_is_japanese(self) -> None:
        def translate(_text: str) -> str:
            raise AssertionError("não deveria traduzir")

        self.assertEqual(translate_text("Potion \\C[2]HP", "ja", "pt", translate), "Potion \\C[2]HP")

    def test_translates_each_line_of_multiline_text(self) -> None:
        translated = translate_text("Line one\nLine two", "en", "pt", str.upper)

        self.assertEqual(translated, "LINE ONE\nLINE TWO")


def _message(*lines: str) -> list[dict]:
    commands = [{"code": 101, "parameters": ["", 0, 0, 2]}]
    commands += [{"code": 401, "parameters": [line]} for line in lines]
    return commands + [{"code": 0, "parameters": []}]


class MessageGroupTests(unittest.TestCase):
    def test_joins_lines_of_the_same_sentence(self) -> None:
        commands = _message("I think that we should", "go north, my friend.", "Agreed?")

        references = collect_references("CommonEvents.json", [None, {"list": commands}])

        self.assertEqual(len(references), 2)
        self.assertIsInstance(references[0], MessageGroup)
        self.assertEqual(references[0].text, "I think that we should go north, my friend.")
        self.assertEqual(references[1].text, "Agreed?")

    def test_keeps_speaker_name_line_separate(self) -> None:
        commands = _message("\\C[6]Harold\\C[0]", "Welcome to our town.")

        references = collect_references("CommonEvents.json", [None, {"list": commands}])

        self.assertEqual([reference.text for reference in references], ["\\C[6]Harold\\C[0]", "Welcome to our town."])

    def test_japanese_lines_are_joined_without_spaces(self) -> None:
        commands = _message("勇者", "「今日はとても良い天気ですね、", "散歩に行こう。」")

        references = collect_references("CommonEvents.json", [None, {"list": commands}], "ja")

        self.assertEqual([reference.text for reference in references], ["勇者", "「今日はとても良い天気ですね、散歩に行こう。」"])

    def test_rewraps_translation_into_the_original_lines(self) -> None:
        commands = _message("I think that we should", "go north, my friend.")
        group = collect_references("CommonEvents.json", [None, {"list": commands}])[0]

        group.set("Acho que devemos ir para o norte, meu amigo.")

        self.assertEqual(
            [command["parameters"][0] for command in commands[1:3]],
            ["Acho que devemos ir para", "o norte, meu amigo."],
        )

    def test_wrap_keeps_line_count(self) -> None:
        self.assertEqual(_wrap_lines("Olá", 3), ["Olá", "", ""])
        self.assertEqual(_wrap_lines("um dois três", 3), ["um", "dois", "três"])


class FakeModel(BatchModel):
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.sentencizer = SimpleNamespace(split_sentences=lambda text: re.findall(r"[^.!?]+[.!?]*\s*", text))

    def translate_sentences(self, sentences: list[str]) -> list[list[str]]:
        self.calls.append(list(sentences))
        return [[sentence.strip().upper()] for sentence in sentences]

    def decode(self, tokens: list[str]) -> str:
        return " ".join(tokens)


class BatchModelTests(unittest.TestCase):
    def test_translates_each_repeated_sentence_once(self) -> None:
        model = FakeModel()

        result = model.translate(["Hi there. Bye now.", "Hi there.", ""], lambda done, total: None)

        self.assertEqual(result, ["HI THERE. BYE NOW.", "HI THERE.", ""])
        self.assertEqual(model.calls, [["Hi there. ", "Bye now.", "Hi there."]])

    def test_stops_when_cancelled(self) -> None:
        with self.assertRaises(translator_core.TranslationCancelled):
            FakeModel().translate(["Hello."], lambda done, total: None, lambda: True)


class CacheTests(unittest.TestCase):
    def test_round_trip_by_language_pair(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.sqlite3"
            _save_cache(path, "en", "pt", {"Hello": "Olá"})

            self.assertEqual(_load_cache(path, "en", "pt", ["Hello", "Bye"]), {"Hello": "Olá"})
            self.assertEqual(_load_cache(path, "en", "es", ["Hello"]), {})


class TranslateGameTests(unittest.TestCase):
    def _create_game(self, root: Path) -> Path:
        data = root / "www" / "data"
        data.mkdir(parents=True)
        (data / "System.json").write_text(json.dumps({"gameTitle": "Hero Quest"}), encoding="utf-8")
        events = [None, {"pages": [{"list": _message("Hello there, \\N[1]!", "Hello there, \\N[2]!")}]}]
        (data / "Map001.json").write_text(json.dumps({"displayName": "", "events": events}), encoding="utf-8")
        return data

    def test_translates_game_and_reuses_cache(self) -> None:
        models: list[FakeModel] = []

        def create_model(*_args) -> FakeModel:
            models.append(FakeModel())
            return models[-1]

        with tempfile.TemporaryDirectory() as folder, mock.patch.object(
            translator_core, "ensure_translation_model"
        ), mock.patch.object(translator_core, "_get_package_translations", return_value=[None]), mock.patch.object(
            translator_core, "BatchModel", side_effect=create_model
        ):
            root = Path(folder)
            self._create_game(root)
            cache = root / "cache.sqlite3"

            translate_game(root, root / "out1", cache_path=cache)
            translate_game(root, root / "out2", cache_path=cache)

            map_data = json.loads((root / "out1" / "Map001.json").read_text(encoding="utf-8"))
            lines = [command["parameters"][0] for command in map_data["events"][1]["pages"][0]["list"][1:3]]
            self.assertEqual(lines, ["HELLO THERE, \\N[1]!", "HELLO THERE, \\N[2]!"])
            self.assertEqual(models[0].calls, [["Hello there,", "Hero Quest"]])
            self.assertEqual(len(models), 1)
            self.assertEqual(
                (root / "out1" / "Map001.json").read_text(encoding="utf-8"),
                (root / "out2" / "Map001.json").read_text(encoding="utf-8"),
            )


def _installed_model(from_code: str, to_code: str):
    try:
        return translator_core._get_package_translations(from_code, to_code)
    except Exception:
        return None


@unittest.skipUnless(_installed_model("en", "pt"), "modelo en → pt não instalado")
class RealModelTests(unittest.TestCase):
    def test_batch_matches_argos_translation(self) -> None:
        import argostranslate.translate

        texts = [
            "Hello there, traveler! I haven't seen you around here before.",
            "Restores 50 HP to one ally.",
            "Be careful, monsters roam the forest at night.",
            "Iron Sword",
        ]
        model = BatchModel(_installed_model("en", "pt")[0], 2, 2)

        batched = model.translate(texts, lambda done, total: None)

        self.assertEqual(batched, [argostranslate.translate.translate(text, "en", "pt") for text in texts])


if __name__ == "__main__":
    unittest.main()
