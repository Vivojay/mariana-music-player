import sqlite3
from types import SimpleNamespace

from mariana.terminal_library import library_rows


def test_cached_labels_follow_play_order_and_fall_back_without_probing_files(tmp_path):
    paths = [str(tmp_path / name) for name in ('raw.flac', 'broken.mp3', 'new.wav')]
    names = ['raw', 'broken', 'new']
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE library_files (canonical_path, metadata_json, state)')
        db.executemany('INSERT INTO library_files VALUES (?, ?, ?)', [
            (paths[1], 'invalid json', 'available'),
            (paths[0], '{"title":"Cut 2","artist":"A","album":"B"}', 'available'),
            (paths[2], '{"title":"Old title"}', 'missing'),
        ])
        result = library_rows(SimpleNamespace(fetchall=db.execute), names, paths)
    assert result == [
        ('Cut 2', 'A · B', 'play 1', paths[0]),
        ('broken', 'MP3 · ' + tmp_path.name, 'play 2', paths[1]),
        ('new', 'WAV · ' + tmp_path.name, 'play 3', paths[2]),
    ]
