"""RPG Maker detection, JSON extraction and output serialization."""
import json

from game_translate.formats.rpg_maker import collect_references, iter_json_files
from game_translate.translators.base import Document, FolderOutput


class RpgMakerTranslator(FolderOutput):
    description = 'RPG Maker: diálogos, escolhas, nomes e descrições do banco de dados.'

    def resolve(self, selected):
        for candidate in (selected, selected / 'www/data', selected / 'data'):
            if (candidate / 'System.json').is_file() and any(candidate.glob('Map*.json')):
                return candidate
        return None

    def language(self, folder):
        return None  # Preserve the user's source language selection.

    def documents(self, folder, source_language):
        for path in iter_json_files(folder):
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            refs = collect_references(path.name, data, source_language)
            yield Document(path.relative_to(folder), refs,
                           lambda data=data: json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
