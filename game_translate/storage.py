"""Filesystem copying and backup naming, independent of game formats."""
import shutil
import os
from pathlib import Path
from time import monotonic
from datetime import datetime

from game_translate.common import TranslationCancelled


def backup_path(original):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return original.parent / f'{original.name}_backup_{timestamp}'


def copy_game(original, output, progress=None, is_cancelled=None):
    """Copy in chunks so large archives also report progress and can be cancelled."""
    original = Path(original)

    def check_cancelled():
        if is_cancelled and is_cancelled():
            raise TranslationCancelled()

    check_cancelled()
    if progress:
        progress(0, 1, 'Calculando o tamanho da cópia do jogo…')
    total = 0
    for directory, _, files in os.walk(original):
        for name in files:
            check_cancelled()
            total += (Path(directory) / name).stat().st_size
    copied = 0
    last_report = 0.0

    def report(source, force=False):
        nonlocal last_report
        now = monotonic()
        if progress and (force or now - last_report >= 0.1):
            last_report = now
            relative = Path(source).relative_to(original)
            progress(copied, max(total, 1),
                     f'Copiando jogo: {copied / 1048576:.1f} de {total / 1048576:.1f} MB — {relative}')

    def copy_file(source, destination):
        nonlocal copied
        check_cancelled()
        report(source)
        with open(source, 'rb') as reader, open(destination, 'wb') as writer:
            while True:
                check_cancelled()
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
                copied += len(chunk)
                report(source)
        shutil.copystat(source, destination)
        return destination

    shutil.copytree(original, output, copy_function=copy_file)
    check_cancelled()
    if progress:
        progress(max(total, 1), max(total, 1), 'Cópia do jogo concluída. Gravando a tradução…')


def apply_folder(original, translated):
    backup = backup_path(original)
    shutil.copytree(original, backup)
    shutil.copytree(translated, original, dirs_exist_ok=True)
    return backup
