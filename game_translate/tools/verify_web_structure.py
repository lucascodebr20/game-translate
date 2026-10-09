"""Read-only structural check against an unpacked game's JavaScript files."""
import subprocess
import sys
from pathlib import Path
from game_translate.formats.web import collect_source_strings, render_source, detect_web_language

def main():
    root = Path(sys.argv[1]) / 'www'
    language = detect_web_language(root)
    files = texts = 0
    for path in (root / 'js').rglob('*.js'):
        source = path.read_text(encoding='utf-8-sig')
        refs = collect_source_strings(source, 'js', language)
        for ref in refs:
            ref.set('Structural test')
        result = subprocess.run(['node', '--check'], input=render_source(source, refs), text=True, encoding='utf-8', capture_output=True, timeout=15)
        if result.returncode:
            print(f'Syntax validation failed: {path.name}')
            sys.exit(1)
        files += 1
        texts += len(refs)
    print(f'Language: {language}. Validated {files} JavaScript files and {texts} string references; no game files changed.')


if __name__ == '__main__':
    main()
