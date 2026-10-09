"""TyranoScript scenarios, embedded NW.js output and patch validation."""
import zipfile

from game_translate.formats.tyrano import (
    collect_tyrano_strings, detect_tyrano_language, find_tyrano_executable,
    is_tyrano_game, load_scenarios, write_executable,
)
from game_translate.translation.source import render_source
from game_translate.storage import copy_game
from game_translate.translators.base import Document, FolderOutput, check_cancelled


class TyranoTranslator(FolderOutput):
    description = 'TyranoScript: diálogos, escolhas e rótulos. A saída é uma cópia do jogo, incluindo o executável e os arquivos necessários.'

    def resolve(self, selected):
        return selected if is_tyrano_game(selected) else None

    def language(self, folder):
        return detect_tyrano_language(folder)

    def documents(self, folder, source_language):
        _, scenarios = load_scenarios(folder)
        for relative, source in scenarios:
            refs = collect_tyrano_strings(source, source_language)
            yield Document(relative, refs,
                           lambda source=source, refs=refs: render_source(source, refs).encode('utf-8'))

    def write(self, folder, output, documents, progress=None, is_cancelled=None):
        executable = find_tyrano_executable(folder)
        if executable is None:
            return super().write(folder, output, documents, progress, is_cancelled)
        check_cancelled(is_cancelled)
        copy_game(folder, output, progress, is_cancelled)
        replacements = {}
        for document in documents:
            check_cancelled(is_cancelled)
            if document.refs:
                replacements[document.path.as_posix()] = document.render()
        if progress:
            progress(0, 1, 'Gravando e verificando o executável TyranoScript…')
        write_executable(executable, output / executable.name, replacements)
        return len(replacements)

    def apply(self, original, translated):
        executable = find_tyrano_executable(original)
        if executable:
            with zipfile.ZipFile(translated / executable.name) as archive:
                if archive.testzip():
                    raise ValueError('O executável traduzido contém arquivos corrompidos.')
        elif not is_tyrano_game(translated):
            raise ValueError('A saída não contém um jogo TyranoScript válido.')
        return super().apply(original, translated)
