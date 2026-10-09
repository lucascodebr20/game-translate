"""Visual Novel Maker detection, decoded documents and validated output."""
from game_translate.formats.vnm import VnmDocument, detect_vnm_language, is_vnm_game
from game_translate.translators.base import Document, FolderOutput


class VnmTranslator(FolderOutput):
    description = 'Visual Novel Maker: diálogos, escolhas e textos localizáveis. Saída: cópia de resources/app.'

    def resolve(self, selected):
        for candidate in (selected, selected / 'resources/app', selected / 'app', selected.parent):
            if is_vnm_game(candidate):
                return candidate
        return None

    def language(self, folder):
        return detect_vnm_language(folder)

    def documents(self, folder, source_language):
        for path in sorted((folder / 'data').glob('*.json.js')):
            data = VnmDocument(path.read_bytes(), path.name[:-8])

            def render(data=data):
                result = data.render()
                VnmDocument(result, data.uid)
                return result

            yield Document(path.relative_to(folder), data.refs, render)

    def apply(self, original, translated):
        for path in (original / 'data').glob('*.json.js'):
            VnmDocument((translated / 'data' / path.name).read_bytes(), path.name[:-8])
        return super().apply(original, translated)
