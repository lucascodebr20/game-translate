"""Opt-in Windows legacy locale changes with a persistent restore snapshot."""
import base64
import ctypes
import json
import os
import re
import subprocess
from pathlib import Path


STATE_FILE = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'TradutorRPGMaker' / 'windows_locale.json'
NLS_KEY = r'SYSTEM\CurrentControlSet\Control\Nls'


def read_configuration():
    if os.name != 'nt':
        raise OSError('Esta opção está disponível somente no Windows.')
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, NLS_KEY + r'\Language') as key:
        lcid = winreg.QueryValueEx(key, 'Default')[0]
    name = ctypes.create_unicode_buffer(85)
    if not ctypes.windll.kernel32.LCIDToLocaleName(int(lcid, 16), name, len(name), 0):
        raise OSError('Não foi possível identificar a configuração regional do Windows.')
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, NLS_KEY + r'\CodePage') as key:
        pages = {field: winreg.QueryValueEx(key, field)[0] for field in ('ACP', 'OEMCP', 'MACCP')}
    return {'locale': name.value, 'code_pages': pages}


def load_snapshot(path=STATE_FILE):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    validate_configuration(data['original'])
    if not isinstance(data.get('active'), bool):
        raise ValueError('Backup da configuração regional inválido.')
    return data


def validate_configuration(config):
    if not re.fullmatch(r'[A-Za-z0-9-]{2,85}', config['locale']):
        raise ValueError('Idioma regional inválido.')
    for field in ('ACP', 'OEMCP', 'MACCP'):
        if not re.fullmatch(r'[0-9]{1,5}', str(config['code_pages'][field])):
            raise ValueError('Página de código inválida.')


def save_snapshot(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def build_change_script(config):
    validate_configuration(config)
    lines = ["$ErrorActionPreference = 'Stop'", 'try {',
             f"Set-WinSystemLocale -SystemLocale '{config['locale']}'",
             "$key = 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Nls\\CodePage'"]
    # Set-WinSystemLocale does not reliably disable the separate UTF-8 beta flag.
    # Restore exact code pages, including UTF-8 when that was the prior setting.
    for field in ('ACP', 'OEMCP', 'MACCP'):
        lines.append(f"Set-ItemProperty -LiteralPath $key -Name '{field}' -Value '{config['code_pages'][field]}'")
    lines.extend(['exit 0', '} catch { exit 1 }'])
    return '\n'.join(lines)


def _encoded(script):
    return base64.b64encode(script.encode('utf-16-le')).decode('ascii')


def apply_configuration(config):
    if os.name != 'nt':
        raise OSError('Esta opção está disponível somente no Windows.')
    payload = _encoded(build_change_script(config))
    bootstrap = ("$ErrorActionPreference = 'Stop'; try { "
                 "$p = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') "
                 f"-ArgumentList '-NoProfile -NonInteractive -EncodedCommand {payload}' "
                 "-Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode "
                 "} catch { exit 2 }")
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', _encoded(bootstrap)],
                            creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode == 2:
        raise OSError('A permissão de administrador foi cancelada ou não pôde ser solicitada.')
    if result.returncode:
        raise OSError('O Windows não concluiu a alteração. O backup foi preservado para restauração.')


def enable_japanese(path=STATE_FILE):
    snapshot = load_snapshot(path)
    if snapshot is None or not snapshot['active']:
        snapshot = {'original': read_configuration(), 'active': True}
        save_snapshot(snapshot, path)
    # Preserve the first snapshot even if enabling is repeated before a reboot.
    apply_configuration({'locale': 'ja-JP', 'code_pages': {'ACP': '932', 'OEMCP': '932', 'MACCP': '10001'}})
    return snapshot['original']['locale']


def restore_previous(path=STATE_FILE):
    snapshot = load_snapshot(path)
    if snapshot is None or not snapshot['active']:
        raise ValueError('Não há configuração anterior salva para restaurar.')
    apply_configuration(snapshot['original'])
    snapshot['active'] = False
    save_snapshot(snapshot, path)
    return snapshot['original']['locale']
