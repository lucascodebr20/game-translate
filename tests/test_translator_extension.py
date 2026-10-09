"""A new game format can use the workflow without adding format branches."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_translate.translators.base import Document, FolderOutput
from game_translate.workflow import apply_translation, translate_game


class Reference:
    def __init__(self, text):
        self.text = text

    def set(self, value):
        self.text = value


class CustomTranslator(FolderOutput):
    description = 'Custom test format'

    def resolve(self, selected):
        return selected if (selected / 'dialogue.custom').is_file() else None

    def language(self, folder):
        return 'en'

    def documents(self, folder, source_language):
        ref = Reference((folder / 'dialogue.custom').read_text(encoding='utf-8'))
        yield Document(Path('dialogue.custom'), [ref], lambda: ref.text.encode('utf-8'))


class TranslatorExtensionTests(unittest.TestCase):
    def test_custom_format_translation_and_apply_without_workflow_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / 'game'
            game.mkdir()
            (game / 'dialogue.custom').write_text('Hello traveller', encoding='utf-8')
            (game / 'asset.bin').write_bytes(b'original asset')
            model = type('Model', (), {'translate': lambda self, texts, *args: ['Olá viajante' for _ in texts]})()
            with patch('game_translate.translators.registry.TRANSLATORS', (CustomTranslator(),)), \
                    patch('game_translate.workflow.ensure_translation_model'), \
                    patch('game_translate.workflow._create_models', return_value=[model]):
                output, texts, files = translate_game(game, root / 'translated', cache_path=None)
                self.assertEqual((texts, files), (1, 1))
                self.assertEqual((output / 'dialogue.custom').read_text(encoding='utf-8'), 'Olá viajante')
                self.assertEqual((game / 'dialogue.custom').read_text(encoding='utf-8'), 'Hello traveller')
                backup = apply_translation(game, output)
            self.assertEqual((backup / 'dialogue.custom').read_text(encoding='utf-8'), 'Hello traveller')
            self.assertEqual((game / 'asset.bin').read_bytes(), b'original asset')
