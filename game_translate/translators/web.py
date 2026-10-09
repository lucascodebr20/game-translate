"""Unpacked HTML/JavaScript game translation."""
from game_translate.formats.web import collect_source_strings, detect_web_language, render_source
from game_translate.translators.base import Document, FolderOutput


class WebTranslator(FolderOutput):
    description = 'HTML/JavaScript: textos estáticos dos arquivos JavaScript e HTML.'

    def resolve(self, selected):
        for candidate in (selected, selected / 'www'):
            if (candidate / 'index.html').is_file() and (candidate / 'js').is_dir():
                return candidate
        return None

    def language(self, folder):
        return detect_web_language(folder)

    def documents(self, folder, source_language):
        paths = sorted(folder.rglob('*.js')) + sorted(folder.rglob('*.html'))
        for path in paths:
            data = path.read_text(encoding='utf-8-sig')
            refs = collect_source_strings(data, 'js' if path.suffix == '.js' else 'html', source_language)
            yield Document(path.relative_to(folder), refs,
                           lambda data=data, refs=refs: render_source(data, refs).encode('utf-8'))
