import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tyrano_game import collect_tyrano_strings
from web_game import render_source
from translator_core import resolve_data_folder, translate_game, apply_translation


class TyranoTests(unittest.TestCase):
    def test_scenarios_preserve_commands_scripts_and_variables(self):
        source = ('; comment\n*start\n#&f.PlayerName\nHello there[p]\n'
                  '[glink text="Go&nbsp;back" target="*start" storage="scene.ks"]\n'
                  '[iscript]\nf.internal="Do not translate";\n[endscript]\n'
                  'Your name: [emb exp="f.PlayerName"] welcome[p]\n')
        refs = collect_tyrano_strings(source)
        self.assertEqual([r.text for r in refs], ['Hello there', 'Go\xa0back', 'Your name:', 'welcome'])
        for ref in refs:
            ref.set('Olá "amigo" [x]\nTudo bem')
        result = render_source(source, refs)
        self.assertIn('f.internal="Do not translate";', result)
        self.assertIn('#&f.PlayerName', result)
        self.assertIn('[emb exp="f.PlayerName"]', result)
        self.assertIn('target="*start" storage="scene.ks"', result)
        self.assertIn('&quot;amigo&quot;', result)
        self.assertNotIn('[x]', result)

    def test_embedded_pipeline_preserves_runtime_assets_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / 'game'
            game.mkdir()
            exe = game / 'runtime.exe'
            stub = b'MZ' + b'fake-runtime' * 12
            exe.write_bytes(stub)
            with zipfile.ZipFile(exe, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('tyrano/plugins/kag/kag.js', '// runtime')
                archive.writestr('data/scenario/main.ks', '#Speaker\nHello there[p]\n[glink text="Continue" target="*next"]')
                archive.writestr('data/image/asset.bin', b'unchanged')
                archive.writestr('package.json', '{"main":"app://./index.html"}')
            (game / 'dependency.dll').write_bytes(b'dependency')
            original = exe.read_bytes()
            self.assertEqual(resolve_data_folder(game), game)
            model = type('Model', (), {'translate': lambda self, texts, *args: ['Olá' for _ in texts]})()
            with patch('translator_core.ensure_translation_model'), patch('translator_core._create_models', return_value=[model]):
                output, count, files = translate_game(game, root / 'output', cache_path=None)
            self.assertEqual((count, files), (2, 1))
            self.assertEqual(exe.read_bytes(), original)
            self.assertTrue((output / exe.name).read_bytes().startswith(stub))
            self.assertEqual((output / 'dependency.dll').read_bytes(), b'dependency')
            with zipfile.ZipFile(output / exe.name) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read('data/image/asset.bin'), b'unchanged')
                self.assertIn('Olá[p]', archive.read('data/scenario/main.ks').decode())
            backup = apply_translation(game, output)
            self.assertEqual((backup / exe.name).read_bytes(), original)

    def test_unpacked_scenarios(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / 'game'
            (game / 'tyrano').mkdir(parents=True)
            (game / 'data/scenario').mkdir(parents=True)
            (game / 'data/scenario/main.ks').write_text('Hello[p]', encoding='utf-8')
            model = type('Model', (), {'translate': lambda self, texts, *args: ['Olá' for _ in texts]})()
            with patch('translator_core.ensure_translation_model'), patch('translator_core._create_models', return_value=[model]):
                output, _, _ = translate_game(game, Path(temporary) / 'output', cache_path=None)
            self.assertEqual((output / 'data/scenario/main.ks').read_text(encoding='utf-8'), 'Olá[p]')
