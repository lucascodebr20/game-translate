import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_translate.formats.renpy import collect_strings, render
from game_translate.translation.text import translate_text
from game_translate.translators.renpy import RenpyTranslator
from game_translate.workflow import translate_game, apply_translation


SOURCE = '''# Original dialogue must remain unchanged.
translate game_translate start_123:
    # hero "Hello [player]!"
    hero happy "Hello [player]!" # a comment
    "{b}Welcome{/b}, [player!q]."
    voice "audio/voice.ogg"
    $ status = "internal"

translate game_translate strings:
    old "Go home"
    new "Go home"
'''


class RenpyTests(unittest.TestCase):
    def test_dialogue_suffix_preserved(self):
        source = 'translate game_translate start_1:\n    hero "Hello" nointeract with dissolve\n'
        refs = collect_strings(source)
        self.assertEqual(len(refs), 1)
        refs[0].set('Olá')
        self.assertIn('hero "Olá" nointeract with dissolve', render(source, refs).decode('utf-8'))

    def test_native_units_and_interpolation(self):
        refs = collect_strings(SOURCE)
        self.assertEqual(len(refs), 3)
        seen = []
        for ref in refs:
            def translate(body):
                seen.append(body)
                return 'Olá "amigo"'
            ref.set(translate_text(ref.text, 'en', 'pt', translate))
        output = render(SOURCE, refs).decode('utf-8')
        self.assertIn('[player!q]', output)
        self.assertIn('[player]', output)
        self.assertIn('{b}', output)
        self.assertIn('old "Go home"', output)
        self.assertIn('voice "audio/voice.ogg"', output)
        self.assertIn('$ status = "internal"', output)
        self.assertFalse(any('player' in text for text in seen))
        for ref in refs:
            ast.literal_eval(ref.replacement)

    def test_workflow_output_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / 'novel'
            for name in ('game', 'renpy', 'lib'):
                (game / name).mkdir(parents=True)
            (game / 'game' / 'archive.rpa').write_bytes(b'unchanged')
            translator = RenpyTranslator()
            self.assertEqual(translator.resolve(game / 'game'), game)
            sources = [(Path('game/tl/game_translate/script.rpy'), SOURCE)]
            model = type('Model', (), {'translate': lambda self, texts, *args: ['Olá' for text in texts]})()
            with patch('game_translate.translators.renpy.generate_sources', return_value=sources) as generate, \
                    patch('game_translate.translators.registry.TRANSLATORS', (translator,)), \
                    patch('game_translate.workflow.ensure_translation_model'), \
                    patch('game_translate.workflow._create_models', return_value=[model]):
                self.assertEqual(translator.language(game), 'en')
                output, count, files = translate_game(game, root / 'translated', cache_path=None)
                self.assertEqual((count, files), (3, 1))
                generate.assert_called_once()
                self.assertIn('Olá', (output / sources[0][0]).read_text(encoding='utf-8'))
                self.assertIn('config.language', (output / 'game/zz_game_translate_language.rpy').read_text())
                self.assertFalse((game / 'game/tl').exists())
                backup = apply_translation(game, output)
            self.assertEqual((backup / 'game/archive.rpa').read_bytes(), b'unchanged')
            self.assertTrue((game / sources[0][0]).exists())

    def test_cache_refreshes_when_archive_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'game').mkdir()
            archive = folder / 'game/archive.rpa'
            archive.write_bytes(b'a')
            translator = RenpyTranslator()
            with patch('game_translate.translators.renpy.generate_sources', return_value=[]) as generate:
                translator.sources(folder)
                archive.write_bytes(b'changed')
                translator.sources(folder)
                self.assertEqual(generate.call_count, 2)
