# Local stem monitoring and export

Mariana can prepare source-separated audio locally, monitor one or more prepared
stems while a finite item keeps its playback identity, and export the stem files.
It never uploads source media to a separation service.

## What “real-time” means here

Source separation itself is not performed in the sound-device callback. Hybrid
Demucs analyzes the complete finite item on a background worker and can take
minutes, especially on a CPU. After that preparation finishes, Mariana decodes
the selected local stem files alongside the original and switches the listening
mix with a 50 ms equal-power transition. The original decoder remains the source
of playback position, queue transitions, event capture, and program/broadcast
audio. A missing, late, or failed stem decoder falls back to the original mix.

This is intentionally different from claiming low-latency causal separation of
an unseen live stream. Radio, livestreams, unknown-duration media, and items over
four hours are rejected.

## Models and names

The default `htdemucs` model produces four actual outputs:

- `vocals`
- `drums`
- `bass`
- `other`

`acapella` is an alias for `vocals`. `karaoke` and `instruments` select every
prepared output except vocals. The optional `htdemucs_6s` model adds `guitar` and
`piano`; upstream describes those additional outputs as experimental. Mariana
does not call the broad drums output “kicks” or the broad other output “melody.”

The implementation follows the upstream model’s documented stem vocabulary and
file output rather than applying frequency filters and misrepresenting the result
as source separation. See the [Demucs project](https://github.com/facebookresearch/demucs)
and the [Hybrid Transformers paper](https://arxiv.org/abs/2211.08553).

## Commands

```text
stems status
stems help
stems prepare [4|6] [--yes]
stems cancel
stems solo vocals
stems solo acapella
stems solo karaoke
stems mix vocals drums
stems original
stems export "C:\path\to\folder" [--yes]
stems clear [--yes]
```

Install the optional worker runtime in Mariana’s Python environment before the
first preparation:

```text
python -m pip install demucs
```

The package and its model runtime are loaded only by an explicit preparation
job, so ordinary application startup and playback do not import them. The first
confirmed preparation may retrieve the selected model weights. `stems status`
distinguishes a missing worker from an idle, running, ready, failed, or cancelled
job without revealing a local path or a temporary online playback reference.

Each preparation owns an immutable request-metadata snapshot, a verified copy of
the input bytes, and a generation-bound cancel token. Local files are copied with
1 MiB buffers into an exclusively created workspace. The original handle/path,
size, timestamps, copied bytes, and a second source SHA-256 read are checked before
separation. The separator never reads the user's original path. Replacing the
original after snapshot completion does not change the accepted job. Rewriting
the owned input during separation is rejected before result publication.
Cancellation invalidates later progress and completion; another preparation
must wait for the previous worker to finish unwinding. Cache clear and preparation
cannot overlap in the same service, and filesystem work does not hold the status
lock. Shutdown refuses new work, requests cancellation, and waits at most two
seconds (or a shorter requested budget). A late worker cannot publish a successful
result after cancellation or shutdown. An already-entered filesystem operation
cannot be forcibly rolled back: a complete manifest written during cancellation
is retained as cache but is not activated or reported as the completed job.
Managed separator processes respond to cancellation independently; a blocked
filesystem or uncooperative optional worker is not forcibly terminated as a
Python thread.

## Storage and export

Prepared input and stems live under Mariana's private data cache. Results expire
after fourteen days, with a default 16 GiB budget. Preparation reserves a
conservative input/output allowance under the cache coordination lock before
creating large files. Other processes' reservations and existing results consume
that budget. Busy results are never evicted to satisfy it: insufficient capacity
causes a clear refusal. A 2 GiB free-disk reserve is checked before work; the
managed separator also checks output size/free space during processing. These
checks are cooperative safeguards, not filesystem quotas against an unrelated
process consuming the disk between checks.

Result identities use version 3 manifests bound to SHA-256 of the actual input
bytes, finite duration, media identity, and model. Each output has a byte digest;
cache reuse verifies those outputs. Same-sized input edits with preserved
timestamps do not reuse an old separation. Version 2 results are not reused or
silently deleted; they can require manual storage review. Model/runtime upgrades
that change separation behavior should bump the cache format rather than pretend
old results were produced by the new implementation.

The ready result, every monitor decoder (including retiring decoders and seek
replacements), and every export holds a shared native file lock. Clear/pruning
requires the corresponding exclusive lock. Windows uses
[`LockFileEx`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex); other
supported platforms use `flock`. The lock protects against cooperating Mariana
processes, not just threads in one instance. A retained monitor pin survives
service shutdown and is released only after its decoder's resource cleanup.
Retaining a pin is an in-memory reference operation; cache lookup and lock
acquisition never run in the audio callback. Process exit releases kernel locks
without guessing whether a saved process ID is still alive.

Abandoned work and incomplete results are removed only after acquiring their
exclusive lock and validating their ownership marker and bounded directory tree.
Traversal never follows symlinks, hardlinked files, Windows junctions or reparse
points. Unknown directories are not recursively deleted. Directory traversal is
limited to 256 entries and 12 nested levels per result, with at most 1,024 cached
results/workspaces. Coordination lock files are deliberately not unlinked, to
avoid creating two independent locks for one pathname; the namespace is bounded
to 8,192 entries and requires offline storage review if exhausted.

Temporary owned inputs are discarded after success, cancellation or failure.
The model cache is separate because a partial model eviction would corrupt later
jobs. Users can clear the current result explicitly.

Online finite audio is materialized to local FLAC through the already resolved,
private backend input, with an explicit materialization byte limit. Its actual
materialized bytes determine cache identity too, so a changed online recording
cannot be accepted solely because its provider identity is unchanged. Temporary
signed URLs and request headers are never placed
in the manifest, renderer projection, confirmation, or command output.

Export writes the real prepared WAV outputs beneath a title-derived directory.
Existing outputs are refused unless the same command includes its explicit
confirmation bypass. Approval binds the existing file identities; replacing or
changing an approved output during copying invalidates that approval. An output
that was absent at approval is activated without overwriting a file that appears
later, even when `--yes` was supplied for other existing outputs.

All stems are copied into exclusively created, unique temporary files before any
output becomes visible. Copying uses bounded buffers, checks SHA-256 byte integrity,
and revalidates source and destination identities. Linked files and directories,
including Windows junctions/reparse points, are refused. Export never changes the
source file or downloaded media.

A copy or verification failure exports nothing. Activation is atomic per file,
not across the complete stem set: if a later activation fails, the error reports
how many completed outputs remain. Mariana does not delete those successful files
as rollback. Cleanup removes only temporary files whose ownership and directory
identities still match. If a directory is replaced or moved during export, cleanup
fails closed and may leave its owned partial files in the original directory.

These checks protect against ordinary concurrent operations and detected path
replacement. Explicitly approved replacement uses the shared revalidate-then-replace
output contract, not an operating-system compare-and-swap; it does not promise
immunity to a hostile same-account process changing paths in the final syscall gap.
Kernel lease behavior is tested with a second process, including abrupt exit.
Real optional-model execution, listening quality and hardware performance remain
separate acceptance checks; deterministic separator fixtures do not certify them.

Users are responsible for having the rights to process and export a recording.
