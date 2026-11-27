"""Compare completion data with executable CLI branches, including compatibility syntax."""
import ast
import json
import re
from pathlib import Path

import pytest

from mariana.commands import ALIAS_COMPATIBILITY, SEARCH_COMMANDS, is_search_command, normalize_command, parse_search

ROOT = Path(__file__).resolve().parents[1]
MAIN = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
FUNCTIONS = {node.name: node for node in MAIN.body if isinstance(node, ast.FunctionDef)}
CORE = json.loads((ROOT / 'mariana' / 'command_grammar_core.json').read_text(encoding='utf-8'))
STUDIO = json.loads((ROOT / 'mariana' / 'command_grammar_studio.json').read_text(encoding='utf-8'))
NATIVE = {name for catalog in (CORE, STUDIO) for rule in catalog['commands']
          if rule.get('surface', 'native') in {'native', 'both'}
          for name in (rule['path'], *rule.get('aliases', []))}
HEADS = {name.split()[0] for name in NATIVE}
# These specific dispatch branches print a usage error/deprecation notice. They do not
# perform the misspelled/retired operation and must stay out of completion suggestions.
DIAGNOSTIC_HEADS = {
    '.podbeans', '.pods', '/download', '/download-a', '/download-au', '/download-yt',
    'download-a', 'download-au', 'download-yt', 'isp', 'isp?', 'ispl',
    '/reddit-sessions', '/rs', 'vivojay',
}


def strings(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [v.value for v in node.elts if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return []


def test_dispatcher_routes_full_command_literals_and_normalization_aliases_are_covered():
    heads, whole_commands = set(), set()
    for node in ast.walk(FUNCTIONS['process']):
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'routed' for t in node.targets):
            heads.update(key.value for key in node.value.keys)
        if not isinstance(node, ast.Compare) or not isinstance(node.ops[0], (ast.In, ast.Eq)):
            continue
        expr = ast.unparse(node.left)
        target = node.comparators[0]
        if expr in ('commandslist[0]', 'commandslist[0].lower()', 'commandslist[0].casefold()'):
            heads.update(strings(target))
        elif expr in ('commandslist', 'commandslist[:2]'):
            alternatives = [target] if isinstance(node.ops[0], ast.Eq) else getattr(target, 'elts', [])
            for item in alternatives:
                words = strings(item)
                if words:
                    heads.add(words[0])
                    whole_commands.add(' '.join(words))
    assert heads - HEADS == DIAGNOSTIC_HEADS
    assert whole_commands - NATIVE == {'vivojay fav', 'vivojay favourite'}
    assert SEARCH_COMMANDS <= HEADS
    assert all(alias in NATIVE for group in ALIAS_COMPATIBILITY if group.status != 'retired' for alias in group.aliases)
    assert not HEADS.intersection(DIAGNOSTIC_HEADS)


@pytest.mark.parametrize(('handler', 'parent', 'variable'), [
    ('queue_command','queue','operation'), ('_queue_group_command','queue group','action'),
    ('playlist_command','playlist','operation'), ('album_command','album','operation'),
    ('library_command','library','operation'), ('replaygain_command','replaygain','operation'),
    ('broadcast_command','broadcast','operation'), ('youtube_auth_command','youtube auth','operation'),
    ('tools_command','tools','operation'), ('setup_command','setup','operation'),
    ('radio_command','radio','operation'), ('recommendation_command','recommend','operation'),
    ('station_command','station','operation'), ('stems_command','stems','operation'),
    ('focus_command','focus','operation'), ('crossfade_command','crossfade','operation'),
    ('discord_command','discord presence','operation'), ('room_command','room','operation'),
    ('session_command','session','operation'), ('chapters_command','chapters','action'),
    ('captions_command','captions','action'), ('avsync_command','avsync','action'),
    ('timed_lyrics_command','lyrics','operation'), ('media_command','media','operation'),
])
def test_every_named_handler_action_is_present(handler, parent, variable):
    actions = set()
    for n in ast.walk(FUNCTIONS[handler]):
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == variable:
            if isinstance(n.ops[0], (ast.Eq, ast.In)):
                actions.update(s for s in strings(n.comparators[0]) if not s.startswith('-') or s == '-')
    assert {f'{parent} {action}' for action in actions} <= NATIVE


def test_every_grammar_flag_in_selected_dispatchers_is_reachable_under_its_own_family():
    for family, functions in {
        'queue': ['queue_command','_queue_group_command'], 'playlist':['playlist_command'],
        'album':['album_command'], 'station':['station_command'], 'library':['library_command'],
        'download-ya':['download_audio_command','_download_album_job'], 'region':['region_command'],
        'media':['media_command'], 'rename':['rename_command'], 'lyrics':['timed_lyrics_command'],
        'thumb':['thumb_command'], 'hotspots':['hotspots_command'], 'play':['local_play_commands'],
    }.items():
        syntax_flags = {n.value for func in functions for n in ast.walk(FUNCTIONS[func])
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and re.fullmatch(r'--[a-z][a-z0-9-]*', n.value)}
        # Playlist prev/next inject --in internally before calling navigation_command.
        # The user cannot supply a second --in switch on these routes.
        if family == 'playlist':
            syntax_flags.discard('--in')
        declared = {flag for rule in CORE['commands'] if rule['path'].split()[0] == family
                    for flag in rule.get('flags', [])}
        assert syntax_flags <= declared, (family, syntax_flags - declared)


@pytest.mark.parametrize('head', ['.find17','.f3','.rfind3','.rf4','.lfind2','.lf8','+3','-2','.+7','.-4','.39','8'])
def test_parameterized_heads_align_with_native_parser_and_keep_literal_strings_intact(head):
    match = [r for r in CORE['headPatterns'] if re.fullmatch(r['pattern'], head, re.I)]
    assert len(match) == 1
    canonical = match[0]['canonical']
    if head.startswith(('.f','.r','.l')):
        assert is_search_command(head)
        assert parse_search([head, 'Björk']).result_index == int(re.search(r'\d+$',head)[0])
        assert canonical in SEARCH_COMMANDS
    elif '+' in head or '-' in head:
        assert normalize_command(head).split() == [canonical, re.search(r'\d+$',head)[0]]
    else:
        assert canonical == ''  # Bare and dotted library indices take no additional tokens.
