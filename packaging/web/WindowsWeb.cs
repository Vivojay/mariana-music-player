// Windows .NET Framework 4.5+ launcher for the portable player. No administrator access required.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

internal static class MarianaWeb {
    private sealed class Asset {
        public byte[] Bytes;
        public string ETag;
        public string Type;
    }

    private static readonly Dictionary<string, Asset> Assets = new Dictionary<string, Asset>(StringComparer.Ordinal);
    private static readonly Semaphore Clients = new Semaphore(16, 16);
    private static volatile bool stopping;

    private static string ContentType(string name) {
        switch (Path.GetExtension(name).ToLowerInvariant()) {
            case ".js": return "text/javascript; charset=utf-8";
            case ".css": return "text/css; charset=utf-8";
            case ".html": return "text/html; charset=utf-8";
            case ".json": return "application/json";
            case ".webmanifest": return "application/manifest+json";
            case ".png": return "image/png";
            case ".wav": return "audio/wav";
            case ".wasm": return "application/wasm";
            default: return "application/octet-stream";
        }
    }

    private static void ReadAssets() {
        using (var source = Assembly.GetExecutingAssembly().GetManifestResourceStream("MarianaWebAssets"))
        using (var archive = new ZipArchive(source, ZipArchiveMode.Read))
        using (var hash = SHA256.Create()) {
            const string folder = "web-player/";
            foreach (var entry in archive.Entries) {
                if (!entry.FullName.StartsWith(folder, StringComparison.Ordinal) || entry.Name.Length == 0) continue;
                var path = "/" + entry.FullName.Substring(folder.Length);
                using (var input = entry.Open())
                using (var output = new MemoryStream()) {
                    input.CopyTo(output);
                    var bytes = output.ToArray();
                    Assets.Add(path, new Asset {
                        Bytes = bytes, Type = ContentType(path),
                        ETag = "\"" + BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant() + "\""
                    });
                }
            }
        }
        if (!Assets.ContainsKey("/index.html") || !Assets.ContainsKey("/sw.js"))
            throw new InvalidDataException("The player assets are incomplete.");
    }

    private static string[] ReadRequest(Stream stream) {
        const int limit = 16384;
        byte[] headers = new byte[limit];
        for (int i = 0; i < limit; i++) {
            int value = stream.ReadByte();
            if (value < 0) return null;
            headers[i] = (byte)value;
            if (i >= 3 && value == 10 && headers[i-1] == 13 && headers[i-2] == 10 && headers[i-3] == 13)
                return Encoding.ASCII.GetString(headers, 0, i-3).Split(new [] { "\r\n" }, StringSplitOptions.None);
        }
        return null;
    }

    private static string Header(string[] lines, string name) {
        string prefix = name + ":";
        string value = null;
        for (int i = 1; i < lines.Length; i++) {
            if (!lines[i].StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) continue;
            if (value != null) return null;
            value = lines[i].Substring(prefix.Length).Trim();
        }
        return value;
    }

    private static void Send(Stream stream, string status, string type, byte[] data, string etag, bool head) {
        string headers = "HTTP/1.1 " + status + "\r\nConnection: close\r\nReferrer-Policy: no-referrer\r\n" +
            "X-Content-Type-Options: nosniff\r\nCache-Control: " + (etag == null ? "no-store" : "no-cache") + "\r\n";
        if (etag != null) headers += "ETag: " + etag + "\r\n";
        if (data != null) headers += "Content-Type: " + type + "\r\nContent-Length: " + data.Length.ToString(CultureInfo.InvariantCulture) + "\r\n";
        var bytes = Encoding.ASCII.GetBytes(headers + "\r\n");
        stream.Write(bytes, 0, bytes.Length);
        if (!head && data != null) stream.Write(data, 0, data.Length);
        stream.Flush();
    }

    private static void Handle(TcpClient client, int port) {
        using (client) {
            client.ReceiveTimeout = 5000;
            client.SendTimeout = 5000;
            using (var stream = client.GetStream())
            using (var input = new BufferedStream(stream)) {
                var lines = ReadRequest(input);
                if (lines == null) return;
                var request = lines[0].Split(' ');
                if (request.Length != 3) return;
                var host = Header(lines, "Host");
                var head = request[0] == "HEAD";
                var path = request[1].Split('?')[0];
                bool defaultHost = port == 80 && (host == "127.0.0.1" || String.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase));
                if (!defaultHost && host != "127.0.0.1:" + port && !String.Equals(host, "localhost:" + port, StringComparison.OrdinalIgnoreCase)) {
                    Send(stream, "403 Forbidden", "text/plain", new byte[0], null, head);
                } else if (request[0] == "POST" && (path == "/api/accounts" || path == "/api/jam")) {
                    Send(stream, "503 Service Unavailable", "application/json",
                         Encoding.UTF8.GetBytes("{\"error\":\"The native bridge requires the local Mariana Python player.\"}"), null, false);
                } else if (request[0] != "GET" && !head) {
                    Send(stream, "405 Method Not Allowed", "text/plain", new byte[0], null, false);
                } else if (path == "/healthz") {
                    Send(stream, "200 OK", "application/json", Encoding.UTF8.GetBytes("{\"status\":\"ready\",\"surface\":\"web\"}"), null, head);
                } else {
                    if (path == "/") path = "/index.html";
                    if (path == "/favicon.ico") path = "/icon-192.png";
                    Asset asset;
                    if (!Assets.TryGetValue(path, out asset)) Send(stream, "404 Not Found", "text/plain", new byte[0], null, head);
                    else if (Header(lines, "If-None-Match") == asset.ETag) Send(stream, "304 Not Modified", "", null, asset.ETag, true);
                    else Send(stream, "200 OK", asset.Type, asset.Bytes, asset.ETag, head);
                }
            }
        }
    }

    public static int Main(string[] args) {
        int port = 8767;
        string view = null;
        bool open = true;
        for (int i = 0; i < args.Length; i++) {
            string arg = args[i];
            if (arg == "--help" || arg == "-h") {
                Console.WriteLine("Mariana-Web [--view console|flow|voice] [--port 8767] [--no-open]");
                return 0;
            } else if (arg == "--no-open") open = false;
            else if (arg == "--port" && i + 1 < args.Length && Int32.TryParse(args[++i], out port) && port >= 0 && port <= 65535) continue;
            else if (arg == "--view" && i + 1 < args.Length && Array.IndexOf(new [] {"console", "flow", "voice"}, args[i+1]) >= 0)
                view = args[++i];
            else { Console.Error.WriteLine("Invalid arguments. Use --help."); return 2; }
        }
        var server = new TcpListener(IPAddress.Loopback, port);
        server.ExclusiveAddressUse = true;
        try {
            ReadAssets();
            server.Start(32);
            int activePort = ((IPEndPoint)server.LocalEndpoint).Port;
            string url = "http://127.0.0.1:" + activePort + "/" + (view == null ? "" : "?view=" + view);
            Console.WriteLine("Mariana is ready at " + url);
            Console.WriteLine("Press Ctrl+C in this window to quit.");
            if (open) {
                try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
                catch (System.ComponentModel.Win32Exception) { }
            }
            Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs e) {
                e.Cancel = true;
                stopping = true;
                server.Stop();
            };
            while (!stopping) {
                Clients.WaitOne();
                var client = server.AcceptTcpClient();
                ThreadPool.QueueUserWorkItem(delegate {
                    try { Handle(client, activePort); }
                    catch (IOException) { }
                    catch (SocketException) { }
                    finally { Clients.Release(); }
                });
            }
        } catch (Exception e) {
            if (!stopping) { Console.Error.WriteLine("Could not start Mariana: " + e.Message); return 1; }
        } finally { server.Stop(); }
        return 0;
    }
}
