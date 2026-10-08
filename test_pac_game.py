import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pac_game import PacArchive, detect_pac_language, swap
from translator_core import apply_translation, resolve_data_folder, translate_game, TranslationCancelled


def record(opcode, payload):
    return struct.pack('<HH', len(payload) + 2, opcode) + payload


def fixture():
    records = [record(0x20, b'\x00\x00\x01\x00BG001'),
               record(0, swap(b'\x30\x00Alice,Hello there.\\nHow are you?,C0100010001')),
               record(0, swap(b'\x00\x00A quiet morning.')),
               record(0, swap(b'\x41\x00\x01\x00')),
               record(0x10, b'\x20\x00target_script')]
    blocks = [(b'opening', struct.pack('<I', len(records)) + b''.join(records)),
              (b'_system', b'[SYSTEM]\nFont=original\n')]
    width = 20
    base = 7 + len(blocks) * (width + 8)
    index = b''
    offset = 0
    for name, block in blocks:
        index += name.ljust(width, b'\0') + struct.pack('<II', offset, len(block))
        offset += len(block)
    return struct.pack('<HBI', len(blocks), width, base) + index + b''.join(b for _, b in blocks)


class PacTests(unittest.TestCase):
    def test_portuguese_quotes_and_symbols_are_shift_jis_compatible(self):
        archive = PacArchive(fixture())
        archive.refs[0].set('Ela disse: \u00abOl\u00e1\u00bb! \u2665 \u2764\ufe0f \u00b7 fim \u2013 sim \u2014 claro')
        updated = PacArchive(archive.render())
        self.assertEqual(updated.refs[0].text, 'Ela disse: "Ola"! <3 <3 . fim - sim - claro')
        self.assertEqual(updated.refs[0].speaker, 'Alice,')
        self.assertEqual(updated.refs[0].voice, ',C0100010001')

    def test_roundtrip_and_preservation_after_longer_translation(self):
        original = fixture()
        archive = PacArchive(original)
        self.assertEqual(archive.render(), original)
        self.assertEqual(len(archive.refs), 2)
        self.assertEqual(archive.refs[0].text, 'Hello there. How are you?')
        archive.refs[0].set('Olá, como você está nesta manhã tão tranquila?')
        updated = PacArchive(archive.render())
        self.assertEqual(updated.refs[0].speaker, 'Alice,')
        self.assertEqual(updated.refs[0].voice, ',C0100010001')
        self.assertIn('Ola、 como voce esta', updated.refs[0].text)
        self.assertIn('\\n', updated.refs[0].original)
        self.assertEqual(updated.refs[1].original, archive.refs[1].original)
        self.assertEqual(updated.entries[1][1], archive.entries[1][1])
        for i in (0, 3, 4):
            self.assertEqual(updated.entries[0][2][i][:2], archive.entries[0][2][i][:2])

    def test_corruption_and_unsupported_text_rejected(self):
        for data in (b'', fixture()[:-1], fixture() + b'extra'):
            with self.assertRaises(ValueError):
                PacArchive(data)
        archive = PacArchive(fixture())
        for text in ('Hello\x00world', 'Hello\\command', 'Hello 😀', 'A' * 65536):
            with self.assertRaises(ValueError):
                archive.refs[0].set(text)

    def test_pipeline_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / 'game'
            game.mkdir()
            original = fixture()
            (game / 'srp.pac').write_bytes(original)
            (game / 'grd.pac').write_bytes(b'untouched graphics')
            self.assertEqual(resolve_data_folder(game), game)
            self.assertEqual(detect_pac_language(game), 'en')
            model = type('Model', (), {'translate': lambda self, texts, *args: ['Olá, bom dia!' for _ in texts]})()
            with patch('translator_core.ensure_translation_model'), patch('translator_core._create_models', return_value=[model]):
                output, count, files = translate_game(game, root / 'translated', cache_path=None)
            self.assertEqual((count, files), (2, 1))
            self.assertEqual([p.name for p in output.iterdir()], ['srp.pac'])
            self.assertEqual((game / 'srp.pac').read_bytes(), original)
            self.assertIn('Ola、 bom dia!', PacArchive((output / 'srp.pac').read_bytes()).refs[0].text)
            backup = apply_translation(game, output)
            self.assertEqual((backup / 'srp.pac').read_bytes(), original)
            self.assertEqual((game / 'srp.pac').read_bytes(), (output / 'srp.pac').read_bytes())
            self.assertEqual((game / 'grd.pac').read_bytes(), b'untouched graphics')

    def test_cancelled_cached_translation_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / 'game'
            game.mkdir()
            (game / 'srp.pac').write_bytes(fixture())
            with patch('translator_core.ensure_translation_model'), patch('translator_core._load_cache', return_value={
                'Hello there. How are you?': 'Bom dia', 'A quiet morning.': 'Bom dia'
            }):
                with self.assertRaises(TranslationCancelled):
                    translate_game(game, root / 'out', is_cancelled=lambda: True)
            self.assertFalse((root / 'out').exists())

    def test_invalid_patch_does_not_touch_original_or_create_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game, translated = root / 'game', root / 'translated'
            game.mkdir()
            translated.mkdir()
            (game / 'srp.pac').write_bytes(fixture())
            (translated / 'srp.pac').write_bytes(b'invalid')
            with self.assertRaises(ValueError):
                apply_translation(game, translated)
            self.assertEqual((game / 'srp.pac').read_bytes(), fixture())
            self.assertEqual(list(root.glob('game_backup_*')), [])

    def test_existing_temporary_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game, translated = root / 'game', root / 'translated'
            game.mkdir()
            translated.mkdir()
            (game / 'srp.pac').write_bytes(fixture())
            (translated / 'srp.pac').write_bytes(fixture())
            temporary = game / 'srp.pac.translation.tmp'
            temporary.write_bytes(b'existing user data')
            with self.assertRaises(FileExistsError):
                apply_translation(game, translated)
            self.assertEqual(temporary.read_bytes(), b'existing user data')
            self.assertEqual((game / 'srp.pac').read_bytes(), fixture())


if __name__ == '__main__':
    unittest.main()
