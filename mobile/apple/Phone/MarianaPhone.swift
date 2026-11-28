import SwiftUI
import WebKit

@main
struct MarianaPhoneApp: App {
    var body: some Scene { WindowGroup { WebPlayer() } }
}

struct WebPlayer: UIViewRepresentable {
    final class Navigation: NSObject, WKNavigationDelegate, WKUIDelegate {
        private static func directoryKey(_ url: URL) -> String? {
            guard var parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
                  parts.scheme?.lowercased() == "https", parts.host != nil,
                  parts.user == nil, parts.password == nil else { return nil }
            parts.fragment = nil
            if parts.percentEncodedPath.isEmpty { parts.percentEncodedPath = "/" }
            return parts.string
        }
        private let links: Set<String> = {
            guard let directory = Bundle.main.url(forResource: "directory", withExtension: "json", subdirectory: "web-player"),
                  let data = try? Data(contentsOf: directory),
                  let json = try? JSONSerialization.jsonObject(with: data) else { return [] }
            let rows = json as? [[String: Any]] ?? (json as? [String: Any])?["sources"] as? [[String: Any]] ?? []
            return Set(rows.compactMap { row in
                guard let value = row["url"] as? String, let url = URL(string: value) else { return nil }
                return Navigation.directoryKey(url)
            })
        }()

        private let providers: [[String: String]] = {
            guard let file = Bundle.main.url(forResource: "account-providers", withExtension: "json", subdirectory: "web-player"),
                  let data = try? Data(contentsOf: file),
                  let rows = try? JSONDecoder().decode([String: [String: String]].self, from: data) else { return [] }
            return Array(rows.values)
        }()
        private func isVoiceInvite(_ url: URL) -> Bool {
            guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
                  parts.scheme == "https", parts.host == "meet.jit.si", parts.port == nil,
                  parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil else { return false }
            return parts.percentEncodedPath.range(of: #"^/[A-Za-z0-9_-]{3,160}$"#, options: .regularExpression) != nil
        }
        private func isProviderLink(_ url: URL) -> Bool {
            guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false), parts.scheme == "https",
                  parts.port == nil, parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil else { return false }
            for row in providers {
                if let site = row["site"], Self.directoryKey(url) == site { return true }
                guard let prefix = row["profile"], let base = URLComponents(string: prefix),
                      base.host == parts.host, parts.path.hasPrefix(base.path) else { continue }
                let handle = String(parts.path.dropFirst(base.path.count))
                if handle != "." && handle != ".." && handle.range(of: #"^[\p{L}\p{M}\p{N}_. -]{1,80}$"#, options: .regularExpression) != nil { return true }
            }
            return false
        }

        func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                     initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                     decisionHandler: @escaping (WKPermissionDecision) -> Void) {
            let index = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "web-player")
            guard type == .microphone, frame.isMainFrame, let index,
                  webView.url?.standardizedFileURL == index.standardizedFileURL else {
                decisionHandler(.deny)
                return
            }
            decisionHandler(.prompt)
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            let allowed = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "web-player")
            guard let url = action.request.url else { decisionHandler(.cancel); return }
            if let allowed, url.isFileURL, url.standardizedFileURL == allowed.standardizedFileURL {
                decisionHandler(.allow)
                return
            }
            if action.navigationType == .linkActivated,
               action.targetFrame?.isMainFrame != false,
               let key = Navigation.directoryKey(url), links.contains(key) || isProviderLink(url) || isVoiceInvite(url) {
                UIApplication.shared.open(url)
            }
            decisionHandler(.cancel)
        }
    }
    func makeCoordinator() -> Navigation { Navigation() }
    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.addScriptMessageHandler(ClipShare(), contentWorld: .page, name: "marianaClip")
        configuration.allowsInlineMediaPlayback = true
        // File lookup and tone rendering finish asynchronously after the user's Play action.
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.userContentController.addUserScript(WKUserScript(
            source: "window.MarianaNativeShell = 'ios';",
            injectionTime: .atDocumentStart, forMainFrameOnly: true
        ))
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.uiDelegate = context.coordinator
        view.navigationDelegate = context.coordinator
        if let doc = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "web-player") {
            view.loadFileURL(doc, allowingReadAccessTo: doc.deletingLastPathComponent())
        }
        return view
    }
    func updateUIView(_ view: WKWebView, context: Context) {}
}
