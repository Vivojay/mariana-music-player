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
subprocess arguments, events, logs, malformed archives, IPC boundaries, and
failed transactional activation.
