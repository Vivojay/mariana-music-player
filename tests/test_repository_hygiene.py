from pathlib import Path

from tools.clean_workspace import candidates, clean
from tools.verify_repository import MAX_TRACKED_BYTES, inspect, tracked_paths


def test_repository_guard_accepts_source_and_curated_media(tmp_path: Path):
    source = tmp_path / "mariana" / "player.py"
    media = tmp_path / "res" / "sample.mp3"
    source.parent.mkdir()
    media.parent.mkdir()
    source.write_text("print('ready')\n", encoding="utf-8")
    media.write_bytes(b"audio")

    assert inspect(tmp_path, [source.relative_to(tmp_path), media.relative_to(tmp_path)]) == []


def test_repository_guard_rejects_generated_private_legacy_and_large_files(tmp_path: Path):
    paths = {
        Path("build/output.txt"): b"generated",
        Path("data/mariana.db"): b"database",
        Path("user/private.pem"): b"secret",
        Path("help_future.md"): b"legacy",
        Path("large.bin"): b"x" * (MAX_TRACKED_BYTES + 1),
    }
    for relative, content in paths.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    failures = inspect(tmp_path, list(paths), [Path("large.bin")])

    assert any("generated/runtime root" in failure for failure in failures)
    assert any("artifact must not be tracked" in failure for failure in failures)
    assert any("legacy artifact" in failure for failure in failures)
    assert any("tracked file is also ignored" in failure for failure in failures)
    assert any("tracked-file limit" in failure for failure in failures)


def test_workspace_cleaner_preserves_dependencies_and_current_package_by_default(tmp_path: Path):
    generated = tmp_path / "build" / "output.bin"
    cache = tmp_path / "mariana" / "__pycache__" / "module.pyc"
    old_release = tmp_path / "release" / "published" / "old.exe"
    current_release = tmp_path / "release" / "win-unpacked" / "Mariana.exe"
    dependency = tmp_path / "node_modules" / "package" / "index.js"
    legacy_backup = tmp_path / "user" / "user_data.yml.pre-mariana-0.7.bak"
    for path in (generated, cache, old_release, current_release, dependency, legacy_backup):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"content")

    selected = candidates(tmp_path)

    assert generated.parent in selected
    assert cache.parent in selected
    assert old_release.parent in selected
    assert legacy_backup in selected
    assert current_release.parent not in selected
    assert dependency.parents[1] not in selected
    clean(selected, apply=True)
    assert not generated.exists()
    assert not cache.exists()
    assert not old_release.exists()
    assert not legacy_backup.exists()
    assert current_release.exists()
    assert dependency.exists()


def test_workspace_cleaner_dry_run_and_explicit_dependency_release_cleanup(tmp_path: Path):
    dependency = tmp_path / ".venv" / "python.exe"
    packaged = tmp_path / "release" / "win-unpacked" / "Mariana.exe"
    dependency.parent.mkdir()
    packaged.parent.mkdir(parents=True)
    dependency.write_bytes(b"python")
    packaged.write_bytes(b"app")
    selected = candidates(tmp_path, dependencies=True, release=True)

    removed, reclaimed = clean(selected, apply=False)

    assert (removed, reclaimed) == (0, 0)
    assert dependency.exists() and packaged.exists()
    clean(selected, apply=True)
    assert not dependency.exists() and not packaged.exists()


def test_current_tracked_repository_passes_hygiene_guard():
    root = Path(__file__).resolve().parents[1]
    paths = tracked_paths(root)
    assert inspect(root, paths) == []
