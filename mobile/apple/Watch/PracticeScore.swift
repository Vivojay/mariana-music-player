import CryptoKit
import Foundation
import SwiftUI

struct PracticeScore: Decodable {
    struct Word: Decodable {
        let text: String
        let start_ms, end_ms: Int
        let confidence: Double
    }
    struct Voice: Decodable {
        let singer: String
        let words: [Word]
    }
    struct Segment: Decodable {
        let start_ms, end_ms: Int
        let voices: [Voice]
    }
    let schema, media_sha256: String
    let duration_ms: Int
    let confidence: Double
    let segments: [Segment]

    enum Invalid: Error { case missingResources, coverage }

    static func bundled() throws -> (URL, PracticeScore) {
        guard let audio = Bundle.main.url(forResource: "practice-duet", withExtension: "wav"),
              let score = Bundle.main.url(forResource: "practice-duet", withExtension: "json") else { throw Invalid.missingResources }
        let hash = SHA256.hash(data: try Data(contentsOf: audio)).map { String(format: "%02x", $0) }.joined()
        let sheet = try JSONDecoder().decode(PracticeScore.self, from: Data(contentsOf: score))
        guard sheet.matches(hash) else { throw Invalid.coverage }
        return (audio, sheet)
    }

    private func matches(_ hash: String) -> Bool {
        guard schema == "mariana.karaoke.v1", media_sha256 == hash,
              (0.90...1).contains(confidence), (1...86_400_000).contains(duration_ms) else { return false }
        var lastEnd = 0
        var sung = false
        for part in segments {
            guard part.start_ms == lastEnd, part.end_ms > lastEnd, part.end_ms <= duration_ms else { return false }
            lastEnd = part.end_ms
            var names = Set<String>()
            for voice in part.voices {
                guard !voice.words.isEmpty, !voice.singer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                      names.insert(voice.singer).inserted else { return false }
                var lastWord = part.start_ms
                for word in voice.words {
                    guard !word.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, (0.90...1).contains(word.confidence),
                          word.start_ms >= lastWord, word.end_ms > word.start_ms, word.end_ms <= part.end_ms else { return false }
                    lastWord = word.end_ms
                    sung = true
                }
            }
        }
        return sung && lastEnd == duration_ms
    }

    var percent: Int {
        let minimum = segments.flatMap(\.voices).flatMap(\.words).reduce(confidence) { min($0, $1.confidence) }
        return Int(floor(minimum * 100))
    }
    func segment(at ms: Int) -> Segment? { segments.first { $0.start_ms <= ms && ms < $0.end_ms } }

    static func line(_ voice: Voice, at ms: Int) -> Text {
        var line = Text(voice.singer + " · ").bold()
        for (index, word) in voice.words.enumerated() {
            let text = Text((index == 0 ? "" : " ") + word.text)
            line = line + (word.start_ms <= ms && ms < word.end_ms ? text.bold().underline() : text)
        }
        return line
    }
}
