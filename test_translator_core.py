import unittest

from translator_core import collect_references, translate_text


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


if __name__ == "__main__":
    unittest.main()
