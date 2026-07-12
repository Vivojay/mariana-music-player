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
- Audio and listening history stay local unless an optional integration such as
  ListenBrainz is explicitly enabled.

Security regressions are tested for URL redaction, credential persistence,
subprocess arguments, events, logs, malformed archives, IPC boundaries, and
failed transactional activation.
