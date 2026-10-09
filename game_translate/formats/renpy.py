"""Generate native translation units using the game's archive loader."""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from game_translate.translation.source import render_source

LANGUAGE = 'game_translate'
STRING = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
LINE = re.compile(r'^(?P<indent>\s+)(?P<prefix>.*?)\s*(?P<string>' + STRING
                  + r')(?P<suffix>(?:\s+(?:nointeract|with\s+[\w.]+))*\s*(?:#.*)?)$')
INTERPOLATION = re.compile(r'\[\[|\[(?:[^\[\]]|\[[^\[\]]*\])*\]')


def runtime(folder):
    scripts = sorted(folder.glob('*.py'))
    for script in scripts:
        if 'renpy.bootstrap' in script.read_text(encoding='utf-8', errors='replace'):
            for directory in ('py3-windows-x86_64', 'windows-x86_64', 'windows-i686'):
                python = folder / 'lib' / directory / 'python.exe'
                if python.is_file():
                    return python, script
    raise ValueError('Runtime Python do Ren’Py não encontrado na pasta do jogo.')


def generate_sources(folder):
    python, script = runtime(folder)
    with tempfile.TemporaryDirectory(prefix='game_translate_renpy_') as temporary:
        base = Path(temporary)
        # Ren’Py can recompile its common scripts. Keep those writes in the
        # temporary tree too, while reusing only the installed Python binary.
        shutil.copytree(folder / 'renpy', base / 'renpy')
        launcher = base / script.name
        shutil.copy2(script, launcher)

        def copy_file(source, target):
            if str(source).lower().endswith('.rpa'):
                try:
                    os.link(source, target)
                    return target
                except OSError:
                    pass
            return shutil.copy2(source, target)

        shutil.copytree(folder / 'game', base / 'game', copy_function=copy_file,
                        ignore=shutil.ignore_patterns('saves', 'cache'))
        # A fresh language ensures all units are generated, even on a second run.
        generated = base / 'game' / 'tl' / LANGUAGE
        if generated.exists():
            shutil.rmtree(generated)
        # Released games may keep .rpy/.rpyc only in archives. The engine's
        # generator otherwise skips those scripts because they are not loose files.
        (base / 'game' / 'zz_game_translate_extract.rpy').write_text('''init 999 python:
    import os
    for _gt_dir, _gt_name in renpy.loader.listdirfiles():
        if _gt_dir is None and _gt_name.endswith((".rpy", ".rpym")) and not _gt_name.startswith("tl/"):
            _gt_target = os.path.abspath(os.path.join(config.gamedir, _gt_name))
            if os.path.commonpath([config.gamedir, _gt_target]) != config.gamedir:
                raise Exception("Invalid archived script path")
            os.makedirs(os.path.dirname(_gt_target), exist_ok=True)
            with renpy.loader.load(_gt_name) as _gt_source:
                with open(_gt_target, "wb") as _gt_out:
                    _gt_out.write(_gt_source.read())
            config.translate_files.append(_gt_target)
    for _gt_filename in renpy.game.script.translator.file_translates:
        if _gt_filename not in config.translate_files:
            config.translate_files.append(_gt_filename)
''', encoding='utf-8')
        env = os.environ.copy()
        env.update(RENPY_DISABLE_SOUND='1', SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy',
                   PYTHONDONTWRITEBYTECODE='1')
        try:
            result = subprocess.run(
                [str(python), str(launcher), str(base), 'translate', LANGUAGE, '--no-todo'],
                cwd=base, env=env, capture_output=True, timeout=300,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError('O Ren’Py demorou demais para gerar os textos de tradução.') from error
        if result.returncode:
            detail = (result.stderr + result.stdout).decode('utf-8', errors='replace')[-3000:]
            raise ValueError(f'Não foi possível gerar traduções com o Ren’Py:\n{detail}')
        sources = [(path.relative_to(base), path.read_text(encoding='utf-8-sig'))
                   for path in sorted(generated.rglob('*.rpy'))]
        if not sources:
            raise ValueError('O Ren’Py não gerou textos traduzíveis para esse jogo.')
        return sources


class RenpyReference:
    def __init__(self, start, end, literal):
        self.start, self.end = start, end
        self.replacement = None
        self.controls = []
        value = ast.literal_eval(literal)

        def protect(match):
            token = '{__renpy_interpolation_%d}' % len(self.controls)
            self.controls.append((token, match.group()))
            return token

        self.text = INTERPOLATION.sub(protect, value)

    def set(self, value):
        for token, original in self.controls:
            value = value.replace(token, original)
        # Ren’Py literals accept Python escapes; retain Unicode and escape braces as-is.
        self.replacement = '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'


def collect_strings(source):
    refs = []
    mode = None
    offset = 0
    for line in source.splitlines(keepends=True):
        if line.startswith('translate '):
            mode = 'strings' if line.rstrip().endswith(' strings:') else 'dialogue'
        elif line.strip() and not line[0].isspace() and not line.startswith('#'):
            mode = None
        if mode and not line.lstrip().startswith('#'):
            match = LINE.match(line.rstrip('\r\n'))
            if match:
                prefix = match['prefix'].strip()
                valid = prefix == 'new' if mode == 'strings' else bool(
                    not prefix or re.fullmatch(r'[A-Za-z_][\w.]*(?:\s+(?:@\s*)?[\w-]+)*', prefix))
                if valid and (mode == 'strings' or prefix.split(' ')[0] not in ('old', 'new', 'voice', 'play', 'queue', 'scene', 'show', 'hide', 'window', 'call', 'jump', 'pause')):
                    refs.append(RenpyReference(offset + match.start('string'), offset + match.end('string'), match['string']))
        offset += len(line)
    return refs


def render(source, refs):
    return render_source(source, refs).encode('utf-8')
