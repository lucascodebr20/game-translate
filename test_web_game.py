import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_game import collect_source_strings, render_source
from translator_core import resolve_data_folder, translate_game, translate_text


class WebGameTests(unittest.TestCase):
    def test_english_dialogue_preserves_identifiers_and_assets(self):
        source = 'const scene={t:"That day, as always, the city was under attack.",label:"Go back",id:"scene_start",bg:"img/city.webp"}; $("saveButton").textContent="QUICK SAVE";'
        refs = collect_source_strings(source, 'js', 'en')
        self.assertEqual([r.text for r in refs], ['That day, as always, the city was under attack.', 'Go back', 'QUICK SAVE'])
        for ref in refs:
            ref.set('Texto traduzido')
        result = render_source(source, refs)
        self.assertIn('id:"scene_start"', result)
        self.assertIn('bg:"img/city.webp"', result)
        subprocess.run(['node', '--check'], input=result, text=True, encoding='utf-8', check=True, capture_output=True, timeout=15)

    def test_js_preserves_comments_dynamic_templates_and_escaping(self):
        source = '// 日本語\nconst a = "こんにちは"; const b = `名前${player}`; const c = "日本語\\n名前";'
        refs = collect_source_strings(source, "js")
        self.assertEqual([r.text for r in refs], ["こんにちは", "日本語\n名前"])
        for ref in refs:
            ref.set('Olá "amigo"\nTudo bem?')
        result = render_source(source, refs)
        self.assertIn('// 日本語', result)
        self.assertIn('`名前${player}`', result)
        self.assertIn(json.dumps('Olá "amigo"\nTudo bem?', ensure_ascii=False), result)
        subprocess.run(['node', '--check'], input=result, text=True, encoding='utf-8', check=True, capture_output=True, timeout=15)

    def test_html_preserves_code_and_escapes_text(self):
        source = '<button id="start">開始</button><script>const a="日本語";</script><style>/*日本語*/</style>'
        refs = collect_source_strings(source, "html")
        self.assertEqual([r.text for r in refs], ["開始"])
        refs[0].set('Iniciar & <continuar>')
        self.assertIn('Iniciar &amp; &lt;continuar&gt;', render_source(source, refs))

    def test_preserves_character_name_placeholder(self):
        self.assertEqual(translate_text('こんにちは〔名前〕', 'ja', 'pt', lambda s: 'Olá'), 'Olá〔名前〕')

    def test_web_pipeline_creates_separate_playable_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            www = root / 'game' / 'www'
            (www / 'js').mkdir(parents=True)
            (www / 'index.html').write_text('<button>開始</button>', encoding='utf-8')
            (www / 'js' / 'scene.js').write_text('const scene = {t:"こんにちは"};', encoding='utf-8')
            self.assertEqual(resolve_data_folder(www.parent), www)
            model = type('Model', (), {'translate': lambda self, texts, *args: ['Olá' for t in texts]})()
            with patch('translator_core.ensure_translation_model'), patch('translator_core._create_models', return_value=[model]):
                output, count, files = translate_game(www.parent, root / 'translated', 'ja', 'pt', cache_path=None)
            self.assertEqual((count, files), (2, 2))
            self.assertIn('Olá', (output / 'js' / 'scene.js').read_text(encoding='utf-8'))
            self.assertIn('こんにちは', (www / 'js' / 'scene.js').read_text(encoding='utf-8'))
