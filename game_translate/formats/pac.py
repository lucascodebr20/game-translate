"""Reader/writer for the PAC scenario variant verified with DOSNESAN.

Commands and unknown text variants are kept byte-for-byte. The legacy renderer
uses Shift-JIS, so translated Latin accents are transliterated for compatibility.
"""
import re
import struct
import textwrap
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def swap(data):
    return bytes((x >> 4) | ((x & 15) << 4) for x in data)


@dataclass
class PacText:
    record: list
    prefix: bytes
    speaker: str
    voice: str
    original: str
    width: int
    replacement: bytes | None = None

    @property
    def text(self):
        return self.original.replace('\\n', ' ').strip()

    def set(self, value):
        if value == self.text:
            return
        value = unicodedata.normalize('NFKD', value)
        value = ''.join(c for c in value if not unicodedata.combining(c))
        value = value.translate(str.maketrans({
            '\u201c': '"', '\u201d': '"', '\u2019': "'", '\u2018': "'",
            '\u2014': '-', '\u2013': '-', '\u2026': '...', '\u00a0': ' ',
            '\u00ab': '"', '\u00bb': '"', '\u00b7': '.',
            '\u2665': '<3', '\u2661': '<3', '\u2764': '<3', '\ufe0f': '',
        }))
        # ASCII comma separates speaker/dialogue/voice fields in this engine.
        value = value.replace(',', '、')
        if any(ord(c) < 32 for c in value) or '\\' in value:
            raise ValueError('Tradução PAC contém controles ou barras não suportados.')
        value = '\\n'.join(textwrap.wrap(value, width=self.width, break_long_words=False,
                                       break_on_hyphens=False))
        try:
            payload = self.prefix + (self.speaker + value + self.voice).encode('cp932')
        except UnicodeEncodeError as exc:
            unsupported = exc.object[exc.start:exc.end]
            codes = ', '.join(f'U+{ord(c):04X}' for c in unsupported)
            raise ValueError(f'Texto não representável em Shift-JIS: {unsupported!r} ({codes}).') from exc
        if len(payload) + 2 > 65535:
            raise ValueError('Texto excede o limite de um registro PAC.')
        self.replacement = swap(payload)


class PacArchive:
    def __init__(self, data):
        self.data = data
        self.entries = []
        self.refs = []
        if len(data) < 7:
            raise ValueError('Cabeçalho PAC incompleto.')
        count, self.width, base = struct.unpack_from('<HBI', data)
        if not count or not self.width or base != 7 + count * (self.width + 8) or base > len(data):
            raise ValueError('Variante PAC não suportada.')
        expected = 0
        for i in range(count):
            pos = 7 + i * (self.width + 8)
            name_bytes = data[pos:pos + self.width]
            name = name_bytes.split(b'\0')[0].decode('cp932')
            offset, size = struct.unpack_from('<II', data, pos + self.width)
            if offset != expected or base + offset + size > len(data):
                raise ValueError(f'Índice PAC inválido: {name}')
            expected += size
            block = data[base + offset:base + offset + size]
            records = None
            if not name.startswith('_'):
                records = self._parse_script(name, block)
            self.entries.append((name_bytes, block, records))
        if base + expected != len(data):
            raise ValueError('Dados extras no arquivo PAC.')

    def _parse_script(self, name, block):
        if len(block) < 4:
            raise ValueError(f'Script PAC incompleto: {name}')
        count = struct.unpack_from('<I', block)[0]
        pos = 4
        records = []
        for _ in range(count):
            if pos + 4 > len(block):
                raise ValueError(f'Registro PAC incompleto: {name}')
            length, opcode = struct.unpack_from('<HH', block, pos)
            end = pos + length + 2
            if length < 2 or end > len(block):
                raise ValueError(f'Tamanho PAC inválido: {name}')
            record = [opcode, block[pos + 4:end], None]
            records.append(record)
            if opcode == 0:
                decoded = swap(record[1])
                # Unknown variants (including malformed original lines) stay intact.
                if decoded[:2] in (b'\x00\x00', b'\x20\x00', b'\x30\x00', b'\x50\x00', b'\x60\x00', b'\x70\x00'):
                    flags = decoded[0]
                    text = decoded[2:].decode('cp932')
                    speaker = voice = ''
                    if flags:
                        speaker, sep, text = text.partition(',')
                        if not sep:
                            raise ValueError(f'Diálogo PAC sem personagem: {name}')
                        speaker += sep
                    if flags in (0x30, 0x50, 0x70):
                        text, sep, voice = text.rpartition(',')
                        if not sep or not re.fullmatch(r'[A-Za-z0-9_]+', voice):
                            raise ValueError(f'Diálogo PAC sem identificador de voz: {name}')
                        voice = sep + voice
                    if any(c.isalpha() for c in text):
                        width = max(30, min(40, max(map(len, text.split('\\n')))))
                        ref = PacText(record, decoded[:2], speaker, voice, text, width)
                        record[2] = ref
                        self.refs.append(ref)
            pos = end
        if pos != len(block):
            raise ValueError(f'Contagem PAC inválida: {name}')
        return records

    def render(self):
        blocks = []
        index = bytearray()
        offset = 0
        for name, original, records in self.entries:
            block = original
            if records is not None:
                chunks = [struct.pack('<I', len(records))]
                for opcode, payload, ref in records:
                    if ref is not None and ref.replacement is not None:
                        payload = ref.replacement
                    chunks.append(struct.pack('<HH', len(payload) + 2, opcode) + payload)
                block = b''.join(chunks)
            index.extend(name + struct.pack('<II', offset, len(block)))
            blocks.append(block)
            offset += len(block)
        return self.data[:7] + bytes(index) + b''.join(blocks)


def load_pac(folder):
    return PacArchive((Path(folder) / 'srp.pac').read_bytes())


def detect_pac_language(folder):
    refs = load_pac(folder).refs
    japanese = sum(len(re.findall(r'[\u3040-\u30ff\u4e00-\u9fff]', ref.text)) for ref in refs)
    latin = sum(len(re.findall(r'[A-Za-z]', ref.text)) for ref in refs)
    return 'ja' if japanese > latin else 'en'
