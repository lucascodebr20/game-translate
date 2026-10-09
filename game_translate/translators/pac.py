"""PAC scenario translation and atomic patch application."""
import shutil
from pathlib import Path

from game_translate.formats.pac import PacArchive, detect_pac_language, load_pac
from game_translate.storage import backup_path
from game_translate.translators.base import Document, check_cancelled


class PacTranslator:
    description = 'PAC: a saída contém srp.pac. Acentos serão convertidos para letras simples por compatibilidade.'

    def resolve(self, selected):
        return selected if (selected / 'srp.pac').is_file() else None

    def language(self, folder):
        return detect_pac_language(folder)

    def documents(self, folder, source_language):
        archive = load_pac(folder)

        def render():
            result = archive.render()
            PacArchive(result)
            return result

        yield Document(Path('srp.pac'), archive.refs, render)

    def write(self, folder, output, documents, progress=None, is_cancelled=None):
        rendered = documents[0].render()
        check_cancelled(is_cancelled)
        output.mkdir(parents=True)
        (output / 'srp.pac').write_bytes(rendered)
        return 1

    def apply(self, original, translated):
        archive_path = translated / 'srp.pac'
        PacArchive(archive_path.read_bytes())
        backup = backup_path(original)
        backup.mkdir()
        shutil.copy2(original / 'srp.pac', backup / 'srp.pac')
        temporary = original / 'srp.pac.translation.tmp'
        created = False
        try:
            with temporary.open('xb') as handle:
                created = True
                handle.write(archive_path.read_bytes())
            temporary.replace(original / 'srp.pac')
        finally:
            if created:
                temporary.unlink(missing_ok=True)
        return backup
