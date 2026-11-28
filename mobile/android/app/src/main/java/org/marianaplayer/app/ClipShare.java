package org.marianaplayer.app;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.util.Base64;
import android.webkit.WebMessage;
import android.webkit.WebMessagePort;
import android.webkit.WebView;
import androidx.core.content.FileProvider;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Origin-bound file handoff for the phone's bundled main document. */
final class ClipShare {
    private static final int LIMIT = 32 * 1024 * 1024;
    private final Activity activity;
    private final File directory;
    private WebMessagePort port;
    private File current;
    private FileOutputStream output;
    private int expected, received;
    private String mime, name, target;
    private double seconds;

    ClipShare(Activity activity) {
        this.activity = activity;
        directory = new File(activity.getCacheDir(), "shared-clips");
        File[] old = directory.listFiles();
        if (old != null) for (File f : old) {
            if (f.lastModified() < System.currentTimeMillis() - 86400000L) f.delete();
        }
    }
    void attach(WebView web, Uri origin) {
        close();
        WebMessagePort[] pair = web.createWebMessageChannel();
        port = pair[0];
        port.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override public void onMessage(WebMessagePort channel, WebMessage message) {
                if (channel != port) return;
                try {
                    if (message.getData() == null || message.getData().length() > 67000) throw new IOException("File block is too large.");
                    JSONObject fields = new JSONObject(message.getData());
                    if ("targets".equals(fields.optString("op"))) {
                        channel.postMessage(new WebMessage(targets(fields.getString("mime"), fields.optDouble("seconds", 0), fields.optBoolean("portrait")).toString()));
                    } else {
                        receive(fields); channel.postMessage(new WebMessage("ok"));
                    }
                } catch (Exception error) {
                    discard();
                    channel.postMessage(new WebMessage("Could not open this destination. Choose All apps or check available storage."));
                }
            }
        });
        web.postWebMessage(new WebMessage("MarianaClipPort", new WebMessagePort[]{pair[1]}), origin);
    }
    private void receive(JSONObject message) throws JSONException, IOException {
        switch (message.getString("op")) {
            case "link": {
                String link = message.getString("url");
                Uri uri = Uri.parse(link);
                if (link.length() > 2048 || !"https".equals(uri.getScheme()) || uri.getHost() == null
                        || uri.getUserInfo() != null || uri.getPort() != -1) throw new IOException("Invalid public link.");
                Intent intent = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, link);
                activity.startActivity(Intent.createChooser(intent, "Share music link"));
                return;
            }
            case "start":
                discard();
                mime = message.getString("mime");
                String ext;
                if ("audio/wav".equals(mime)) ext = ".wav";
                else if ("audio/mp4".equals(mime)) ext = ".m4a";
                else if ("audio/webm".equals(mime)) ext = ".webm";
                else if ("audio/ogg".equals(mime)) ext = ".ogg";
                else if ("text/vtt".equals(mime)) ext = ".vtt";
                else if ("text/plain".equals(mime)) ext = ".txt";
                else if ("video/mp4".equals(mime)) ext = ".mp4";
                else if ("video/webm".equals(mime)) ext = ".webm";
                else throw new IOException("Unsupported file type");
                target = message.optString("target", "system");
                seconds = message.optDouble("seconds", 0);
                if ("instagram-story".equals(target) && !message.optBoolean("portrait")) throw new IOException("Portrait video required");
                expected = message.getInt("size");
                if (expected < 1 || expected > LIMIT) throw new IOException("Unsupported file size");
                name = message.getString("name").replaceAll("[^\\p{L}\\p{N} _.\\-]", "_");
                if (name.length() > 100 || !name.endsWith(ext)) name = "Mariana-clip" + ext;
                if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Storage unavailable");
                current = File.createTempFile("clip-", ext, directory);
                output = new FileOutputStream(current);
                break;
            case "chunk":
                if (output == null) throw new IOException("No active transfer");
                byte[] chunk = Base64.decode(message.getString("data"), Base64.NO_WRAP);
                if (chunk.length == 0 || chunk.length > 49152 || received + chunk.length > expected) throw new IOException("Invalid file block");
                output.write(chunk); received += chunk.length;
                break;
            case "finish":
                if (output == null || received != expected) throw new IOException("Incomplete transfer");
                output.close(); output = null;
                Uri file = FileProvider.getUriForFile(activity, activity.getPackageName() + ".clips", current, name);
                Intent send = targetIntent(target, mime, file, seconds);
                if (send == null) throw new IOException("Selected app unavailable");
                send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                send.setClipData(ClipData.newRawUri("Mariana clip", file));
                activity.startActivity("system".equals(target) ? Intent.createChooser(send, "Share clip") : send);
                current = null; received = 0;
                break;
            case "cancel": discard(); break;
            default: throw new IOException("Unknown file operation");
        }
    }
    private String appId() {
        try {
            String configured = activity.getPackageManager().getApplicationInfo(
                activity.getPackageName(), PackageManager.GET_META_DATA).metaData.getString("org.marianaplayer.META_APP_ID", "");
            return configured.matches("id:[0-9]{1,25}") ? configured.substring(3) : "";
        } catch (Exception ignored) { return ""; }
    }
    private Intent targetIntent(String target, String type, Uri file, double duration) {
        if ("instagram-story".equals(target)) {
            String id = appId();
            if (id.isEmpty() || !(duration > 0 && duration <= 20.001) || !type.startsWith("video/")) return null;
            Intent story = new Intent("com.instagram.share.ADD_TO_STORY").setPackage("com.instagram.android")
                .setDataAndType(file, type).putExtra("source_application", id);
            return story.resolveActivity(activity.getPackageManager()) != null ? story : null;
        }
        Intent send = new Intent(Intent.ACTION_SEND).setType(type).putExtra(Intent.EXTRA_STREAM, file);
        if ("system".equals(target)) return send;
        String[] packages;
        switch (target) {
            case "instagram": packages = new String[]{"com.instagram.android"}; break;
            case "snapchat": packages = new String[]{"com.snapchat.android"}; break;
            case "tiktok": packages = new String[]{"com.zhiliaoapp.musically", "com.ss.android.ugc.trill"}; break;
            default: return null;
        }
        for (String pkg : packages) {
            send.setPackage(pkg);
            if (send.resolveActivity(activity.getPackageManager()) != null) return send;
        }
        return null;
    }
    private JSONArray targets(String type, double duration, boolean portrait) throws JSONException {
        JSONArray result = new JSONArray();
        Uri check = Uri.parse("content://" + activity.getPackageName() + ".clips/clips/preview");
        String[][] candidates = {{"instagram-story", "Instagram Stories"}, {"instagram", "Instagram"},
            {"snapchat", "Snapchat"}, {"tiktok", "TikTok"}};
        for (String[] c : candidates) {
            String reason = "";
            if ("instagram-story".equals(c[0]) && (!portrait || !type.startsWith("video/"))) reason = "prepare a portrait video";
            else if ("instagram-story".equals(c[0]) && duration > 20.001) reason = "choose up to 20 seconds";
            else if ("instagram-story".equals(c[0]) && appId().isEmpty()) reason = "publisher setup required";
            else if (targetIntent(c[0], type, check, duration) == null) reason = "app unavailable for this format";
            result.put(new JSONObject().put("id", c[0]).put("name", c[1]).put("reason", reason));
        }
        return result;
    }
    private void discard() {
        if (output != null) { try { output.close(); } catch (IOException ignored) {} output = null; }
        if (current != null) { current.delete(); current = null; }
        received = 0;
    }
    void close() {
        if (port != null) { port.close(); port = null; }
        discard();
    }
}
