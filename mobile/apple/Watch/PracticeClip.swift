import CoreTransferable
import Foundation
import UniformTypeIdentifiers

/// Data representation sends actual PCM bytes to the user's chosen watch share activity.
struct PracticeClip: Transferable {
    let bytes: Data
    static var transferRepresentation: some TransferRepresentation {
        DataRepresentation(exportedContentType: .wav) { clip in clip.bytes }
            .suggestedFileName("Mariana-duet.wav")
    }
    static func prepare(start: Int, end: Int) throws -> PracticeClip {
        let (url, score) = try PracticeScore.bundled()
        guard start >= 0, end > start, end <= score.duration_ms else { throw PracticeScore.Invalid.coverage }
        let wave = try Data(contentsOf: url)
        func le(_ index: Int, _ count: Int) -> Int {
            (0..<count).reduce(0) { $0 | (Int(wave[index + $1]) << (8 * $1)) }
        }
        func tag(_ index: Int, _ expected: String) -> Bool {
            wave[index..<index + 4].elementsEqual(expected.utf8)
        }
        guard wave.count >= 44, tag(0, "RIFF"), tag(8, "WAVE"), tag(12, "fmt "), tag(36, "data"),
              le(16, 4) == 16, le(20, 2) == 1, le(40, 4) == wave.count - 44 else { throw PracticeScore.Invalid.coverage }
        let rate = le(24, 4), stride = le(32, 2)
        guard (1...384_000).contains(rate), stride > 0 else { throw PracticeScore.Invalid.coverage }
        // 64-bit intermediates for watchOS arm64_32.
        let first = (Int64(start) * Int64(rate) + 500) / 1000 * Int64(stride)
        let last = (Int64(end) * Int64(rate) + 500) / 1000 * Int64(stride)
        guard last > first, last <= Int64(wave.count - 44) else { throw PracticeScore.Invalid.coverage }
        var out = Data(wave.prefix(44))
        let length = Int(last - first)
        for i in 0..<4 {
            out[4+i] = UInt8(truncatingIfNeeded: (36+length) >> (8*i))
            out[40+i] = UInt8(truncatingIfNeeded: length >> (8*i))
        }
        out.append(contentsOf: wave[(44+Int(first))..<(44+Int(last))])
        return PracticeClip(bytes: out)
    }
}
