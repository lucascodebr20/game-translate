from game_translate.common import TranslationCancelled
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from game_translate import workflow
from game_translate import settings
from game_translate.translation import catalog, models
from game_translate.translation.catalog import ENGINES, EngineInfo
from game_translate.settings import load_settings, save_settings
from game_translate.translation.text import translate_text
from game_translate.formats.rpg_maker import MessageGroup, _wrap_lines, collect_references
from game_translate.translation.models import BatchModel, NllbModel, ensure_engine_files
from game_translate.translation.cache import _load_cache, _save_cache
from game_translate.workflow import translate_game


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
        with self.assertRaises(TranslationCancelled):
            FakeModel().translate(["Hello."], lambda done, total: None, lambda: True)


class CacheTests(unittest.TestCase):
    def test_round_trip_by_engine_and_language_pair(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.sqlite3"
            _save_cache(path, "argos", "en", "pt", {"Hello": "Olá"})

            self.assertEqual(_load_cache(path, "argos", "en", "pt", ["Hello", "Bye"]), {"Hello": "Olá"})
            self.assertEqual(_load_cache(path, "argos", "en", "es", ["Hello"]), {})
            self.assertEqual(_load_cache(path, "nllb-600m", "en", "pt", ["Hello"]), {})

    def test_migrates_cache_without_engine_to_argos(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.sqlite3"
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE translations (from_code TEXT, to_code TEXT, source TEXT, translated TEXT, "
                "PRIMARY KEY (from_code, to_code, source))"
            )
            db.execute("INSERT INTO translations VALUES ('en', 'pt', 'Hello', 'Olá')")
            db.commit()
            db.close()

            self.assertEqual(_load_cache(path, "argos", "en", "pt", ["Hello"]), {"Hello": "Olá"})


class SettingsTests(unittest.TestCase):
    def test_saves_engine_and_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            with mock.patch.object(settings, "SETTINGS_FILE", path):
                self.assertEqual(load_settings()["engine"], "argos")
                save_settings({"engine": "nllb-1.3b"})
                self.assertEqual(load_settings()["engine"], "nllb-1.3b")
                path.write_text('{"engine": "removido"}', encoding="utf-8")
                self.assertEqual(load_settings()["engine"], "argos")


class EngineDownloadTests(unittest.TestCase):
    def test_downloads_missing_files_only(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.bin"
            source.write_bytes(b"x" * 1000)
            engine = EngineInfo("teste", "Teste", "", "1 KB", (("model.bin", source.as_uri()),))
            messages: list[str] = []

            with mock.patch.object(catalog, "MODELS_DIR", Path(folder) / "models"):
                self.assertFalse(engine.is_installed())
                ensure_engine_files(engine, lambda done, total, message: messages.append(message))
                self.assertTrue(engine.is_installed())
                self.assertEqual((engine.folder / "model.bin").read_bytes(), b"x" * 1000)
                source.unlink()
                ensure_engine_files(engine)

            self.assertTrue(messages)

    def test_cancelled_download_leaves_no_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.bin"
            source.write_bytes(b"x" * 1000)
            engine = EngineInfo("teste", "Teste", "", "1 KB", (("model.bin", source.as_uri()),))

            with mock.patch.object(catalog, "MODELS_DIR", Path(folder) / "models"):
                with self.assertRaises(TranslationCancelled):
                    ensure_engine_files(engine, is_cancelled=lambda: True)
                self.assertEqual(list(engine.folder.iterdir()), [])


class SentenceSplitTests(unittest.TestCase):
    def test_splits_latin_and_japanese_sentences(self) -> None:
        model = NllbModel.__new__(NllbModel)

        self.assertEqual(
            model.split_sentences("Damn it... I can't! She said \"Go.\" Fine"),
            ["Damn it...", "I can't!", 'She said "Go."', "Fine"],
        )
        self.assertEqual(
            model.split_sentences("おい、お前！やっと目が覚めたか。「元気？」"),
            ["おい、お前！", "やっと目が覚めたか。", "「元気？」"],
        )


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
            workflow, "ensure_translation_model"
        ), mock.patch.object(workflow, "_create_models", side_effect=lambda *_args: [create_model()]):
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
        return models._get_package_translations(from_code, to_code)
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


@unittest.skipUnless(ENGINES["nllb-600m"].is_installed(), "modelo NLLB-200 600M não baixado")
class NllbModelTests(unittest.TestCase):
    def test_translates_every_sentence_of_a_line(self) -> None:
        model = NllbModel(ENGINES["nllb-600m"], "en", "pt", 2, 2)

        result = model.translate(
            ["Iron Sword", "My son went missing three days ago. Please, find him!"], lambda done, total: None
        )

        self.assertEqual(result[0], "Espada de Ferro")
        self.assertIn("três dias", result[1])
        self.assertIn("encontr", result[1].lower())


if __name__ == "__main__":
    unittest.main()
