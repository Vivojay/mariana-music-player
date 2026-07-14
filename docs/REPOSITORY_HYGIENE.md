# Repository Hygiene

## Source map

| Path | Purpose |
|---|---|
| `main.py` | CLI entry point and compatibility command loop |
| `mariana/` | Current playback, queue, library, album, station, download, and persistence services |
| `desktop/` | Electron main/preload processes and React terminal UI |
| `lyrics_provider/` | Lyrics display and identification integration |
| `recommendation_engine/` | Local ranking and optional recommendation integrations |
| `beta/` | Legacy-named adapters still required by supported commands; new code should use `mariana/` |
| `res/` | Curated immutable media and lyric-window assets |
| `settings/` and `user/` | Packaged factory defaults only; mutable state belongs in the platform data directory |
| `tools/` | Verification, packaging, maintenance, and workspace-cleaning commands |
| `tests/` | Deterministic, real-process, opt-in live, and packaged acceptance tests |
| `docs/` | Architecture, security, testing, limitations, and recorded verification evidence |

Generated databases, settings, logs, downloads, models, and user history never
belong in the source tree. Mariana stores them in the platform-specific runtime
directory reported by `setup status`.

## Clean local outputs

Preview safe cleanup:

```powershell
python tools/clean_workspace.py
```

Remove test caches, build intermediates, stale duplicate release directories,
coverage reports, source-tree runtime state, and generated CSS:

```powershell
python tools/clean_workspace.py --apply
```

The default cleanup preserves `.venv`, `node_modules`, managed media tools, and
the current `release/win-unpacked` application. Remove those reproducible local
dependencies or the current package only when explicitly requested:

```powershell
python tools/clean_workspace.py --apply --dependencies --release
```

The cleaner is intentionally limited to repository-owned generated paths. It
does not inspect or delete user media or Mariana's platform data directory.

## Prevent artifact commits

Run the tracked-index guard locally:

```powershell
python tools/verify_repository.py
```

CI and signed-release workflows run the same command. It rejects:

- tracked files that are also ignored;
- build, release, dependency, cache, test, and runtime-state directories;
- retired files removed during the external-snapshot audit;
- databases, logs, archives, executables, signing material, and common secrets;
- individual tracked files larger than 5 MiB.

This check evaluates Git's tracked index, so `git add -f` cannot bypass it.
Curated media assets remain permitted under the size ceiling.
