import Foundation
import UIKit
import WebKit

/// Receives bounded chunks from the bundled main document and opens the system activity sheet.
final class ClipShare: NSObject, WKScriptMessageHandlerWithReply {
    private let root = FileManager.default.temporaryDirectory.appendingPathComponent("MarianaClips", isDirectory: true)
    private var partial: URL?
    private var output: FileHandle?
    private var destination = "system"
    private var videoSeconds = 0.0
    private var mediaType = ""
    private var expected = 0
    private var received = 0

    override init() {
        super.init()
        let files = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        for file in files {
            if let modified = try? file.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate,
               modified.timeIntervalSinceNow < -86400 { try? FileManager.default.removeItem(at: file) }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let document = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "web-player")
        guard let document, message.frameInfo.isMainFrame,
              let web = message.webView, web.url?.standardizedFileURL == document.standardizedFileURL,
              let fields = message.body as? [String: Any], let op = fields["op"] as? String else {
            replyHandler(nil, "Clip sharing requires the bundled player.")
            return
        }
        do {
            switch op {
            case "link":
                guard let raw = fields["url"] as? String, raw.utf8.count <= 2048,
                      let parts = URLComponents(string: raw), parts.scheme == "https", parts.host != nil,
                      parts.user == nil, parts.password == nil, parts.port == nil, let link = parts.url,
                      var presenter = web.window?.rootViewController else { throw ShareFailure.invalid }
                while let next = presenter.presentedViewController { presenter = next }
                let sheet = UIActivityViewController(activityItems: [link], applicationActivities: nil)
                sheet.popoverPresentationController?.sourceView = web
                sheet.popoverPresentationController?.sourceRect = CGRect(x: web.bounds.midX, y: web.bounds.midY, width: 1, height: 1)
                presenter.present(sheet, animated: true)
            case "targets":
                let type = fields["mime"] as? String ?? "", seconds = fields["seconds"] as? Double ?? 0
                var reason = ""
                if !type.hasPrefix("video/") || fields["portrait"] as? Bool != true { reason = "prepare a portrait video" }
                else if seconds > 20.001 { reason = "choose up to 20 seconds" }
                else if storyURL() == nil { reason = "publisher setup required" }
                else if let url = storyURL(), !UIApplication.shared.canOpenURL(url) { reason = "Instagram unavailable" }
                replyHandler([["id":"instagram-story", "name":"Instagram Stories", "reason":reason]], nil)
                return
            case "start":
                discard()
                let types = ["video/mp4": "mp4", "video/webm": "webm", "audio/wav": "wav",
                             "audio/mp4": "m4a", "audio/webm": "webm", "audio/ogg": "ogg",
                             "text/vtt": "vtt", "text/plain": "txt"]
                guard let size = fields["size"] as? Int, (1...32 * 1024 * 1024).contains(size),
                      let mime = fields["mime"] as? String, let ext = types[mime] else { throw ShareFailure.invalid }
                destination = fields["target"] as? String ?? "system"
                videoSeconds = fields["seconds"] as? Double ?? 0
                mediaType = mime
                if destination == "instagram-story" && fields["portrait"] as? Bool != true { throw ShareFailure.invalid }
                guard destination == "system" || destination == "instagram-story" else { throw ShareFailure.invalid }
                let suggested = fields["name"] as? String ?? ""
                let safe = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: " ._-"))
                let name = suggested.count <= 100 && suggested.hasSuffix("." + ext) && !suggested.hasPrefix(".")
                    && suggested.unicodeScalars.allSatisfy(safe.contains) ? suggested : "Mariana-clip." + ext
                let directory = root.appendingPathComponent(UUID().uuidString, isDirectory: true)
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                let file = directory.appendingPathComponent(name)
                partial = file
                guard FileManager.default.createFile(atPath: file.path, contents: nil) else { throw ShareFailure.invalid }
                output = try FileHandle(forWritingTo: file)
                expected = size
            case "chunk":
                guard let output, let encoded = fields["data"] as? String, encoded.utf8.count <= 65536,
                      let data = Data(base64Encoded: encoded), !data.isEmpty, data.count <= 49152,
                      received + data.count <= expected else { throw ShareFailure.invalid }
                try output.write(contentsOf: data); received += data.count
            case "finish":
                guard let output, let file = partial, expected == received,
                      var presenter = web.window?.rootViewController else { throw ShareFailure.invalid }
                try output.close(); self.output = nil
                if destination == "instagram-story" {
                    guard let url = storyURL(), UIApplication.shared.canOpenURL(url),
                          mediaType.hasPrefix("video/"), videoSeconds > 0, videoSeconds <= 20.001 else { throw ShareFailure.invalid }
                    let bytes = try Data(contentsOf: file)
                    UIPasteboard.general.setItems([["com.instagram.sharedSticker.backgroundVideo":bytes]],
                        options:[.expirationDate:Date(timeIntervalSinceNow: 300), .localOnly:true])
                    discard()
                    UIApplication.shared.open(url) { opened in
                        replyHandler(opened ? "ok" : nil, opened ? nil : "Instagram could not open. Choose All apps.")
                    }
                    return
                }
                while let next = presenter.presentedViewController { presenter = next }
                let sheet = UIActivityViewController(activityItems: [file], applicationActivities: nil)
                sheet.popoverPresentationController?.sourceView = web
                sheet.popoverPresentationController?.sourceRect = CGRect(x: web.bounds.midX, y: web.bounds.midY, width: 1, height: 1)
                sheet.completionWithItemsHandler = { _, _, _, _ in
                    try? FileManager.default.removeItem(at: file.deletingLastPathComponent())
                }
                presenter.present(sheet, animated: true)
                partial = nil; received = 0
            case "cancel": discard()
            default: throw ShareFailure.invalid
            }
            replyHandler("ok", nil)
        } catch {
            discard()
            replyHandler(nil, "Could not open this destination. Choose All apps or check available storage.")
        }
    }
    private func storyURL() -> URL? {
        guard let id = Bundle.main.object(forInfoDictionaryKey: "MarianaMetaAppID") as? String,
              id.range(of: #"^[0-9]{1,25}$"#, options:.regularExpression) != nil else { return nil }
        return URL(string:"instagram-stories://share?source_application=" + id)
    }
    private func discard() {
        try? output?.close(); output = nil
        if let partial { try? FileManager.default.removeItem(at: partial.deletingLastPathComponent()) }
        partial = nil; received = 0
    }
    private enum ShareFailure: Error { case invalid }
}
