"""Filesystem copying and backup naming, independent of game formats."""
import shutil
from datetime import datetime


def backup_path(original):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return original.parent / f'{original.name}_backup_{timestamp}'


def copy_game(original, output):
    shutil.copytree(original, output)


def apply_folder(original, translated):
    backup = backup_path(original)
    shutil.copytree(original, backup)
    shutil.copytree(translated, original, dirs_exist_ok=True)
    return backup
