import json

import pytest

from mariana.database import MarianaDatabase
from mariana.models import MediaSource
from mariana.podbean import PodbeanShelf, feed_url, show_slug


def feed(count=12):
    items = ''.join(f'<item><title>Part {n}</title><guid>part-{n}</guid>'
                    f'<enclosure url="https://media.example/{n}.mp3" type="audio/mpeg"/>'
                    '</item>' for n in range(1, count + 1))
    return f'<rss version="2.0"><channel><title>Night Show</title>{items}</channel></rss>'.encode()


def test_open_page_play_and_persist(tmp_path):
    db = MarianaDatabase(tmp_path / 'podcasts.sqlite3')
    calls = []
    shelf = PodbeanShelf(db, lambda url: calls.append(url) or feed())
    selected = []
    use = lambda media, play: selected.append((media, play))
    assert '1. Part 1' in shelf.command(['open', 'https://night.podbean.com/'], use)
    assert '11. Part 11' in shelf.command(['episodes', '2'], use)
    assert not selected
    shelf.command(['queue', '12'], use)
    shelf.command(['play', '12'], use)
    assert [now for _, now in selected] == [False, True]
    first = selected[0][0]
    assert first.stable_id == selected[1][0].stable_id
    assert first.original_uri == 'https://media.example/12.mp3'
    assert first.source == MediaSource.PODCAST and first.album == 'Night Show'
    assert 'Following night' in shelf.command(['follow'], use)
    shelf = PodbeanShelf(db, lambda _: pytest.fail('Shelf should be readable offline'))
    assert shelf.command(['list'], use) == 'night · Night Show'
    shelf.command(['unfollow', 'https://feed.podbean.com/night/feed.xml'], use)
    assert 'No followed' in shelf.command(['list'], use)
    assert calls == [feed_url('night')]


def test_faults_clear_failed_selection_and_public_search(tmp_path):
    db = MarianaDatabase(tmp_path / 'podcasts.sqlite3')
    directory = {'results': [
        {'collectionName': 'Real show', 'feedUrl': feed_url('night')},
        {'collectionName': 'Duplicate', 'feedUrl': feed_url('night')},
        {'collectionName': 'Other host', 'feedUrl': 'https://example.org/nope.xml'}]}
    loads = []
    def fetch(url):
        loads.append(url)
        if 'itunes.apple.com' in url:
            return json.dumps(directory).encode()
        return b'<html/>' if '/missing/' in url else feed()
    shelf = PodbeanShelf(db, fetch)
    assert shelf.command(['search', 'night', 'show'], None) == 'night · Real show'
    assert 'term=night+show' in loads[0]
    shelf.command(['open', 'night'], None)
    with pytest.raises(ValueError, match='between'):
        shelf.command(['queue', '99'], None)
    with pytest.raises(ValueError, match='enclosures'):
        shelf.command(['open', 'missing'], None)
    with pytest.raises(ValueError, match='first'):
        shelf.command(['play', '1'], None)


@pytest.mark.parametrize('invalid', [
    'https://night.podbean.com/e/episode', 'https://feed.podbean.com/night/feed.xml?token=secret',
    'https://attacker.podbean.com.evil.example/', 'https://user:password@night.podbean.com/',
    '../night', 'https://podbean.com', 'www', 'http://127.0.0.1', '-night', 'a' * 64,
])
def test_only_public_show_references(invalid):
    with pytest.raises(ValueError):
        show_slug(invalid)
