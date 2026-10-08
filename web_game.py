"""Translate static display strings in unpacked HTML/JavaScript games.

No JavaScript is executed. Comments and dynamic template literals stay intact.
"""
import json
import re
from html import escape, unescape

TOKENS = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\[\s\S]|[^'\\])*'|\"(?:\\[\s\S]|[^\"\\])*\"|`(?:\\[\s\S]|[^`\\])*`")
JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
HTML_TOKENS = re.compile(r"<!--[\s\S]*?-->|<(script|style)\b[^>]*>[\s\S]*?</\1\s*>|<[^>]+>|[^<]+", re.I)


class SourceString:
    def __init__(self, source, start, end, text, kind):
        self.source, self.start, self.end = source, start, end
        self.text, self.kind = text, kind
        self.replacement = None

    def set(self, value):
        if value == self.text:
            return
        self.replacement = (json.dumps(value, ensure_ascii=False)
                            if self.kind == "js" else escape(value, quote=False))


DISPLAY_PROPERTY = re.compile(r'(?:\b(?:t|text|label|title|description|desc|message|caption|who|n|name)|["\'](?:t|text|label|title|description|desc|message|caption|who|n|name)["\'])\s*:\s*$')
DISPLAY_ASSIGNMENT = re.compile(r'\.(?:textContent|innerText)\s*=\s*$|\b(?:toast|sceneToast|alert|confirm)\(\s*$')


def collect_source_strings(source, kind, from_code="ja"):
    refs = []
    tokens = TOKENS if kind == "js" else HTML_TOKENS
    for match in tokens.finditer(source):
        raw = match.group()
        if kind == "js":
            if raw.startswith(("//", "/*")) or (raw.startswith("`") and "${" in raw):
                continue
            # Decode common JavaScript escapes without interpreting executable code.
            value = re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[\s\S])", _decode_escape, raw[1:-1])
        else:
            if raw.startswith("<"):
                continue
            value = unescape(raw)
        if kind == 'js' and re.match(r'\s*:', source[match.end():]):
            continue  # Object keys are identifiers, even when they look like prose.
        context = source[max(0, match.start() - 100):match.start()]
        display_context = DISPLAY_PROPERTY.search(context) or DISPLAY_ASSIGNMENT.search(context)
        eligible = (bool(JAPANESE.search(value)) if from_code == 'ja' else
                    any(c.isalpha() for c in value) and not JAPANESE.search(value)
                    and (kind == 'html' or bool(display_context)))
        if eligible:
            refs.append(SourceString(source, match.start(), match.end(), value, kind))
    return refs


def detect_web_language(folder):
    """Use scene display strings rather than Japanese developer comments."""
    counts = {"en": 0, "ja": 0}
    for path in (folder / 'js').glob('*.js'):
        source = path.read_text(encoding='utf-8-sig')
        for code in counts:
            counts[code] += sum(len(ref.text) for ref in collect_source_strings(source, 'js', code))
    return max(counts, key=counts.get)


def _decode_escape(match):
    value = match.group(1)
    if value.startswith(("u", "x")) and len(value) > 1:
        return chr(int(value[1:], 16))
    return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "\n": ""}.get(value, value)


def render_source(source, refs):
    for ref in reversed(refs):
        if ref.replacement is not None:
            source = source[:ref.start] + ref.replacement + source[ref.end:]
    return source
