# Autocomplete and Command Dropdown Audit

## Scope and conclusion

This document records the command-completion architecture as of `dev-6`. It is
an audit and design only; no parser, command, terminal, or desktop behavior was
changed.

Autocomplete is feasible, but an Electron dropdown must not be built by
reconstructing command state from terminal output or renderer keystrokes. The
safe sequence is to establish backend-owned command metadata and a pure
completion engine first, then add terminal and desktop presentation adapters.
The existing typed desktop control channel can eventually carry bounded
completion queries, but it does not currently provide line-editing state or a
completion action.

## Current command architecture

Command processing currently has five distinct layers:

1. `mariana/commands.py::normalize_command` canonicalizes exact and first-token
   aliases declared in `ALIAS_COMPATIBILITY`. It also defines the search prefix
   families in `SEARCH_COMMANDS`.
2. `mariana/command_parser.py::split_command` tokenizes single- or double-quoted
   input while preserving Windows backslashes. It reports incomplete quoting.
3. `main.py::process` combines a routed handler dictionary with a large legacy
   conditional dispatcher. Bare numbers, dot-prefixed immediate play, slash
   source/search forms, and equals-prefixed inspection forms have distinct
   semantics.
4. Command-family functions such as `queue_command`, `playlist_command`,
   `album_command`, `library_command`, `radio_command`, `station_command`,
   `favorite_command`, `block_command`, and `region_command` parse their own
   subcommands, flags, and scoped indices.
5. `main.py::HELP_GROUPS` and `HELP_EXAMPLES`, `help.md`, and the README command
   reference describe commands independently of dispatch.

The reusable pieces are the tokenizer, compatibility-alias table, search
request parser, and individual family parsers. There is no complete registry
from which dispatch, help, validation, and completion can all be derived.
Consequently, scraping `main.py`, parsing `Usage:` strings, or treating
`HELP_GROUPS` as grammar would be incomplete and unsafe.

### Existing grammar characteristics

- Command and subcommand keywords are case-insensitive in most modern paths,
  but some legacy branches still compare literal lower-case tokens.
- Quoted values may contain whitespace. Backslashes are literal, and doubled
  matching quotes inside a quoted value encode one quote.
- A bare positive number is a library/catalog index. Scoped indices such as
  `fav N`, queue positions, playlist tree paths, and album references have
  different namespaces and must never be interchanged.
- A leading dot commonly means immediate playback (`.N`, `.fav N`, `.find`), a
  slash identifies source/search forms (`/ys`, `/yl`, `/ml`), and some equals
  forms inspect or return an index. Prefix semantics are part of the command,
  not cosmetic aliases.
- Confirmation flags are command-scoped. A trailing `y`, `yes`, or `--yes`
  cannot be stripped globally because those values can be legitimate names or
  paths.
- Free-text search terms, URLs, quoted playlist names, paths, durations, ranges,
  and selectors require different replacement and quoting rules.

## Recommended command metadata

Add a backend-only static registry before adding any completion UI. A command
specification should describe syntax and presentation, not contain serialized
handlers or mutable application state.

| Field | Purpose |
| --- | --- |
| Stable specification key | Internal registry identity; never a media or user identifier |
| Canonical command and category | Primary spelling and help grouping |
| Aliases | Spelling, scope (`exact`, `token`, or prefix form), and status (`native`, compatibility, or retired) |
| Summary and examples | Concise help text shared by CLI help and suggestion detail |
| Forms | Valid subcommand paths rather than one ambiguous usage string |
| Argument slots | Name, kind, required/repeatable state, quoting policy, and valid literals |
| Flags | Valid position, whether a value is required, and mutual exclusions |
| Risk | Read-only, state-changing, destructive, credential-bearing, or external-action |
| Availability | Static requirements such as current media, finite media, indexed library, or desktop mode |
| Completion provider | A named allowlisted provider for sanitized dynamic candidates; never an arbitrary callback sent to clients |

Argument kinds should preserve namespaces explicitly: `library-index`,
`favorite-index`, `queue-position`, `playlist-tree-path`, `album-reference`,
`download-job-reference`, `duration`, `seek-target`, `region-time`, `enum`,
`free-text`, `url`, and `filesystem-path`. This prevents the target-binding bugs
that occur when one numeric list context is reused for another command.

The serialized catalog may include canonical commands, safe aliases, forms,
literal values, summaries, risk labels, and availability labels. It must not
include handlers, local paths, URLs entered by the user, credentials, cookies,
headers, browser profiles, resolver data, stable media IDs, device identity, or
private account data.

### Alias policy

- Rank and display the canonical command first.
- Show native aliases as secondary labels.
- Keep compatibility aliases executable, but hide them from normal suggestion
  lists unless the typed prefix matches the alias or compatibility aliases are
  explicitly requested.
- Never suggest retired aliases. An exact retired command may continue to emit
  its existing migration guidance.
- Preserve meaningful `.`, `/`, and `=` prefixes. Completion must not rewrite a
  prefixed action into a command with different execution semantics.
- Validate at startup or in tests that aliases do not collide across scopes.

## Completion candidates

### Safe static candidates

The first completion layers should cover command names, help topics,
subcommands, flags, and enumerated values:

| Family | Useful static suggestions |
| --- | --- |
| Playback/status | `play`, `pause`, `stop`, `next`, `prev`, `now`, `progress`, `autonext`; `on`, `off`, `status` |
| Seek/fade | `start`, `end`, percentage/duration examples; `in`, `out`, `to`, `from`, `over`/`in` only where accepted |
| Queue | Operations, group operations, ordering strategies, repeat/consume modes, `ys`, `youtube` |
| Library/search | Search command families, library operations, scan modes, `current`, `--full`, `--dry-run` |
| Favourites/blocked media | `fav`, `.fav`, `favs`, `block`, `unblock`, `blocked`, and their literal operations |
| Regions | `show`, `clear`, `clear-start`, `clear-end`, `current`, `start`, `end` |
| Downloads | Command families, job operations, formats, quality values, and safe flags |
| Playlists/albums | Operations, ordering modes, insertion locations, and non-destructive flags |
| Radio/station | Operations, scope values, leveling modes, and status actions |
| Discord/settings/tools | Presence modes, theme presets, close behavior, auth/tool status actions |
| Destructive commands | Exact command/flag forms with a visible risk label; never fuzzy auto-correction or automatic execution |

Syntax examples are suggestion detail, not insertable values. For example,
`+30s` may teach seek syntax, but a completer must not invent a timestamp the
user did not type.

### Sanitized dynamic candidates

Later phases may query backend-owned read-only projections for:

- library indices with safe indexed display labels;
- favorite-local indices with safe labels;
- queue positions with safe labels;
- existing playlist names;
- cached album references with safe edition labels;
- locally configured radio/station names;
- current-media and supported-mode availability.

Dynamic results must be bounded, generated without network access, and carry a
request generation so stale results cannot be applied after library, queue, or
playback state changes. They must contain insertion text and safe presentation
text only. Canonical paths, source URLs, resolver fields, fingerprints,
credentials, tokens, stable private IDs, and full queue/history contents are
not completion data.

Do not suggest free-text searches, arbitrary URLs, credential values, browser
profiles, lyrics, descriptions, output paths, or confirmation bypass tokens.
Filesystem completion is explicitly deferred because it creates disclosure,
quoting, traversal, and destructive-target risks.

## Completion engine and CLI behavior

A pure backend completion engine should accept the current line, cursor offset,
and a bounded local context, then return:

- the exact replacement span;
- insertion text already quoted for Mariana's tokenizer;
- safe display text and optional short detail;
- candidate kind and risk label;
- whether more input is required;
- a request generation for dynamic results.

It must use the same quote and token rules as `split_command`, including
incomplete quoted tokens. It must never execute a command while computing or
accepting a completion.

Recommended keyboard contract:

- `Tab` completes a unique candidate or opens the candidate list.
- A second `Tab`, `Down`, and `Up` move through candidates without executing.
- `Shift+Tab` moves backward.
- `Escape` closes the list and leaves the line unchanged.
- Accepting a suggestion replaces only the reported span. It does not submit
  the command; the user must press `Enter` separately to execute.
- A candidate that merely extends to a shared prefix may insert that prefix,
  but completion must not guess a destructive command or target.

The current `input()` loop does not expose a cross-platform completer or an
authoritative editable-line object. A later CLI adapter therefore needs a
tested line-editor boundary. A `prompt_toolkit`-style adapter is a possible
cross-platform route, with the current `input()` behavior retained as a safe
fallback, but dependency, packaged-PTY, first-boot, Unicode, and Windows tests
must precede adoption. Platform-specific `readline` alone would not provide
Windows parity.

## Fuzzy matching and ranking

Fuzzy matching should be deterministic and opt-in after prefix completion is
stable. Recommended order:

1. exact canonical match;
2. canonical token prefix;
3. native-alias prefix;
4. subcommand token prefix in the active grammar form;
5. word-boundary/subsequence match;
6. bounded edit distance for non-destructive command names only.

Results should be stable for equal scores, capped (for example, eight visible
items), and grouped by active grammar position. Fuzzy matching must never alter
free text, URLs, paths, media titles, playlist names, or numeric targets. It
must never silently correct or execute destructive commands. Retired aliases
receive no fuzzy score; compatibility aliases rank below canonical/native
forms. Matching should use Unicode normalization consistent with local search
where practical, while insertion preserves the registry spelling.

## Electron and xterm feasibility

`desktop/TerminalSurface.tsx` currently forwards `terminal.onData` bytes
directly through `window.mariana.terminal.write`. Its `pendingInput` string is
only sufficient to detect `clear`/`cls`; escape sequences reset it, and it does
not model cursor movement, wrapped lines, selection replacement, quoted paste,
or backend prompt redraws. It is not a safe parser or completion buffer.

xterm can display an HTML dropdown over or adjacent to the terminal, but a
clean inline implementation requires authoritative line/cursor state and
careful positioning through resize, wrapping, scrolling, DPI, and font
changes. The first desktop dropdown should be anchored consistently near the
active prompt/footer rather than relying on private xterm renderer internals.
Pixel-near-cursor placement can follow after resize and wrapped-line E2E tests.

The desktop should:

- obtain catalog and suggestion results from a typed, authenticated backend
  request, extending the boundary in `mariana/desktop_control.py`,
  `desktop/main.ts`, `desktop/preload.cts`, and `desktop/shared.ts`;
- render suggestions only, with no independent grammar or mutable command
  catalog;
- receive sanitized replacement spans and labels;
- send typed completion-navigation/accept intent to the backend-owned line
  editor when that boundary exists;
- never inject a selected command into the terminal as a playback/control
  mechanism and never execute it merely because a suggestion was accepted;
- discard responses whose request generation or prompt session is stale.

A future command palette and terminal dropdown should consume the same catalog
and completion service. They may use different layouts, but must not carry
separate command definitions. A general typed command-execution API is not
required for autocomplete and should not be introduced as a shortcut.

## Accessibility and interaction

- The dropdown uses a combobox/listbox relationship with an accessible name,
  active-descendant state, selected option, result count, and risk text.
- Keyboard use must be complete; pointer use is optional and must not steal
  terminal focus unexpectedly.
- Screen-reader announcements should be concise and should not repeat on every
  playback/status event.
- Reduced-motion mode disables animated opening or selection movement.
- Long labels are display-trimmed while their sanitized full label remains
  accessible.
- Closing the dropdown restores terminal focus and preserves the exact input.
- Multiple desktop terminal views share the backend but keep separate prompt
  session IDs so a result from one view cannot modify another.

## Risks and edge cases

- **Metadata drift:** a partial registry can disagree with the legacy
  dispatcher. Registry coverage and help consistency need explicit tests before
  the registry drives UI.
- **Ambiguous numeric scopes:** library, favorite, queue, album, and search
  indices cannot share a completion provider.
- **Stale state:** queue/library changes and auto-advance can invalidate dynamic
  results between query and acceptance.
- **Quoted input:** replacement must preserve spaces, doubled quotes, Windows
  backslashes, incomplete quotes, and cursor edits in the middle of a token.
- **Prefix commands:** `.`, `/`, and `=` forms can change action semantics and
  must not be normalized as cosmetic punctuation.
- **Destructive actions:** fuzzy correction, confirmation tokens, and target
  suggestions can create accidental mutation; prefer exact forms and visible
  risk labels.
- **Privacy:** catalog-backed labels still require the same safe-display rules
  as playback projection. No path or provider internals may enter desktop
  events.
- **Terminal ownership:** renderer-side reconstruction will fail on paste,
  cursor movement, prompt redraw, Unicode widths, and line wrapping.
- **Performance:** dynamic queries must be local, cancellable, bounded, and
  debounced; no network request belongs in keystroke handling.

## Staged implementation plan

1. **Static command metadata registry.** Add canonical top-level commands,
   categories, forms, literal arguments, alias status, risk, and privacy labels.
   Validate uniqueness and compatibility-alias coverage. Do not change dispatch.
2. **CLI/help registry adoption.** Generate the compact runtime help surface
   from the registry and add consistency checks against `help.md`; migrate
   command families incrementally rather than rewriting `process` at once.
3. **Basic command-name Tab completion.** Add a backend line-editor adapter and
   pure completion engine for canonical top-level names and native aliases,
   retaining ordinary `input()` as fallback until packaged acceptance passes.
4. **Context-aware arguments.** Add subcommand/literal completion, then bounded
   sanitized providers for scoped library, favorite, queue, playlist, album,
   and station contexts.
5. **Desktop dropdown.** Add typed catalog/query events and an accessible
   renderer-only listbox. It consumes backend replacement spans and does not
   execute commands or mutate playback.
6. **Fuzzy ranking.** Add deterministic non-destructive command-name ranking
   after prefix behavior and accessibility are stable.
7. **Richer typed integration.** Add cancellable dynamic queries, prompt-session
   generations, and shared command-palette presentation only where a concrete
   user workflow requires them.

### First safe implementation slice

The first slice should add `mariana/command_catalog.py` with immutable command
and argument specifications for canonical top-level names, native and
compatibility aliases, help categories, literal subcommands, and risk labels.
It should add tests for duplicate canonical names, alias collisions, unknown
categories, unsafe serialized fields, deterministic ordering, and coverage of
the existing `ALIAS_COMPATIBILITY` table. It should not alter `process`, input,
help output, desktop IPC, or packaged dependencies.

This slice produces a reviewable source of truth without pretending the legacy
dispatcher has already been migrated. Runtime help adoption is a separate
commit after the registry is complete enough to avoid hiding valid commands.

## Explicitly out of scope

- Runtime autocomplete, dropdown UI, command palette, or command execution.
- Renderer-owned parsing or command definitions.
- Terminal text injection as a typed control substitute.
- Filesystem, URL, credential, browser-profile, lyrics, or free-text
  suggestions.
- Network-backed suggestions, provider searches, or recommendation queries.
- New commands, aliases, playback policies, persistence, or migrations.
- Mini-player, mouse seeking, Discord acceptance, and release packaging.

## Audit evidence

- Parser and aliases: `mariana/command_parser.py`, `mariana/commands.py`.
- Dispatch and family parsers: `main.py::process` and the command-family
  functions listed above.
- Runtime help: `main.py::HELP_GROUPS`, `HELP_EXAMPLES`, and `help_command`.
- User reference: `help.md` and the README command map.
- Terminal input: `desktop/TerminalSurface.tsx`.
- Desktop boundary: `desktop/main.ts::requestBackendControl`,
  `desktop/preload.cts`, `desktop/shared.ts`, and
  `mariana/desktop_control.py::DesktopControl`.
- Current typed backend action: `main.py::_desktop_control_request`, currently
  allowlisting favourite toggle only.

No runtime code fix was made during this audit.
