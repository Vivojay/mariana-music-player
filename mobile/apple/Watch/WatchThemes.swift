import SwiftUI

struct WatchTheme: Decodable {
    struct Chrome: Decodable { let background, accent, text: String }
    let name: String
    let chrome: Chrome

    static let all: [String: WatchTheme] = {
        guard let url = Bundle.main.url(forResource: "theme_presets", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let themes = try? JSONDecoder().decode([String: WatchTheme].self, from: data)
        else { return [:] }
        return themes
    }()
    static func color(_ hex: String) -> Color? {
        guard hex.first == "#", hex.count == 7 || hex.count == 9,
              let rgb = UInt32(hex.dropFirst().prefix(6), radix: 16) else { return nil }
        return Color(.sRGB, red: Double((rgb >> 16) & 255)/255,
                     green: Double((rgb >> 8) & 255)/255, blue: Double(rgb & 255)/255, opacity: 1)
    }
}
