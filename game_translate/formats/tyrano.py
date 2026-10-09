"""TyranoScript scenarios and NW.js executables with embedded ZIP data."""
import re
import zipfile
from html import escape, unescape
from pathlib import Path

from game_translate.translation.source import JAPANESE

TAG = re.compile(r'\[(?:[^\]"\']|"[^"]*"|\'[^\']*\')*\]')
ATTRIBUTE = re.compile(r'\btext\s*=\s*(["\'])(.*?)\1', re.S)
DISPLAY_TAGS = {'glink', 'ptext', 'tb_ptext_show', 'mtext'}


class TyranoString:
    def __init__(self, start, end, text, attribute=False):
        self.start, self.end, self.text = start, end, text
        self.attribute = attribute
        self.replacement = None

    def set(self, value):
        if value == self.text:
            return
        # Prevent model output from introducing executable scenario syntax.
        value = value.replace('[', '［').replace(']', '］')
        value = value.replace('\r', ' ').replace('\n', ' ')
        self.replacement = (escape(value, quote=True).replace(' ', '&nbsp;')
                            if self.attribute else value)


def collect_tyrano_strings(source, from_code='en'):
    refs = []
    blocked = None
    offset = 0
    for line in source.splitlines(keepends=True):
        stripped = line.lstrip()
        if blocked:
            if re.match(r'\[end' + blocked + r'\b', stripped, re.I):
                blocked = None
            offset += len(line)
            continue
        if stripped.startswith((';', '*', '#', '@')):
            offset += len(line)
            continue
        position = 0
        for match in TAG.finditer(line):
            _add_text(refs, line, position, match.start(), offset, from_code)
            tag_name = re.match(r'\[\s*(\w+)', match.group())
            name = tag_name.group(1).lower() if tag_name else ''
            if name in {'iscript', 'html'}:
                blocked = 'script' if name == 'iscript' else 'html'
                position = len(line)
                break
            if name in DISPLAY_TAGS:
                attribute = ATTRIBUTE.search(match.group())
                if attribute:
                    start = offset + match.start() + attribute.start(2)
                    value = unescape(attribute.group(2))
                    if value.strip() and not value.startswith('&') and (from_code != 'ja' or JAPANESE.search(value)):
                        refs.append(TyranoString(start, start + len(attribute.group(2)), value, True))
            position = match.end()
        _add_text(refs, line, position, len(line), offset, from_code)
        offset += len(line)
    return refs


def _add_text(refs, line, start, end, offset, code):
    raw = line[start:end]
    text = raw.strip()
    if not any(c.isalpha() for c in text):
        return
    if code == 'ja' and not JAPANESE.search(text):
        return
    left = len(raw) - len(raw.lstrip())
    refs.append(TyranoString(offset + start + left, offset + start + left + len(text), text))


def find_tyrano_executable(folder):
    for path in sorted(Path(folder).glob('*.exe')):
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if 'tyrano/plugins/kag/kag.js' in names and any(n.startswith('data/scenario/') and n.endswith('.ks') for n in names):
                    return path
        except (OSError, zipfile.BadZipFile):
            continue
    return None


def is_tyrano_game(folder):
    return ((folder / 'tyrano').is_dir() and (folder / 'data/scenario').is_dir()) or find_tyrano_executable(folder) is not None


def load_scenarios(folder):
    executable = find_tyrano_executable(folder)
    if executable:
        with zipfile.ZipFile(executable) as archive:
            return executable, [(Path(n), archive.read(n).decode('utf-8-sig')) for n in archive.namelist()
                                if n.startswith('data/scenario/') and n.endswith('.ks')]
    return None, [(p.relative_to(folder), p.read_text(encoding='utf-8-sig'))
                  for p in sorted((folder / 'data/scenario').rglob('*.ks'))]


def detect_tyrano_language(folder):
    _, scenarios = load_scenarios(folder)
    text = ''.join(ref.text for _, source in scenarios for ref in collect_tyrano_strings(source))
    return 'ja' if len(JAPANESE.findall(text)) > len(re.findall(r'[A-Za-z]', text)) else 'en'


def write_executable(source, target, replacements):
    with zipfile.ZipFile(source) as original:
        prefix_size = min(info.header_offset for info in original.infolist())
        with source.open('rb') as reader, target.open('wb') as writer:
            remaining = prefix_size
            while remaining:
                chunk = reader.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError('Executável NW.js incompleto.')
                writer.write(chunk)
                remaining -= len(chunk)
        with zipfile.ZipFile(target, 'a') as result:
            result.comment = original.comment
            for info in original.infolist():
                data = replacements.get(info.filename)
                result.writestr(info, original.read(info) if data is None else data)
    with zipfile.ZipFile(target) as result:
        bad = result.testzip()
        if bad:
            raise ValueError(f'Arquivo corrompido na saída: {bad}')
