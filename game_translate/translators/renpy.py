"""Native Ren’Py translation adapter, including archived compiled scripts."""
from game_translate.formats.renpy import LANGUAGE, collect_strings, generate_sources, render
from game_translate.translation.source import JAPANESE
from game_translate.storage import copy_game
from game_translate.translators.base import Document, FolderOutput, check_cancelled


class RenpyTranslator(FolderOutput):
    description = 'Ren’Py: diálogos, escolhas e textos localizáveis. A saída é uma cópia completa do jogo com a tradução ativada.'

    def __init__(self):
        self._sources_key = None
        self._sources = None

    def sources(self, folder):
        files = sorted(path for path in (folder / 'game').rglob('*')
                       if path.is_file() and path.suffix in ('.rpa', '.rpy', '.rpyc', '.rpym', '.rpymc'))
        key = (folder, tuple((path, path.stat().st_size, path.stat().st_mtime_ns) for path in files))
        if key != self._sources_key:
            sources = generate_sources(folder)
            self._sources_key, self._sources = key, sources
        return self._sources

    def resolve(self, selected):
        folder = selected.parent if selected.name == 'game' else selected
        if (folder / 'renpy').is_dir() and (folder / 'game').is_dir() and (folder / 'lib').is_dir():
            return folder
        return None

    def language(self, folder):
        texts = [ref.text for path, source in self.sources(folder) if path.name != 'common.rpy'
                 for ref in collect_strings(source)]
        if not texts:
            return None
        return 'ja' if sum(bool(JAPANESE.search(text)) for text in texts) > len(texts) / 2 else 'en'

    def documents(self, folder, source_language):
        for path, source in self.sources(folder):
            refs = collect_strings(source)
            yield Document(path, refs, lambda source=source, refs=refs: render(source, refs))

    def write(self, folder, output, documents, progress=None, is_cancelled=None):
        check_cancelled(is_cancelled)
        # Native translation files do not exist in the source tree yet.
        copy_game(folder, output)
        changed = 0
        for document in documents:
            check_cancelled(is_cancelled)
            target = output / document.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(document.render())
            target.with_suffix('.rpyc').unlink(missing_ok=True)
            changed += 1
        (output / 'game' / 'zz_game_translate_language.rpy').write_text(
            'init 999 python:\n    config.language = "' + LANGUAGE + '"\n', encoding='utf-8')
        return changed

    def apply(self, original, translated):
        if not (translated / 'game' / 'tl' / LANGUAGE).is_dir():
            raise ValueError('A saída não contém a tradução Ren’Py gerada.')
        return super().apply(original, translated)
