from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_translate.common import TranslationCancelled
from game_translate.storage import copy_game


class CopyProgressTests(unittest.TestCase):
    def test_large_file_reports_bytes_during_copy_and_preserves_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'original'
            (source / 'game/empty').mkdir(parents=True)
            archive = source / 'game/archive.rpa'
            archive.write_bytes(b'x' * (3 * 1024 * 1024 + 17))
            events = []
            with patch('game_translate.storage.monotonic', side_effect=range(100)):
                copy_game(source, root / 'output', lambda *event: events.append(event))
            self.assertEqual((root / 'output/game/archive.rpa').read_bytes(), archive.read_bytes())
            self.assertTrue((root / 'output/game/empty').is_dir())
            self.assertTrue(any(0 < done < total and 'archive.rpa' in status
                                for done, total, status in events))
            self.assertEqual(events[-1][:2], (archive.stat().st_size, archive.stat().st_size))

    def test_cancel_during_large_file_stops_before_copy_finishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'original'
            source.mkdir()
            archive = source / 'archive.rpa'
            archive.write_bytes(b'x' * 3 * 1024 * 1024)
            cancelled = False

            def progress(done, total, status):
                nonlocal cancelled
                if done > 0:
                    cancelled = True

            with patch('game_translate.storage.monotonic', side_effect=range(100)):
                with self.assertRaises(TranslationCancelled):
                    copy_game(source, root / 'output', progress, lambda: cancelled)
            self.assertLess((root / 'output/archive.rpa').stat().st_size, archive.stat().st_size)
            self.assertEqual(archive.stat().st_size, 3 * 1024 * 1024)

    def test_already_cancelled_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(TranslationCancelled):
                copy_game(root, root / 'output', is_cancelled=lambda: True)
            self.assertFalse((root / 'output').exists())
