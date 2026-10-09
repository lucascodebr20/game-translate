import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import game_translate.platform.windows_locale as module


ORIGINAL = {'locale': 'pt-BR', 'code_pages': {'ACP': '65001', 'OEMCP': '65001', 'MACCP': '10000'}}


class LocaleTests(unittest.TestCase):
    def test_repeated_enable_preserves_original_and_restore_recovers_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state.json'
            with patch.object(module, 'read_configuration', return_value=ORIGINAL) as read, patch.object(module, 'apply_configuration') as apply:
                module.enable_japanese(state)
                module.enable_japanese(state)
                read.assert_called_once()
                self.assertEqual(module.load_snapshot(state)['original'], ORIGINAL)
                self.assertEqual(apply.call_args.args[0]['code_pages']['ACP'], '932')
                module.restore_previous(state)
                apply.assert_called_with(ORIGINAL)
                self.assertFalse(module.load_snapshot(state)['active'])

    def test_cancelled_uac_retains_restore_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state.json'
            with patch.object(module, 'read_configuration', return_value=ORIGINAL), patch.object(module, 'apply_configuration', side_effect=OSError('cancelled')):
                with self.assertRaises(OSError):
                    module.enable_japanese(state)
                self.assertEqual(module.load_snapshot(state)['original'], ORIGINAL)
                with self.assertRaises(OSError):
                    module.restore_previous(state)
                self.assertTrue(module.load_snapshot(state)['active'])

    def test_restoration_without_snapshot_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(module, 'apply_configuration') as apply:
                with self.assertRaises(ValueError):
                    module.restore_previous(Path(temp) / 'missing.json')
                apply.assert_not_called()

    def test_script_rejects_injection_and_restores_exact_code_pages(self):
        script = module.build_change_script(ORIGINAL)
        self.assertIn("Set-WinSystemLocale -SystemLocale 'pt-BR'", script)
        self.assertIn("-Name 'ACP' -Value '65001'", script)
        with self.assertRaises(ValueError):
            module.build_change_script({**ORIGINAL, 'locale': "ja-JP'; exit; '"})
        with self.assertRaises(ValueError):
            module.build_change_script({**ORIGINAL, 'code_pages': {**ORIGINAL['code_pages'], 'ACP': '932;exit'}})

    def test_uac_launch_hidden_waits_and_propagates_failure(self):
        with patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            module.apply_configuration(ORIGINAL)
            args = run.call_args.args[0]
            script = base64.b64decode(args[-1]).decode('utf-16-le')
            self.assertIn('-Verb RunAs -WindowStyle Hidden -Wait -PassThru', script)
            self.assertIn('exit $p.ExitCode', script)
        for code in (1, 2):
            with patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([], code)):
                with self.assertRaises(OSError):
                    module.apply_configuration(ORIGINAL)


if __name__ == '__main__':
    unittest.main()
