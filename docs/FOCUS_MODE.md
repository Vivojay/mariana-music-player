# Focus mode

Focus mode limits Mariana to one approved YouTube item until a local passcode
and a paired-phone verification flow are completed. It is disabled by default.
The phone flow uses Firebase Authentication, App Check with reCAPTCHA
Enterprise, Cloud Functions, Hosting, and Firestore. It does not use SMS.

## Current configuration boundary

The repository contains only inert placeholders. No Firebase project, hosted
service, credential, or approved focus-media list is supplied by Mariana.

1. Copy `.env.example` to the ignored local `.env` file.
2. Replace the `MARIANA_FIREBASE_*` placeholders only after provisioning the
   corresponding Firebase resources.
3. Add stable, deliberately selected 11-character YouTube video identities to
   `MARIANA_FOCUS_YOUTUBE_IDS`, separated by commas. Playback URLs are not
   stored as focus identities.
4. Copy `companion/focus/config.example.js` to the ignored
   `companion/focus/config.js` before deploying the phone companion.
5. Copy `.firebaserc.example` to the ignored `.firebaserc` and select the
   intended Firebase project.

Placeholder values fail closed: `focus status` reports Firebase as unavailable,
and `focus on` refuses activation. The local `.env`, phone companion config,
Firebase project selection, function dependencies, and Firebase diagnostic logs
are ignored by Git.

The configured verification endpoint must be canonical HTTPS. Its dedicated
request handler rejects every redirect, including same-host redirects, so the
desktop token cannot follow another destination. It does not change ordinary
provider networking. Responses are limited to 64 KiB and must contain a valid
structured envelope. Pairing, phone-code and unlock responses are checked for
expiry after the network operation as well as before it; late replies cannot
pair a device, advance the challenge or begin the countdown.

The Firebase project must enable Anonymous Authentication, App Check with a
reCAPTCHA Enterprise provider for the hosted phone companion, Cloud Functions,
Hosting, and Firestore. Deploy the supplied Firestore rules and indexes. Configure
a Firestore TTL policy for the `expires_at` field in both `focusPairings` and
`focusUnlocks`; application checks still reject expired records immediately.

## Commands

| Command | Behavior |
|---|---|
| `focus` / `focus status` | Show activation prerequisites and current state. |
| `focus setup` | Create or replace the local passcode while focus mode is off. |
| `focus pair` | Create a single-use, five-minute phone pairing invitation. |
| `focus pair status` | Finish recording an approved phone pairing. |
| `focus devices` | List paired phones. |
| `focus revoke DEVICE_ID` | Revoke a phone while focus mode is off. |
| `focus media` | List the configured stable YouTube identities. |
| `focus on [YOUTUBE_ID]` | Confirm activation and play one approved item. |
| `focus off` | Verify the passcode and create a phone unlock request. |
| `focus verify` | Privately enter the phone code and show the reverse code. |
| `focus cancel` | Cancel an incomplete unlock without disabling focus mode. |
| `focus recover` | Recheck a restored, valid active backup; does not unlock Focus Mode. |

The passcode verifier and desktop pairing token are held in the operating-system
credential store. Persistent focus state contains device metadata and the stable
YouTube identity, never the passcode or a transient playback URL. While active,
ordinary media switching, discovery, downloads, settings changes, and queue edits
are rejected at Mariana's command and playback boundaries.

## Human-verification limitations

The phone companion disables ordinary selection, copy, and context-menu actions
for the displayed code. The desktop shows its reverse code in a separate,
non-selectable window and removes it from the ordinary renderer event. These are
friction measures, not an absolute guarantee: operating-system accessibility
tools, screenshots, cameras, or optical character recognition can still capture
visible text. Firebase App Check helps attest the phone web client but is not a
general proof that a person cannot automate the entire flow.

Until the placeholders are replaced and the Firebase resources are deployed,
only local status and passcode setup can be exercised; pairing and activation
remain unavailable by design.

## Saved-state recovery

Invalid saved restrictions open a recovery-only application with playback locked,
not an inactive Focus Mode or a startup exception. A persistent desktop notice and
`focus status` explain the condition. The terminal remains available for help,
status, recovery, stop, and exit. Typed playback/settings/discovery mutations are rejected
by the backend; renderer controls cannot bypass recovery. No first-boot sound or
automatic Home refresh starts in recovery. First-run setup and tool migration are
not prerequisites for this locked shell; missing FFmpeg/ffprobe cannot hide the
recovery surface. Unsupported runtimes and explicit startup aborts still apply.

The loader limits saved input to 64 KiB, rejects duplicate keys, unknown versions,
invalid types, inconsistent active/challenge fields and malformed device records.
It never rewrites the damaged primary file. A small `focus-state.json.guard` records
that state has existed and latches recovery across restart, so deleting only the
damaged primary file does not become first boot. An existing valid installation
acquires this guard without rewriting its primary state. If storage is unwritable,
the live process stays locked; durable evidence cannot be promised on failing storage.

Recovery procedure:

1. Preserve the damaged file externally before replacing it. Restore a known-good,
   complete **active** `focus-state.json` backup in the same application data directory.
   Do not delete the guard or create a fabricated inactive state.
2. Use `focus recover`, or **Recheck restored active state** in the desktop notice.
   Merely restarting with a replacement file does not clear the recovery latch.
3. Recovery validates the active backup and its paired-device records, clears old
   pairing/unlock challenges, and resumes the active restriction. A saved countdown
   cannot unlock after recovery. Normal passcode and paired-phone verification are
   still required to turn Focus Mode off.

No valid active backup means playback stays locked, including damaged formerly
inactive state. Mariana does not currently create active backups automatically;
an authenticated reset policy is separate work, not an implicit recovery option.
There is no passcode reset,
credential replacement, automatic data deletion, or recovery unlock shortcut.
Save failure during a normal unlock also enters recovery rather than leaving
the process unlocked while the old locked state remains on disk. After the outermost
state operation releases its lock, the host schedules a deduplicated output stop
and a persistent desktop notice. If the worker cannot start, it emits the notice
and stops synchronously outside both the state and scheduler locks. An unstarted
worker is never retained or joined.
The stop never initializes another output device. `s`/`stop` remain available as
safe recovery operations; driver failures do not clear the restriction. Recovery is an
application consistency mechanism, not protection against someone who controls
the operating-system account and can rewrite its files or program.
