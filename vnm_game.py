"""Visual Novel Maker data wrappers; no game JavaScript is executed."""
import json
import re
from dataclasses import dataclass

SIGNATURE = bytes([42, 11, 22, 79, 43, 37, 14, 11, 24, 30])
WRAPPER = re.compile(r"\s*GS\.dataCache\[['\"]([^'\"]+)['\"]\]\s*=\s*")


def prepare(data):
    return bytes(value ^ SIGNATURE[index % len(SIGNATURE)] for index, value in enumerate(data))


def is_vnm_game(folder):
    return (folder / 'index.html').is_file() and (folder / 'data' / 'ENGINE.js').is_file() and (folder / 'data' / 'SUMMARIES.json.js').is_file()


@dataclass
class Reference:
    container: dict
    key: str

    @property
    def text(self):
        return self.container[self.key]

    def set(self, value):
        self.container[self.key] = value


class VnmDocument:
    def __init__(self, raw, expected_uid=None):
        self.encoded = not raw.lstrip().startswith(b'GS.dataCache[')
        source = (prepare(raw) if self.encoded else raw).decode('utf-8-sig')
        match = WRAPPER.match(source)
        if not match:
            raise ValueError('Arquivo Visual Novel Maker inválido.')
        self.prefix = source[:match.end()]
        self.uid = match[1]
        self.data = json.loads(source[match.end():].strip().rstrip(';'))
        if expected_uid is not None and self.uid != expected_uid:
            raise ValueError('Identificador Visual Novel Maker não corresponde ao arquivo.')
        self.refs = []
        self._walk(self.data)

    def _walk(self, value):
        if isinstance(value, dict):
            # Localizable values carry an lcId, including messages and choices.
            if 'lcId' in value and isinstance(value.get('defaultText'), str):
                if any(c.isalpha() for c in value['defaultText']):
                    self.refs.append(Reference(value, 'defaultText'))
            for child in value.values():
                self._walk(child)
        elif isinstance(value, list):
            for child in value:
                self._walk(child)

    def render(self):
        raw = (self.prefix + json.dumps(self.data, ensure_ascii=False, separators=(',', ':'))).encode('utf-8')
        return prepare(raw) if self.encoded else raw


def detect_vnm_language(folder):
    japanese = re.compile(r'[\u3040-\u30ff\u3400-\u9fff]')
    counts = {'en': 0, 'ja': 0}
    for path in (folder / 'data').glob('*.json.js'):
        for ref in VnmDocument(path.read_bytes(), path.name[:-8]).refs:
            counts['ja' if japanese.search(ref.text) else 'en'] += len(ref.text)
    return max(counts, key=counts.get)
