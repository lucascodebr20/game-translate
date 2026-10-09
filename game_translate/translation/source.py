"""Shared source text ranges and language markers; no format parsing."""
import re

JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")


def render_source(source, refs):
    for ref in reversed(refs):
        if ref.replacement is not None:
            source = source[:ref.start] + ref.replacement + source[ref.end:]
    return source
