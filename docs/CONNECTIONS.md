# Connections

Select **Connections** in Electron or the portable player, choose a service, and use **Connect** when offered. Sign-in opens the provider's own browser page. For Last.fm, choose **Finish sign-in** after granting access. Desktop authorizations are kept in the operating-system keychain. In the static web player, Spotify and Snapchat open a separate sign-in window when popups and BroadcastChannel are available, so the music can keep playing. Browsers that block popups redirect the current tab. Web authorizations last for the current page session. Console and Flow share the same controls and state. An account's public profile can also be saved and opened independently of sign-in.

## Supported actions

| Service | Native CLI, TUI, Electron and local Python web launcher | Published static website |
| --- | --- | --- |
| Spotify | Browser sign-in with PKCE, identity check and up to 20 playlists | PKCE browser sign-in, identity check and playlists on a registered HTTPS origin |
| Last.fm | Signed browser authorization, account verification and ten recent listens | Public profile |
| MusicBrainz | Browser sign-in with PKCE, account verification and profile | Public profile |
| YouTube Music | Google sign-in, identity of your own YouTube channel, up to 20 YouTube playlists. An account with no channel cannot complete channel verification. | Link to a YouTube Music channel using its UC channel ID |
| TikTok | Login Kit desktop with PKCE, verified display name and app-scoped identity | Public profile |
| Snapchat | Public profile. A published HTTPS web player can use Snapchat's registered web redirect. | Login Kit browser PKCE with app-scoped identity and optional display name on a registered HTTPS origin |
| Bandcamp, Facebook, Instagram, SoundCloud | Public profile links | Public profile links |
| ListenBrainz | Public profile and ten recent public listens with no app registration | Public profile and ten recent public listens when the API is reachable |

A **saved public profile** can belong to anyone. A **signed-in identity** is stored only after provider confirmation. **Verify** checks existing access online. If an account was revoked at the provider, reconnect to use it. **Disconnect** removes this installation's credentials. A separate profile bookmark remains available until **Remove link**. For full revocation, use the provider's connected-app settings.

In Mariana, enter `accounts list`. For example:

```text
accounts connect lastfm
accounts finish lastfm
accounts activity lastfm
accounts link bandcamp yourusername
accounts open bandcamp
accounts link listenbrainz yourusername
accounts activity listenbrainz
```

`accounts cancel <service>` abandons an unfinished authorization. Never paste passwords or access tokens into the command prompt. Choosing **Open** launches an official site or a saved link. It does not authorize private access.

## Release operator setup

No service registration or secret is included in this patch. The release operator registers Mariana and configures the app credentials once for a supported deployment. Listeners using a configured release click **Connect**. Unconfigured releases continue to offer public links and ListenBrainz public history. Protect publisher secrets in the deployer's environment. For broad consumer distribution, confidential-client exchanges require an operator-controlled backend. Never bake shared secrets into public installers, mobile bundles or web assets.

| Native service | Operator environment | Registered redirect or flow |
| --- | --- | --- |
| Spotify | `MARIANA_SPOTIFY_CLIENT_ID` | `http://127.0.0.1:8789/accounts/callback`, S256 |
| TikTok | `MARIANA_TIKTOK_CLIENT_ID` (client key) and `MARIANA_TIKTOK_CLIENT_SECRET` | Same loopback redirect, TikTok desktop and approved `user.info.basic` |
| Google/YouTube | `MARIANA_YOUTUBE_CLIENT_ID` and `MARIANA_YOUTUBE_CLIENT_SECRET` | Desktop OAuth client, YouTube Data API v3 enabled, same loopback redirect and `youtube.readonly` consent |
| MusicBrainz | `MARIANA_MUSICBRAINZ_CLIENT_ID` and `MARIANA_MUSICBRAINZ_CLIENT_SECRET` | `http://localhost:8789/accounts/callback`, profile scope |
| Last.fm | `MARIANA_LASTFM_API_KEY` and `MARIANA_LASTFM_API_SECRET` | Desktop request-token approval and signed session exchange |

For static-hosted Spotify and Snapchat, supply the public `MARIANA_SPOTIFY_WEB_CLIENT_ID` and/or `MARIANA_SNAPCHAT_WEB_CLIENT_ID` **when running the web build**. Register the player's exact directory URL, including trailing slash, with each provider. Use HTTPS for public deployments. A build served from a different directory or origin requires its own registered redirect. Browser approval state and the temporary code verifier expire after five minutes. Access and refresh tokens remain in page memory. Mobile WebView custom-scheme callbacks and watch account linking require separate platform registration and device testing.

Spotify development-mode access is restricted to a small approved test group. Google, TikTok and Snapchat may require app review. YouTube Data API returns YouTube channel/playlist metadata. Licensed listening libraries, background synchronization and publishing clips to personal social accounts require separate provider permissions or partner agreements. Bandcamp's official API targets labels and fulfillment partners. Instagram's professional-account API is a separate product. Saving a Facebook, Instagram or Bandcamp link does not grant Mariana private account access. OS file sharing is independent of account sign-in.

## Provider references and verification

- [Spotify PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow), [callback requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri), [quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
- [Last.fm desktop authorization](https://www.last.fm/api/desktopauth), [recent listens](https://www.last.fm/api/show/user.getRecentTracks)
- [MusicBrainz OAuth and user information](https://musicbrainz.org/doc/Development/OAuth2)
- [YouTube authorization](https://developers.google.com/youtube/data/guides/authentication), [channel ownership](https://developers.google.com/youtube/data/guides/implementation/channels)
- [TikTok desktop Login Kit](https://developers.tiktok.com/docs/en/login-kit-desktop), [profile identity](https://developers.tiktok.com/docs/en/tiktok-api-v2-get-user-info/)
- [Snapchat Login Kit](https://developers.snap.com/snap-kit/login-kit/overview), [Bandcamp developer access](https://bandcamp.com/developer), [Instagram platform changes](https://developers.facebook.com/docs/instagram/platform/instagram-api/changelog/)
- [ListenBrainz public listens](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html)

Native tests exercise real loopback HTTP callbacks with fixed provider responses, unmatched state, provider identity, keychain boundaries, disconnect, signed Last.fm calls and same-origin HTTP protections. Browser tests cover static Spotify and Snapchat consent callbacks, memory-only token handling and public links. Production authorization, real-keychain behavior on Windows/macOS, provider app approvals, mobile external-auth handoff and refresh-token rotation with a live provider remain unverified.

Android and iOS open the selected provider or saved public profile in the system browser. Profile routes come from the same provider directory as the web player. The private player document stays open. Published HTTPS browser OAuth and desktop-backed OAuth are separate supported environments.

## Guided setup and listener profiles

Enter `accounts setup` in the CLI or TUI and choose a service by name or number. Enter cancels before taking an action. `accounts setup spotify` offers the sign-in, verification, public bookmark and browser steps available to this installation. Provider consent runs in the browser. Setup never asks for passwords, application secrets or OAuth tokens in the command prompt. An installation without a registered client can still save public profile links. The operator configuration table above identifies the supported registrations.

`accounts setup karaoke` starts the bundled practice duet after confirmation. `accounts setup podcasts` opens a public Podbean search and `accounts setup audiobooks` opens a LibriVox title search. No service registration is required for these public features. Access to a publisher's private feeds or licensed lyrics still requires an appropriate integration.

In the portable player or FLOW, choose **Connections → Guided setup**. The selected feature opens its existing accessible form or duet controls. Registered providers use the grant types listed above. Electron's Connections panel guides the available service actions and includes a local listener manager. [Listener profiles](LISTENER_PROFILES.md) explains the scope of native accounts, portable browser state, and the next-launch switch.

For a personal native installation, the wizard also offers **Configure my own registered provider app** for supported unconfigured Spotify, Last.fm, MusicBrainz, YouTube and TikTok clients. Register a client and the exact callback or desktop authorization flow in the table above first. The wizard displays the callback and collects the client identifier and required secret in hidden prompts. The protected operating-system keychain holds the credentials for the active listener. Choose **Remove my saved app registration** in the same wizard to remove them. A complete publisher environment configuration takes precedence. The public static website uses its build-time public client registration. Browser forms never receive native client secrets.
