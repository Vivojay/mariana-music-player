# Security and privacy

- Mariana accepts local files and HTTP(S)-based media. Unsafe FFmpeg protocols,
  arbitrary capture devices, DRM bypass, and access-control bypass are outside
  the supported contract.
- Queue and library state store canonical references, never signed playback
  URLs, cookies, authorization headers, or secret query parameters.
- Private radio and Icecast passwords use the operating-system credential
  store. A named environment-variable override is available for headless use;
  plaintext configuration fallback is intentionally prohibited.
- Broadcast credentials are inserted by an authenticated loopback tunnel and
  never appear in FFmpeg arguments. TLS certificate verification is mandatory.
- Electron uses local packaged content, context isolation, renderer sandboxing,
  disabled Node integration, a restrictive CSP, validated IPC senders, and a
  narrow typed preload API.
- The Mini-player has its own smaller preload and no access to the main-window
  bridge, PTY, arbitrary backend requests, filesystem, or source URLs. Its
  playback controls carry only the projected current-media identity and a
  fixed allowlisted action.
- Playback JSON is runtime-validated at the Electron main-process boundary.
  Only the schema-8 allowlist is reconstructed; unknown fields are dropped and
  malformed, out-of-range, internally inconsistent, private-reference-bearing,
  duplicate, or older projections are not cached or forwarded. The main window
  and Mini-player defensively revalidate the accepted projection.
- Managed tools require an exact SHA-256 match before extraction. Archive paths
  are validated, activation is transactional, and release publication fails
  closed when signing material is unavailable.
- First-run sample archives reject HTTP errors, invalid ZIPs, traversal, and
  symlink entries before an atomic activation. Setup errors are sanitized in
  writable state and do not expose packaged resources to writes.
- `rm`/`del` accepts only available indexed regular media beneath configured
  library roots. It rejects URLs, directories, symlinks, missing/outside files,
  requires confirmation, and uses the native trash API with no permanent-delete
  fallback.
- Playlist delete/clear bind the displayed playlist ID, name, and revision
  before confirmation and transactionally refuse a renamed, removed, or edited
  target. Lyrics sidecar creation binds an absent destination and uses atomic
  no-clobber activation, preserving a file created by another process.
- The command catalog exposes only static command names, categories, risk
  labels, aliases, form kinds, and flags. It contains no paths, credentials,
  private identifiers, handlers, insertion text, or confirmation callbacks.
  Desktop autocomplete is display-only and cannot execute or approve commands.
- Desktop seek sends one finite absolute target plus the projected media
  identity through a dedicated typed boundary. Renderer, Electron main, and
  backend validation reject stale identity, ineligible state, live or unknown
  duration, blocked media, and invalid targets; the backend reapplies current
  preferred-region bounds. No seek command is constructed or injected into the
  terminal.
- Audio and listening history stay local unless an optional integration such as
  ListenBrainz is explicitly enabled.

Discord Rich Presence is off by default and uses only the local Discord desktop
RPC transport. Projection is derived from `PlaybackSnapshot` on a background
worker and contains no paths, path-derived filenames, URLs, service IDs,
credentials, browser profiles, stable media IDs, queue/history contents,
lyrics, recommendation data, device names, or host/user/network identifiers.
Control characters and path- or URL-like text are rejected before publication.
The committed Discord Application ID is public release metadata, not a
credential. Client secrets, user tokens, OAuth credentials, and Discord account
credentials are prohibited. Missing configuration or RPC dependencies become
dormant typed failures; transient desktop/transport loss retries independently.
Third-party exception text is replaced with fixed sanitized status text, and
Discord transport failure is isolated from playback and shutdown.

Security regressions are tested for URL redaction, credential persistence,
subprocess arguments, events, logs, malformed archives, IPC boundaries,
playback projection allowlisting and stale-event rejection, destructive target
races, alias-equivalent guards, and failed transactional activation.

## Paired-desktop credential verification

The opt-in private-network companion remains read-only. Stock clients generate
32-byte random bearer credentials, but the host does not assume that arbitrary
peers use the stock client or choose strong tokens. Host trust format 2 stores a
PBKDF2-HMAC-SHA256 verifier with 600,000 iterations and 32-byte output. The
server-generated 128-bit request ID becomes the device ID and provides a unique
per-record salt, prefixed with `mariana-paired-device-v2` and a zero byte for
domain separation. Device IDs identify records; verifiers are not lookup keys.
The displayed approval proof is the first 16 hexadecimal verifier characters,
and the client independently derives it using the returned request ID. Bearer
tokens remain in the supported OS-protected credential store, not trust files.

Invitation secrets are independently generated 256-bit values held only for
their short in-memory lifetime and compared in constant time. Syntax validation
does not hash a keyring value. Unknown, malformed, and revoked device requests
are rejected before expensive work. At most two credential derivations run at
once; saturation returns a safe retry error instead of queuing unlimited work.
The transport also retains its four-connection limit. Derivation occurs outside
service and trust locks, with expiry, shutdown, and persisted revocation checked
again afterward. These bounds limit concurrency, not total traffic: a hostile
LAN peer that knows a current device ID can still consume the available work
slots. No playback or audio callback waits for credential derivation.

Trust format 1 contains fast verifiers and is not silently migrated or accepted
as format 2. Old or unknown trust formats remain untouched and produce an
explicit re-pair diagnostic. Both desktops must use the updated proof protocol.
To re-pair an older development installation, stop its listener/application,
explicitly retire the host's `trusted-devices.json` from the paired state
directory, disconnect the old companion connection, and issue/approve a fresh
invitation. Retain `server-identity.json` and its protected key: resetting trust
does not require changing the server certificate. Normal status wire schema,
client connection schema, and server-identity schema remain version 1.

The work factor has a real latency cost and must be included in connection and
shutdown acceptance. The KDF provides offline guessing resistance for weak peer
credentials; it is not a password-strength guarantee or a traffic-rate limiter.
The implementation follows [Python's key-derivation guidance](https://docs.python.org/3/library/hashlib.html#key-derivation)
and [the password-hashing query guidance](https://codeql.github.com/codeql-query-help/python/py-weak-sensitive-data-hashing/).
