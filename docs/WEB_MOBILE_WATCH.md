# Mariana on browsers, phones and watches

See [portable downloads, Docker and native builds](PORTABLE_RELEASES.md) for standalone launchers, checksums and release status.

To operate the running native player through a browser on the same computer, see [native session and surface capabilities](SURFACE_PARITY.md).

The browser and phone editions play audio in the device's web engine. The watch editions have native stream players and a [built-in karaoke duet with WAV clipping](WATCH_PRACTICE.md). Mariana's Python decoder, Electron terminal and SQLite database still run on the desktop. Queues and bookmarks in the portable player belong to the browser origin or app installation.

## Open the web player on Windows

From the repository root, with Python 3.12 available:

```powershell
python tools/build_web_player.py --serve
```

The launcher builds the assets from this checkout and prints the address and directory it is serving. Stop an older server with Ctrl+C, or choose another port with `--port 8768`. You can also run the script by absolute path from a different PowerShell directory.

Open **http://127.0.0.1:8767/**. Type `help`, choose **Add files**, or enter a direct audio URL. Switch between **Console** and **Flow** without interrupting playback. Shared palettes can be adjusted in **Appearance**. **Listening controls** exposes speed, sleep timer, bookmarks and voice softening. Local files can be saved in IndexedDB so the player can reopen them offline. Browser quotas or privacy settings can limit persistence. The UI reports session-only files when storage fails. A browser or operating system that suspends timers or web audio can delay the sleep timer.

A podcast feed needs playable enclosures and must permit browser access through CORS. The feed command imports up to 100 episodes, skips previously queued URLs and times out after 15 seconds. Direct media URL playback uses the browser's supported codecs and network policy. Online sources use the normal audio path. Voice softening is per local item and requires working Web Audio AudioWorklet support. Check **Soften S sounds** under Listening controls.

Deploy the **contents** of `build/web-player` to one HTTPS origin, at the root or a subdirectory. The manifest and versioned service worker use relative paths. Use the browser's Install or Add to Home Screen action where supported. On a phone away from the developer machine, use the HTTPS site address. The loopback address on a phone refers to the phone itself. The worker caches the app shell. Local imported media can be reopened offline. Live streams, public catalogs and feed searches require a connection.

## Android and Wear OS

Install JDK 17, Gradle 8.13 and Android SDK platform 36 with Build Tools 35.0.0. Run the following in the repository root. The phone target uses the prebuilt web assets and accepts multiple local files through the Android document picker. The Wear target accepts a direct HTTPS audio URL, remembers that URL, and supports foreground play, pause and a 15-second rewind on seekable recordings. Each application installs independently. Both watch editions include the shared palette list and a saved custom accent color.

```powershell
python tools/build_web_player.py
gradle -p mobile/android :app:assembleDebug :wear:assembleDebug
```

The expected outputs are `mobile/android/app/build/outputs/apk/debug/app-debug.apk` and `mobile/android/wear/build/outputs/apk/debug/wear-debug.apk`. To install on the intended test device, use `adb devices` and then `adb -s SERIAL install -r PATH_TO_APK`. Replace SERIAL and PATH_TO_APK. Use a Wear OS emulator or a Wear OS Galaxy Watch for the watch APK.

```powershell
gradle -p mobile/android :app:bundleRelease :wear:bundleRelease
```

This builds unsigned release bundles. Configure a developer-owned signing key and package identifiers for Play distribution. The phone targets API 36 and Wear targets API 35. Check the requirements again when submitting. [Android Gradle Plugin compatibility](https://developer.android.com/build/releases/agp-8-13-0-release-notes) · [Google Play target SDK requirements](https://developer.android.com/google/play/requirements/target-sdk) · [Android app signing](https://developer.android.com/studio/publish/app-signing)

## iPhone, iPad and Apple Watch

Use a Mac with Xcode and XcodeGen. The iOS target bundles the same player and opens it in WKWebView. The independent watchOS app uses AVPlayer to stream a user-entered HTTPS media URL, with foreground play/pause, rewind and audio route selection. Depending on the watch and its state, audio routing requires compatible headphones. [Apple watchOS project setup](https://developer.apple.com/documentation/watchos-apps/setting-up-a-watchos-project) · [Audio session activation](https://developer.apple.com/documentation/avfaudio/avaudiosession/activate%28options%3Acompletionhandler%3A%29)

```sh
python3 tools/build_web_player.py --apple-icons
cd mobile/apple
xcodegen generate
xcodebuild -project MarianaMobile.xcodeproj -scheme MarianaPhone -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
xcodebuild -project MarianaMobile.xcodeproj -scheme MarianaWatch -destination 'generic/platform=watchOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

For devices or TestFlight, open `MarianaMobile.xcodeproj`, configure unique bundle IDs and a signing team, archive each intended target with the supported SDK, then export through Xcode Organizer. [Apple distribution](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases)

## Build and acceptance status

The **Mariana web and mobile preview builds** workflow runs on manual dispatch once present on the default branch. It builds the static web folder, runs browser tests, builds debug phone and watch APKs plus unsigned AABs, and archives unsigned iOS/watchOS simulator apps. It uploads each successful job's products as workflow artifacts. It does not publish a store release.

| Target | Evidence from this implementation | Outstanding acceptance |
| --- | --- | --- |
| Browser/PWA | Built the static bundle, served it locally, checked script syntax and exercised commands, RSS deduplication, theme/mode changes, bookmarks, queue mutations and tone generation in a DOM runtime with simulated media. | Actual browser decoding, IndexedDB across restarts, offline playback, system media controls and responsive layout. Chromium startup was blocked by the workspace socket policy. Two real-browser tests ship in `web/tests/player.spec.ts`. Test Safari and Chrome touch devices. |
| Android phone / tablet | A Gradle application embeds the portable player with a scoped local origin, Android picker and system window insets. Java source parsed and resources validated. | Run Gradle, install APK, test local files, IndexedDB, DSP, secure streams, permissions and lifecycle. Build host here lacks Android SDK and Gradle. |
| Wear OS / recent Galaxy Watch | Independent native MediaPlayer application, package and launcher icon supplied. Java parsed and resources validated. | Compile, device-test UI, audio focus and Bluetooth route behavior. Background service, queue synchronization and offline phone transfers are pending. Legacy Tizen has no target. |
| iOS / iPadOS | SwiftUI, WKWebView, generated icons and Xcode project specification supplied. | Compile with Xcode, verify file picker, local origin / IndexedDB persistence, audio interruptions and conditional DSP. Native background audio, CarPlay and account synchronization remain open. |
| watchOS | Standalone SwiftUI and AVPlayer source, Xcode scheme spec and generated icon supplied. | Simulator build and physical watch/audio-route acceptance. Offline library transfer, phone pairing and background listening remain open. |
| Distribution | Manual CI jobs and local commands supply reproducible build entry points. | No CI run, signed APK/AAB/IPA, store submission, entitlement, or public release is evidenced by this patch. Record CI URLs, device/OS versions and store build IDs upon validation. |

To run the browser tests locally after building the web assets, install desktop development dependencies with `npm ci`, install the test browser with `npx playwright install chromium`, then run `npx playwright test --config web/player.e2e.config.ts`.
