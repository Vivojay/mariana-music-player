import AVFoundation
import SwiftUI
import Combine

@main
struct MarianaWatchApp: App {
    var body: some Scene { WindowGroup { WatchPlayerView() } }
}

final class StreamPlayer: ObservableObject {
    @Published var status = "Enter an HTTPS audio URL."
    @Published var playing = false
    @Published var starting = false
    private var playbackRequest: UUID?
    @Published var ready = false
    private var requestID = UUID()
    private var player: AVPlayer?
    private var observation: NSKeyValueObservation?
    private var ending: AnyCancellable?
    private var clockObserver: Any?
    @Published var practice: PracticeScore?
    @Published var positionMs = 0
    @Published var clipStart = 0
    @Published var clipEnd = 0
    @Published var clip: PracticeClip?
    @Published var hasStream = false

    func load(_ text: String) {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme?.lowercased() == "https", url.host != nil, url.user == nil, url.password == nil else {
            status = "Use an HTTPS media URL."
            return
        }
        start(url, sheet: nil)
    }
    func loadPractice() {
        do {
            let (url, sheet) = try PracticeScore.bundled()
            start(url, sheet: sheet)
        } catch { status = "Practice unavailable · recording or timing could not be verified." }
    }
    private func removeClock() {
        if let clockObserver { player?.removeTimeObserver(clockObserver) }
        clockObserver = nil
    }
    deinit { removeClock() }
    private func start(_ url: URL, sheet: PracticeScore?) {
        pause()
        removeClock()
        ready = false
        practice = sheet
        hasStream = sheet == nil
        positionMs = 0
        clip = nil
        clipStart = 0
        clipEnd = sheet?.duration_ms ?? 0
        observation?.invalidate()
        ending?.cancel()
        player = nil
        requestID = UUID()
        let request = requestID
        status = "Connecting audio…"
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, policy: .longFormAudio, options: [])
            AVAudioSession.sharedInstance().activate(options: []) { [weak self] active, error in
                DispatchQueue.main.async {
                    guard let self, self.requestID == request else { return }
                    guard active else { self.status = error?.localizedDescription ?? "Select an audio output."; return }
                    self.prepare(url)
                }
            }
        } catch { status = error.localizedDescription }
    }
    private func prepare(_ url: URL) {
        let item = AVPlayerItem(url: url)
        let current = AVPlayer(playerItem: item)
        player = current
        if practice != nil {
            clockObserver = current.addPeriodicTimeObserver(forInterval: CMTime(value: 1, timescale: 12), queue: .main) { [weak self, weak current] time in
                guard let self, let current, self.player === current, time.seconds.isFinite else { return }
                self.positionMs = Int((max(0, time.seconds) * 1000).rounded())
            }
        }
        status = "Loading…"
        observation = item.observe(\.status, options: [.initial, .new]) { [weak self] item, _ in
            DispatchQueue.main.async {
                guard let self, self.player?.currentItem === item else { return }
                switch item.status {
                case .readyToPlay:
                    if let sheet = self.practice {
                        let duration = item.duration.seconds * 1000
                        guard duration.isFinite && abs(duration - Double(sheet.duration_ms)) <= 250 else {
                            self.pause()
                            self.removeClock()
                            self.practice = nil
                            self.status = "Karaoke unavailable · duration could not be verified."
                            return
                        }
                        self.status = "Practice duet · " + String(sheet.percent) + "% timing"
                    } else { self.status = url.host ?? "Ready" }
                    self.ready = true
                case .failed:
                    self.pause()
                    self.ready = false
                    self.removeClock()
                    self.practice = nil
                    self.status = item.error?.localizedDescription ?? "Stream unavailable."
                default: break
                }
            }
        }
        ending = NotificationCenter.default.publisher(for: .AVPlayerItemDidPlayToEndTime, object: item)
            .receive(on: DispatchQueue.main).sink { [weak self, weak current] _ in
                guard let self, let current, self.player === current else { return }
                current.seek(to: .zero)
                self.playing = false
            }
    }
    func toggle() {
        guard ready, let player else { return }
        if playing || starting { pause(); return }
        let request = UUID()
        playbackRequest = request
        starting = true
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, policy: .longFormAudio, options: [])
            // watchOS negotiates an audio route asynchronously before streaming.
            AVAudioSession.sharedInstance().activate(options: []) { [weak self, weak player] active, error in
                DispatchQueue.main.async {
                    guard let self, let player, self.player === player, self.playbackRequest == request else { return }
                    self.playbackRequest = nil
                    self.starting = false
                    guard active else { self.status = error?.localizedDescription ?? "Select an audio output."; return }
                    player.play()
                    self.playing = true
                }
            }
        } catch {
            pause()
            status = error.localizedDescription
        }
    }
    func pause() {
        playbackRequest = nil
        starting = false
        player?.pause()
        playing = false
    }
    func mark(_ start: Bool) {
        guard let player, ready, let practice else { return }
        let seconds = player.currentTime().seconds
        guard seconds.isFinite else { return }
        let time = max(0, min(practice.duration_ms, Int((seconds * 1000).rounded())))
        if start { clipStart = time } else { clipEnd = time }
        clip = nil
    }
    func prepareClip() {
        guard ready, practice != nil else { return }
        do { clip = try PracticeClip.prepare(start: clipStart, end: clipEnd) }
        catch { clip = nil; status = "Choose a clip start before its end." }
    }
    func seekPractice(to ms: Double) {
        guard ready, let sheet = practice, let player else { return }
        let target = CMTime(value: Int64(min(max(0, ms), Double(sheet.duration_ms))), timescale: 1000)
        player.seek(to: target, toleranceBefore: .zero, toleranceAfter: .zero)
    }
    func back() {
        guard let player else { return }
        let t = player.currentTime().seconds
        if t.isFinite { player.seek(to: CMTime(seconds: max(0, t - 15), preferredTimescale: 600)) }
    }
}
struct WatchPlayerView: View {
    @AppStorage("mariana.streamURL") private var url = ""
    @AppStorage("mariana.watchTheme") private var theme = "aurora"
    @AppStorage("mariana.watchAccent") private var accent = ""
    private var palette: WatchTheme.Chrome? { WatchTheme.all[theme]?.chrome }
    @StateObject private var stream = StreamPlayer()
    @Environment(\.scenePhase) private var phase
    var body: some View {
        ScrollView {
            VStack {
                Text("Mariana").font(.headline)
                TextField("HTTPS audio URL", text: $url)
                Button("Load stream") { stream.load(url) }
                Button("Practice duet") { stream.loadPractice() }
                Text(stream.status).font(.caption)
                Button(stream.starting ? "Cancel" : (stream.playing ? "Pause" : "Play")) { stream.toggle() }.disabled(!stream.ready)
                if let score = stream.practice, stream.ready {
                    if let part = score.segment(at: stream.positionMs), !part.voices.isEmpty {
                        ForEach(part.voices, id: \.singer) { voice in
                            PracticeScore.line(voice, at: stream.positionMs).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    } else {
                        Text(stream.positionMs >= score.duration_ms ? "End of duet" : "Instrumental").font(.caption)
                    }
                    Slider(value: Binding(get: { Double(min(score.duration_ms, stream.positionMs)) },
                                          set: { stream.seekPractice(to: $0) }), in: 0...Double(score.duration_ms), step: 100)
                        .accessibilityLabel("Duet playback position")
                    Text(String(format: "Clip %.2fs → %.2fs", Double(stream.clipStart) / 1000, Double(stream.clipEnd) / 1000)).font(.caption)
                    Button("Mark start here") { stream.mark(true) }
                    Button("Mark end here") { stream.mark(false) }
                    if let clip = stream.clip {
                        ShareLink(item: clip, preview: SharePreview("Mariana duet", image: Image(systemName: "waveform"))) {
                            Label("Share WAV", systemImage: "square.and.arrow.up")
                        }
                    } else { Button("Prepare clip") { stream.prepareClip() }.disabled(stream.clipStart >= stream.clipEnd) }
                } else if stream.hasStream {
                    Text("Karaoke unavailable · no verified 90% timing sheet for this stream.").font(.caption2)
                }
                Button("Back 15 seconds") { stream.back() }.disabled(!stream.ready)
                Picker("Theme", selection: $theme) {
                    ForEach(WatchTheme.all.keys.sorted(), id: \.self) { key in Text(WatchTheme.all[key]?.name ?? key).tag(key) }
                }
                TextField("Accent #RRGGBB", text: $accent)
                if !accent.isEmpty && WatchTheme.color(accent) == nil { Text("Use #RRGGBB or clear the field.").font(.caption2) }
            }.padding(.horizontal)
        }
        .tint(WatchTheme.color(accent) ?? WatchTheme.color(palette?.accent ?? "") ?? .mint)
        .foregroundStyle(WatchTheme.color(palette?.text ?? "") ?? .primary)
        .background(WatchTheme.color(palette?.background ?? "") ?? .black)
        .onChange(of: phase) { value in if value == .background { stream.pause() } }
    }
}
