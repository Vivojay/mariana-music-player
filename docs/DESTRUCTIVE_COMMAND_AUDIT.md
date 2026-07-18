# Destructive and target-mutating command audit

This audit applies the [playback projection contract](PLAYBACK_PROJECTION_CONTRACT.md)
target-binding rules to Mariana's current command surface. It covers filesystem,
library, queue, playlist, preference, credential, download, setup, and catalog
mutations. It is not a claim that every mutation is irreversible.

## Risk classification

- **Safe**: the command has an explicit scope, binds or resolves its target
  deterministically, validates availability, and performs the mutation
  transactionally or through an appropriate recoverable API.
- **Needs follow-up**: the current command is scoped and no wrong-target defect
  is known, but confirmation, revision binding, concurrency handling, recovery,
  or privacy tests are incomplete.
- **Unsafe**: a concrete path can overwrite user data or a confirmed target can
  be redirected without an explicit, revalidated overwrite contract.

## Findings

| Command or category | Current resolution and mutation behavior | Risk | Evidence |
| --- | --- | --- | --- |
| `rm|del <library-index|indexed-path>` | A numeric argument is resolved through the current available-library view, never the last search or queue. `RemovalTarget` binds library ID, resolved path, display index/title, and file signature. The service revalidates all fields immediately before `send2trash`, journals the filesystem/database boundary, and reconciles queue/library state. The explicit confirmation is the only normal surface where the canonical path is shown. | **Safe** | `main.py::recycle_library_media`; `mariana/media_removal.py::RemovalTarget`, `MediaRemovalService.resolve`, `_validate_bound_target`, and `remove`; `tests/test_media_removal.py`; `tests/test_main_helpers_and_commands.py::test_search_results_do_not_redirect_numeric_removal`. Global `remove` and `delete` are not aliases; only `rm` and `del` route here. |
| `rename short` and `--dry-run` | Library numbers use `LibraryCatalog.info`, independent of search/queue state. The command now binds library ID, resolved path, device/inode, size, and modification time before preview. Apply revalidates the same `LibraryRenameTarget`; a moved, replaced, missing, or reindexed file is refused. Rename remains same-directory/same-extension and rolls the filesystem back if the database transaction fails. | **Safe (fixed in this audit)** | `main.py::rename_command`; `mariana/library.py::LibraryRenameTarget`, `bind_rename`, `rename_bound`, and `rename`; `tests/test_media_details.py::test_bound_library_rename_refuses_replaced_or_moved_target`; rename tests in `tests/test_main_helpers_and_commands.py`. |
| Lyrics sidecar creation | `lyrics edit` binds the current local `MediaRef`, verifies the media file, confirms creation when the `.lrc` file is absent, writes a temporary file, and atomically replaces the destination. It does not overwrite an already-present sidecar during the initial check, but destination creation is not an atomic no-clobber operation if another process creates the sidecar during identification/confirmation. | **Needs follow-up** | `main.py::edit_current_lyrics`; confirmation coverage in `tests/test_cli_command_matrix.py`. Add an atomic create-if-absent boundary and a race regression test. |
| `library clean --missing` | This is an explicitly global, confirmed database cleanup and never deletes media files. It removes all rows that are missing at execution time, including a tombstone created while the prompt is open; no pre-confirmation ID set or generation is bound. A later scan can recreate occurrences. | **Needs follow-up** | `main.py::library_command`; `mariana/library.py::clean_missing`; `tests/test_library_cli.py` and `tests/test_library_indexer.py`. Bind the confirmed tombstone ID set or label the operation explicitly as execution-time global state. |
| Library job/loudness mutations | `library retry <target>` and `replaygain rescan <target>` resolve library numbers/paths through `LibraryCatalog.info`, then mutate by stable library ID. Missing targets fail. Loudness removal is regenerable. Explicit `library info/errors` may show paths because they are local inspection commands. | **Safe** | `main.py::library_command`, `replaygain_command`; `mariana/library.py::retry`; `mariana/loudness.py::delete`. Add a search-state poisoning regression test for numeric rescan/retry for parity with removal. |
| Queue item/group mutations | `queue remove/move/swap/jump` positions and hierarchical paths are explicitly queue-scoped. Queue methods capture queue/group IDs, mutate in SQLite transactions, validate range/group/cycle/depth, and record undo history. Search and bare library numbering do not participate. `queue clear` is confirmed; reset/load/order/dedupe are explicit queue-wide operations with history where structural state changes. | **Safe** | `main.py::queue_command`, `_queue_group_command`; `mariana/queueing.py::remove`, `move`, `swap`, `remove_group`, `clear`, and `undo`; `tests/test_main_queue_edges.py`; hierarchy/property coverage in `tests/test_hierarchical_queue_and_playlists.py` and `tests/test_hierarchy_album_download_edges.py`. |
| Queue/playlist display labels | Queue list/tree and some desktop/playlist payloads fall back to `MediaRef.original_uri` when title is absent. That can expose a local path or online URL on a surface that only needs a safe label. It does not redirect mutations, but it violates the projection privacy rule. | **Needs follow-up** | `main.py::queue_command`, `_print_queue_tree`, `_queue_node_payload`, and `playlist_command`. Reuse a sanitized media-label projection and add path/URL leakage tests before expanding queue UI. |
| Playlist delete/clear | Both require explicit playlist scope and confirmation. The command confirms a name, then `PlaylistStore.delete` or `clear` resolves that name again. Clear preserves a prior revision; delete removes the playlist and its revisions. There is no expected playlist ID/revision comparison between prompt and mutation. | **Needs follow-up** | `main.py::playlist_command`; `mariana/playlists.py::delete`, `clear`, `save_snapshot`; confirmation tests in `tests/test_hierarchy_album_download_edges.py`. Resolve name to playlist ID and revision before prompting, then delete/clear by that bound identity with a revision check. |
| Playlist add/remove/move/order | Playlist name and node paths are explicitly playlist-scoped. A store method reads and validates one tree, resolves node/group IDs, and saves a new versioned snapshot. Group removal includes descendants. Concurrent writers can still overwrite a newer revision because `save_snapshot` has no compare-and-swap revision argument; recursive playlist-node removal has no confirmation, although the previous tree is versioned. | **Needs follow-up** | `main.py::playlist_command`; `mariana/playlists.py::_resolve`, `remove_node`, `move_node`, `order`, and `save_snapshot`; hierarchy tests in `tests/test_queue_strategies_and_playlist_editing.py` and `tests/test_hierarchy_album_download_edges.py`. Add expected-revision writes and expose revision restore before claiming concurrent edit safety. |
| Playlist export | The playlist identity and destination are explicit, and output is staged, but `temporary.replace(path)` silently overwrites an existing `.m3u`/`.m3u8` file without confirmation or a bound overwrite target. Export necessarily contains source paths/URLs; that disclosure is intrinsic to the requested file, not suitable for UI events. | **Unsafe** | `main.py::playlist_command`; `mariana/playlists.py::export_m3u`; export tests do not cover an existing destination. Add default no-clobber behavior plus an explicit confirmed overwrite mode that revalidates the destination identity. |
| Albums | There is no album delete/remove command. Search/fetch resolve catalog references; play/queue replace or extend only the authoritative queue; save creates a playlist and rejects name collisions. Album track selectors are scoped to the chosen edition. | **Safe for current surface** | `main.py::album_command`, `_album_reference`, `_album_tracks`; `mariana/albums.py`; `tests/test_album_cli.py`, `tests/test_albums.py`. |
| Current-media favourites and blocks | `fav !|+|-` and `bl !|+|-` operate only on the `MediaRef` captured from the current controller snapshot. They do not accept a library/search number. The stable media identity is written transactionally and the action is reversible. | **Safe** | `main.py::preference_command`, `_preference_media`; `mariana/preferences.py::set` and `toggle`; `tests/test_preferences.py`. |
| Favourite-list inspect/play | `fav N` and `.fav N` are explicitly favourite-list-local. `_favorite_selection` captures one `PreferenceEntry`, maps local entries back to an available indexed library identity, and rejects missing/tombstoned items. Search, queue, and current playback do not affect the selection. | **Safe** | `main.py::_favorite_selection`, `_play_favorite_selection`, and `favorite_command`; `tests/test_favorite_selection.py`, including search/queue poisoning and tombstone cases. |
| Desktop favourite toggle | Renderer intent carries the opaque projected media ID over the authenticated typed channel. The backend compares it with the current snapshot, validates toggle availability, mutates preferences, and emits a fresh projection. Stale intent is rejected with a safe error. | **Safe** | `main.py::_desktop_control_request`; `mariana/desktop_control.py`; `tests/test_desktop_favorites.py`. |
| Radio favourite | `radio favorite <station>` is explicitly radio-scoped. `RadioCatalog.get` resolves slug/ID to a stable station ID and the transaction updates only that row. | **Safe** | `main.py::radio_command`; `mariana/radio.py::favorite`; `tests/test_radio_catalog.py`. |
| Broadcast/radio credential deletion | Profile/station input is resolved to a stable keychain reference before confirmation. Deletion uses that captured reference, not a post-prompt list index. Secrets are never printed. | **Safe** | `main.py::broadcast_command`, `radio_command`; `mariana/credentials.py`; tests in `tests/test_loudness_broadcast_cli.py` and `tests/test_setup_preferences_radio_cli.py`. |
| Download job pause/resume/cancel | Commands require an explicit job UUID. State transitions use conditional transactional updates and refuse invalid/missing states. They do not use search, queue, or playback indices. | **Safe** | `main.py::download_audio_command`; `mariana/download_jobs.py::pause`, `resume`, `cancel`; `tests/test_download_cli.py`. |
| Download output activation | `download-ml` accepts an explicit/default destination but has no confirmation, and both direct/extractor paths atomically replace an existing destination. Managed YouTube jobs also replace an existing expected filename unless `--missing-only` skips it. The confirmation identifies a destination directory, not a bound existing output file. | **Unsafe** | `main.py` `download-ml` and `download_audio_command`; `mariana/download.py::download_media`; `mariana/download_jobs.py::create` and `_run_item`; `tests/test_custom_download.py` and `tests/test_download_cli.py` lack complete no-clobber/confirmed-overwrite coverage. |
| Setup restart and refresh/global configuration | `setup restart` and `refresh all` are confirmed global operations, not target selectors. Include/exclude downloads, theme, desktop close policy, ReplayGain mode, and radio leveling mutate named settings transactionally or through one backend authority. They cannot be redirected by search/queue state. | **Safe for target binding** | `main.py::setup_command`, refresh dispatch, `set_download_library_inclusion`, and settings commands. Their broader rollback/recovery behavior is covered by their subsystem tests rather than selector tests. |

## Code fix made during this audit

`rename short` previously previewed a path, confirmed, then called
`LibraryCatalog.rename(library_id, filename)`. That method re-read the current
path for the ID, so a concurrent library move/reindex or file replacement could
change the filesystem object after the preview.

The fix adds `LibraryRenameTarget`, captures path and file signature before the
preview, and requires `rename_bound` to revalidate the complete target before
the filesystem operation. Existing same-extension validation, collision
refusal, database transaction, and filesystem rollback remain unchanged.

No other runtime behavior was changed in this audit.

## Recommended follow-up batches

1. **Prevent unconfirmed file replacement.** Make playlist export,
   `download-ml`, and managed download activation no-clobber by default. Any
   overwrite option must preview the exact destination, bind its identity or
   absence, confirm, revalidate, and then activate atomically.
2. **Bind playlist identity and revision.** Resolve delete/clear/edit targets to
   playlist ID plus expected revision before prompting or editing. Use
   compare-and-swap updates, surface conflicts, and expose revision restore for
   recursive edits.
3. **Bind global cleanup sets.** Capture the missing-library IDs approved by
   `library clean --missing`, or clearly define and test execution-time global
   semantics.
4. **Use atomic sidecar no-clobber creation.** Refuse if an `.lrc` target appears
   after confirmation instead of replacing it.
5. **Sanitize collection labels.** Stop using `original_uri` as the generic
   queue/playlist/desktop label. Add explicit privacy tests for local paths,
   online URLs, and provider identifiers.
6. **Extend poisoning/concurrency tests.** Cover search/queue/current-state
   interference for rename, library retry/rescan, playlist deletion, and
   concurrent playlist revisions. Keep all destructive filesystem tests inside
   temporary directories with mocked trash or activation APIs.

## Audit invariants for future commands

- A bare number has one documented domain; list-local numbers require an
  explicit command family.
- Resolve once to stable identity before confirmation and execute against that
  same bound identity.
- Revalidate path, file signature, availability, and expected revision
  immediately before mutation.
- Refuse ambiguity, tombstones, stale revisions, target replacement, or a new
  destination collision.
- Keep paths and URLs out of ordinary labels/events; reveal them only for an
  explicit inspection, export, download destination, or destructive file
  confirmation.
- Use transactions, rollback/journaling, revision history, or the operating
  system trash API according to the storage boundary.
- Test cancellation, failure, stale search/queue/playback state, concurrent
  change, and exact prompt-to-operation identity.
