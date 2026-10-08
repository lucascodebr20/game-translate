import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vnm_game import VnmDocument, prepare
from translator_core import apply_translation, resolve_data_folder, translate_game


class VnmTests(unittest.TestCase):
    def fixture(self):
        return b"GS.dataCache['scene'] = " + json.dumps({
            'uid': 'scene', 'items': {'commands': [
                {'id': 'gs.ShowMessage', 'params': {'message': {'lcId': None, 'defaultText': 'Hello {GT:Player}!'}, 'characterId': 'hero'}},
                {'id': 'vn.Choice', 'params': {'text': {'lcId': 'choice', 'defaultText': 'Go home'}, 'action': {'label': 'home'}}},
                {'id': 'gs.Script', 'params': {'script': 'alert("Hello")'}}
            ], 'name': 'Internal scene'}}).encode()

    def test_roundtrip_and_strict_wrapper(self):
        for raw in (self.fixture(), prepare(self.fixture())):
            doc = VnmDocument(raw, 'scene')
            self.assertEqual(len(doc.refs), 2)
            doc.refs[0].set('Olá {GT:Player}!')
            result = VnmDocument(doc.render(), 'scene')
            self.assertEqual(result.refs[0].text, 'Olá {GT:Player}!')
            self.assertEqual(result.encoded, doc.encoded)
            self.assertEqual(result.data['items']['name'], 'Internal scene')
        with self.assertRaises(ValueError):
            VnmDocument(self.fixture() + b';alert(1)')
        with self.assertRaises(ValueError):
            VnmDocument(self.fixture(), 'other')

    def test_pipeline_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'game' / 'resources' / 'app'
            data = app / 'data'
            data.mkdir(parents=True)
            (app / 'index.html').write_text('<html></html>')
            (data / 'ENGINE.js').write_text('engine')
            (data / 'SUMMARIES.json.js').write_bytes(b"GS.dataCache['SUMMARIES'] = {}")
            original = prepare(self.fixture())
            (data / 'scene.json.js').write_bytes(original)
            for selected in (root / 'game', app, data):
                self.assertEqual(resolve_data_folder(selected), app)
            model = type('Model', (), {'translate': lambda self, texts, *args: ['Olá' for _ in texts]})()
            with patch('translator_core.ensure_translation_model'), patch('translator_core._create_models', return_value=[model]):
                output, count, files = translate_game(root / 'game', root / 'translated', cache_path=None)
            self.assertEqual((count, files), (2, 1))
            self.assertEqual((data / 'scene.json.js').read_bytes(), original)
            doc = VnmDocument((output / 'data' / 'scene.json.js').read_bytes())
            self.assertIn('{GT:Player}', doc.refs[0].text)
            self.assertEqual(doc.data['items']['commands'][1]['params']['action']['label'], 'home')
            backup = apply_translation(root / 'game', output)
            self.assertEqual((backup / 'data' / 'scene.json.js').read_bytes(), original)
            self.assertEqual((data / 'scene.json.js').read_bytes(), doc.render())
