from pathlib import Path

import pytest

import main
from mariana.albums import AlbumCatalog
from mariana.database import MarianaDatabase
from mariana.download_jobs import DownloadJobError, DownloadManager
from mariana.models import (
    AlbumRef,
    AlbumTrack,
    AlbumTrackStatus,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
)


def yt(video_id: str, title: str) -> MediaRef:
    return MediaRef(
        MediaSource.YOUTUBE,
        f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        artist="Artist",
        album="Album",
        resolver_data={"youtube": True, "video_id": video_id, "album_id": "album"},
    )


@pytest.fixture
def download_cli(monkeypatch, tmp_path: Path):
    database = MarianaDatabase(tmp_path / "downloads.db")
    manager = DownloadManager(database, autostart=False)
    album = AlbumRef(
        "album",
        "Album",
        album_artist="Album Artist",
        release_mbid="release",
        date="2001",
        country="US",
        tracks=[
            AlbumTrack(
                "Local",
                artist="Artist",
                position=1,
                media=MediaRef(MediaSource.LOCAL, str(tmp_path / "local.mp3"), title="Local"),
                resolution_status=AlbumTrackStatus.LOCAL,
            ),
            AlbumTrack(
                "Online",
                artist="Artist",
                position=2,
                track_number=2,
                media=yt("online", "Online"),
                resolution_status=AlbumTrackStatus.ONLINE,
            ),
            AlbumTrack(
                "Missing",
                artist="Artist",
                position=3,
                track_number=3,
                resolution_status=AlbumTrackStatus.UNRESOLVED,
            ),
        ],
    )

    class Albums:
        def fetch(self, reference):
            assert reference in {"album", "1", "https://www.youtube.com/playlist?list=PL1"}
            return album

        select_tracks = staticmethod(AlbumCatalog.select_tracks)

    printed = []
    monkeypatch.setattr(main, "DOWNLOADS", manager)
    monkeypatch.setattr(main, "ALBUMS", Albums())
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "current_media_type", None)
    monkeypatch.setattr(main, "currentsong", None)
    yield manager, album, printed
    manager.close()
    database.close()


def test_plain_download_is_current_track_only(monkeypatch, tmp_path: Path, download_cli):
    manager, _album, printed = download_cli
    media = yt("current", "Current")
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    )
    job = main.download_audio_command(["--yes", "--quality", "worst", "--to", str(tmp_path)])
    assert job.kind == "track" and job.quality == "worst"
    item = manager.items(job.job_id)[0]
    assert item.media.original_uri == "https://www.youtube.com/watch?v=current"
    assert item.media.resolver_data == {"youtube": True, "video_id": "current"}
    assert any("queued" in value for value in printed)


def test_explicit_track_does_not_expand_playlist(monkeypatch, tmp_path: Path, download_cli):
    manager, _album, _printed = download_cli
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    job = main.download_audio_command(
        [
            "https://www.youtube.com/watch?v=single&list=PL1",
            "--track",
            "--to",
            str(tmp_path),
            "--yes",
        ]
    )
    assert job.total_items == 1
    assert manager.items(job.job_id)[0].media.original_uri.endswith("watch?v=single")


def test_album_download_requires_partial_permission_and_skips_local(monkeypatch, tmp_path: Path, download_cli):
    manager, album, _printed = download_cli
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=album.tracks[1].media),
    )
    with pytest.raises(DownloadJobError, match="unresolved"):
        main.download_audio_command(["--album", "current", "--to", str(tmp_path), "--yes"])
    job = main.download_audio_command(
        [
            "--album",
            "current",
            "--allow-partial",
            "--missing-only",
            "--to",
            str(tmp_path),
            "--yes",
        ]
    )
    assert job.kind == "album" and job.album_id == "album" and job.total_items == 1
    item = manager.items(job.job_id)[0]
    assert item.metadata["track_number"] == 2
    assert item.metadata["release_mbid"] == "release"


def test_album_selector_can_reference_nonplaying_album(tmp_path: Path, download_cli):
    manager, _album, _printed = download_cli
    job = main.download_audio_command(
        ["--album", "1", "--tracks", "2", "--to", str(tmp_path), "--yes"]
    )
    assert manager.items(job.job_id)[0].media.title == "Online"


def test_download_confirmation_rejection_and_local_current(monkeypatch, tmp_path: Path, download_cli):
    manager, _album, printed = download_cli
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=yt("decline", "Decline")),
    )
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    assert main.download_audio_command(["--to", str(tmp_path)]) is None
    assert manager.status() == []
    assert any("cancelled" in value for value in printed)

    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(
            PlaybackState.PLAYING,
            media=MediaRef(MediaSource.LOCAL, str(tmp_path / "local.mp3")),
        ),
    )
    with pytest.raises(DownloadJobError, match="stored locally"):
        main.download_audio_command(["--yes"])


def test_download_status_pause_resume_cancel(tmp_path: Path, download_cli):
    manager, _album, printed = download_cli
    job = main.download_audio_command(
        ["https://www.youtube.com/watch?v=control", "--to", str(tmp_path), "--yes"]
    )
    main.download_audio_command(["status", job.job_id])
    main.download_audio_command(["pause", job.job_id])
    main.download_audio_command(["resume", job.job_id])
    main.download_audio_command(["cancel", job.job_id])
    assert manager.job(job.job_id).state.value == "cancelled"
    assert any(job.job_id in value for value in printed)
    with pytest.raises(DownloadJobError, match="Usage"):
        main.download_audio_command(["pause"])
