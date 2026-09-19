# Paired desktops: private read-only companion

This first local-network delivery establishes device trust and read-only playback
status. It does not grant playback control, publishing, playlist/file access,
chat, camera/microphone capture, forwarding, or recording. Those capabilities
need separate permissions and implementations. The earlier Firebase-based Focus
companion is a separate cloud prototype, not this trust boundary.

## Explicit startup and use

Pairing is disabled at startup. Importing the modules or constructing the service
does not open a socket, start a worker, provision a certificate, or access the
credential store. The application coordinator starts provisioning/network work
only after an explicit `room` operation; it never reconnects automatically.

The command family uses the backend worker, not terminal-text injection:

```text
room status
room host 192.168.1.20
room invite invitation.json
room requests
room approve <request-id> <device-proof>
room devices
room revoke <device-id>
room stop

room connect invitation.json <full-server-fingerprint> "Listening room"
room poll
room now
room cancel
room disconnect
```

Use the host's actual private IPv4 interface, optionally followed by a port.
Loopback is supported for testing. Wildcard binding, public addresses, hostnames,
IPv6, and link-local interfaces are not supported in this version. Accepted
connections must also originate from a private IPv4 or loopback address. No
firewall rules, router mappings, public listener, discovery broadcasts, accounts,
or external services are created. Do not forward this port through a router.
Private addressing alone is not a security boundary; authentication remains
mandatory for every status request.

Deliver an invitation privately to the intended device. Independently compare
the complete server fingerprint through a trusted channel, rather than treating
an invitation file's own fingerprint as proof of who sent it. Compare the
displayed device proof on both devices before the host approves the request.
The invitation grants permission to request pairing, not status access.

`room cancel` discards only the local, unpersisted attempt. A rejected, expired,
or interrupted attempt can be cancelled and retried with a new invitation.
`room disconnect` forgets that saved client connection and its credential; it
does not revoke host-side trust. The host uses `room revoke` to prevent subsequent
access. Revocation does not erase status someone already received.

## Trust and protected storage

- The host lazily provisions an EC P-256 self-signed TLS server certificate with
  a one-year validity. The private key is encrypted PKCS#8 on disk. Its random
  passphrase is stored only in an OS-protected credential backend.
- TLS uses Python's established OpenSSL-backed `ssl` implementation, TLS 1.2 or
  newer, certificate validity/name checks, and the explicitly verified certificate
  as its sole trust anchor. An exact SHA-256 peer-certificate pin is checked before
  sending any HTTP request or credentials. Verification is never disabled.
- The application installs system-certificate verification for ordinary HTTPS.
  That wrapper is unsuitable for a pinned server and attempts peer verification
  even before a deferred server handshake. Pairing lazily loads the standard
  library's existing `ssl` loader code into a separate module namespace. It uses
  the unchanged standard `SSLContext` there, without swapping global TLS classes,
  accessing wrapper-private objects, or changing HTTP/provider certificate policy.
  An unavailable loader refuses pairing; guessed source-file paths and unverified
  TLS fallbacks are not used. Frozen/packaged loader availability needs separate
  packaged acceptance.
- Each invitation has a 256-bit random one-use secret and a lifetime of at most
  five minutes. Monotonic deadlines enforce host-side expiry even if the wall
  clock moves backwards; the wall-clock expiry is for display/client checks.
  Devices need reasonably synchronized clocks. Making a new invitation invalidates
  the previous unconsumed invitation.
- Each recipient creates its own 256-bit bearer credential. The host stores only
  its digest and an explicit `status.read` permission after local approval. The
  recipient stores its credential in its OS keyring, namespaced by verified server
  fingerprint and device ID. Server private keys and recipient credentials are
  different secrets and cannot be substituted for each other.
- Supported protected stores are Windows Credential Manager, macOS Keychain,
  Linux Secret Service, and KWallet. Exact supported backend classes are checked;
  arbitrary plugins, plaintext/file stores, null stores, and chains containing an
  unsupported fallback are rejected. A safe chain selects one protected backend
  once and never searches/falls back between stores. Windows credentials use
  local-machine persistence rather than enterprise roaming persistence.
- There is no plaintext or environment-variable fallback. Missing keys, corrupted
  identity documents, unavailable protected storage, or expired certificates refuse
  operation without silently replacing identity or dropping existing trust. Renewal
  requires a future explicit identity-renewal/re-pairing workflow.
- Trust writes use temporary-file flush/fsync and atomic replacement. A nonblocking
  OS file lock and fresh disk reload precede each trust read/write, so separate
  processes cannot authorize from a stale revocation cache or overwrite a revocation.
  A busy state file safely refuses that request. Small stable lock files are retained
  intentionally to avoid replacement-inode races.

The threat model covers untrusted network peers, invitation reuse, stale state,
and accidentally unsafe credential backends. It cannot protect against a malicious
process already running as the same OS user, a compromised paired device, or an
operator approving an impostor without comparing identities.

## Narrow status and resource boundaries

Status is an allowlisted copy of the existing sanitized playback projection:
state, title, artist, source category, position, duration, finite/live flags, and
schema version. It excludes media/library IDs, local paths, queue contents,
resolver dictionaries, playback URLs, cookies, credentials, ratings, and raw error
logs. The recipient validates the same exact shape and sanitizes display text
again. Serving status reads cached backend state; it does not invoke the decoder,
resolver, provider, command loop, or audio callback.

Only pairing request/poll and authenticated read-only status endpoints exist.
Unknown/control/file routes, browser-origin requests, duplicate HTTP/JSON keys,
non-finite numbers, excessive nesting, and expanded permission documents are
rejected. No raw request bodies, TLS exceptions, or bearer credentials are logged.

Limits are four concurrent TLS requests, eight pending requests, 32 persisted
devices, 8 KiB headers, 4 KiB request/response bodies, 16 JSON container levels,
and 128 KiB trust metadata. Revoked devices remain recorded and count toward the
device limit; there is no silent eviction. TLS handshake timeout is two seconds;
HTTP header/body processing has a five-second absolute deadline and two-second
idle timeout. Connections are one request each, without chunking or keepalive.
Closing cancels open sockets and bounds thread joins to three seconds; stopping
the service does not wait on a busy approval lock. A new listener lifetime clears
ephemeral invitations/requests while retaining durable trust.

## Implementation and evidence

- [Trust and protected storage](../mariana/paired_trust.py)
- [Pinned TLS server and client](../mariana/paired_transport.py)
- [Lazy application coordinator](../mariana/paired_companion.py)
- [Protocol and lifecycle regressions](../tests/test_paired_desktops.py)

Certificate provisioning uses the pinned `cryptography==50.0.1` dependency only
when pairing starts. Existing dependency versions remain unchanged. The package
uses an Apache-2.0-or-BSD-3-Clause license; packaged distribution must retain its
required third-party notices, including bundled cryptographic runtime notices.
See the official [installation guidance](https://cryptography.io/en/stable/installation/),
[X.509 tutorial](https://cryptography.io/en/stable/x509/tutorial/),
[license explanation](https://cryptography.io/en/stable/faq/#what-license-is-cryptography-available-under),
and [Python TLS documentation](https://docs.python.org/3/library/ssl.html).

Automated verification exercises real loopback TLS, explicit approval, certificate
pin rejection before application requests, restart persistence, recipient isolation,
revocation across independent stores, atomic-write failure, invalid protocols,
expiry/reuse, concurrency, and shutdown. A separate Windows Credential Manager
round trip used a unique disposable service entry and removed it afterwards.
The pairing suite also runs after the real application's system-trust
initialization and verifies that the ordinary global HTTPS context stays intact.

These checks are not evidence of two-physical-desktop operation, firewall consent,
macOS/Linux native credential-store behavior, packaged acceptance, or security
review of future sharing/capture/chat services. No native device-pairing interface
or automatic network discovery is implied by this backend/CLI foundation.

The next bounded feature is approved recipient-specific portable playlist
references. Owned-file transfer needs separate acceptance, bounded staging,
integrity checks, source-replacement defenses, and no-clobber import before it
can be enabled. Camera/microphone capture, livestream relay, chat, replay retention,
and public community discovery remain separate future milestones.
