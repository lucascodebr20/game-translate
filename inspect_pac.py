"""Extract text for inspection without modifying the original game."""
import argparse
import json
import struct
from pathlib import Path


def extract(path: Path):
    data = path.read_bytes()
    count, width, base = struct.unpack_from('<HBI', data)
    if base != 7 + count * (width + 8):
        raise ValueError('Unsupported PAC index')
    texts = []
    skipped = []
    for i in range(count):
        index = 7 + i * (width + 8)
        name = data[index:index + width].split(b'\0')[0].decode('cp932')
        offset, size = struct.unpack_from('<II', data, index + width)
        if base + offset + size > len(data):
            raise ValueError(f'Invalid entry: {name}')
        block = data[base + offset:base + offset + size]
        if name.startswith('_'):
            skipped.append(name)
            continue
        records = struct.unpack_from('<I', block)[0]
        pos = 4
        for record in range(records):
            length, opcode = struct.unpack_from('<HH', block, pos)
            end = pos + 2 + length
            if length < 2 or end > len(block):
                raise ValueError(f'Invalid record: {name}:{record}')
            if opcode == 0:
                payload = block[pos + 4:end]
                decoded = bytes((x >> 4) | ((x & 15) << 4) for x in payload)
                if len(decoded) < 2:
                    raise ValueError(f'Missing text flags: {name}:{record}')
                texts.append({
                    'script': name, 'record': record,
                    'flags_hex': decoded[:2].hex(),
                    'source': decoded[2:].decode('cp932'),
                    'translation': '',
                })
            pos = end
        if pos != len(block):
            raise ValueError(f'Trailing bytes: {name}')
    return {'source_archive': str(path.resolve()), 'entries': count,
            'skipped_system_entries': skipped, 'texts': texts}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = extract(args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Extracted {len(result['texts'])} text records from {result['entries']} entries")
