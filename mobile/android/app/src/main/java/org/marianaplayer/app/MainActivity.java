package org.marianaplayer.app;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.*;
import java.io.IOException;
import java.io.ByteArrayInputStream;
import java.util.ArrayList;
import java.util.Map;
import java.util.HashSet;
import java.util.Set;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import org.json.*;
import java.util.HashMap;

public final class MainActivity extends Activity {
    private static final String HOST = "app.mariana.invalid";
    private static final int PICK_AUDIO = 51;
    private static final Map<String,String> ASSETS = new HashMap<>();
    static {
        ASSETS.put("command-input.js","application/javascript");
        ASSETS.put("command-input.css","text/css");
        ASSETS.put("command-match.js","application/javascript");
        ASSETS.put("command-grammar.js","application/javascript");
        ASSETS.put("completion-values.js","application/javascript");
        ASSETS.put("meeting-config.js","application/javascript");
        ASSETS.put("voice.js","application/javascript");
        ASSETS.put("index.html","text/html");
        ASSETS.put("public-share.js","application/javascript");
        ASSETS.put("jams.js","application/javascript");
        ASSETS.put("accounts.js","application/javascript");
        ASSETS.put("account-config.js","application/javascript");
        ASSETS.put("accounts.css","text/css");
        ASSETS.put("companion.js","application/javascript");
        ASSETS.put("clip-media.js","application/javascript");
        ASSETS.put("clip-story.js","application/javascript");
        ASSETS.put("clip-share.js","application/javascript");
        ASSETS.put("clip.js","application/javascript");
        ASSETS.put("dj.css","text/css");
        ASSETS.put("dj.js","application/javascript");
        ASSETS.put("dj-engine.js","application/javascript");
        ASSETS.put("dj-recorder.js","application/javascript");
        ASSETS.put("clip.css","text/css");
        ASSETS.put("wall.js","application/javascript");
        ASSETS.put("catalog.js","application/javascript");
        ASSETS.put("player.js","application/javascript");
        ASSETS.put("strudel-pattern.js","application/javascript");
        ASSETS.put("strudel.js","application/javascript");
        ASSETS.put("strudel-engine.json","application/json");
        ASSETS.put("tone-keys.css","text/css");
        ASSETS.put("listener-profiles.js","application/javascript");
        ASSETS.put("soundbank-data.js","application/javascript");
        ASSETS.put("soundbank.js","application/javascript");
        ASSETS.put("tone-bank.js","application/javascript");
        ASSETS.put("tone-procedures.js","application/javascript");
        ASSETS.put("effect-studio.js","application/javascript");
        ASSETS.put("video-presets.js","application/javascript");
        ASSETS.put("video-filters.js","application/javascript");
        ASSETS.put("video-filters.css","text/css");
        ASSETS.put("effect-worklet.js","application/javascript");
        ASSETS.put("workspace.js","application/javascript");
        ASSETS.put("workspace.css","text/css");
        ASSETS.put("platform.js","application/javascript");
        ASSETS.put("tone.js","application/javascript");
        ASSETS.put("speech-capture.js","application/javascript");
        ASSETS.put("speech-dsp.js","application/javascript");
        ASSETS.put("speech-worklet.js","application/javascript");
        ASSETS.put("karaoke.js","application/javascript");
        ASSETS.put("karaoke-invite.js","application/javascript");
        ASSETS.put("karaoke-mix.js","application/javascript");
        ASSETS.put("karaoke-ttml.js","application/javascript");
        ASSETS.put("karaoke-hash.js","application/javascript");
        ASSETS.put("practice-duet.js","application/javascript");
        ASSETS.put("karaoke.css","text/css");
        ASSETS.put("transcripts.js","application/javascript");
        ASSETS.put("themes.js","application/javascript");
        ASSETS.put("directory.js","application/javascript");
        ASSETS.put("directory-data.js","application/javascript");
        ASSETS.put("directory.json","application/json");
        ASSETS.put("player.css","text/css");
        ASSETS.put("manifest.webmanifest","application/manifest+json");
        ASSETS.put("icon-192.png","image/png");
        ASSETS.put("icon-512.png","image/png");
    }
    private static boolean isVoiceInvite(Uri url) {
        return "https".equals(url.getScheme()) && "meet.jit.si".equalsIgnoreCase(url.getEncodedAuthority())
            && url.getEncodedQuery() == null && url.getEncodedFragment() == null
            && url.getEncodedPath() != null && url.getEncodedPath().matches("/[A-Za-z0-9_-]{3,160}");
    }
    private final Set<String> directoryLinks = new HashSet<>();
    private final Set<String> providerProfiles = new HashSet<>();
    private WebView player;
    private ClipShare clipShare;
    private ValueCallback<Uri[]> chooser;
    private static final int MIC_PERMISSION = 52;
    private PermissionRequest pendingMic;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        loadDirectoryLinks();
        loadProviderLinks();
        clipShare = new ClipShare(this);
        player = new WebView(this);
        setContentView(player);
        player.setOnApplyWindowInsetsListener((view,insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            return insets;
        });
        WebSettings settings = player.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        // The local app selects media only after a user command or an active queue.
        // Rendering/IndexedDB round-trips can outlive the original tap.
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        player.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView view, String url) {
                if (("https://" + HOST + "/index.html").equals(url)) {
                    clipShare.attach(view, Uri.parse("https://" + HOST));
                }
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri url = request.getUrl();
                if (request.isForMainFrame() && request.hasGesture() && (directoryLinks.contains(directoryKey(url)) || isProviderProfile(url) || isVoiceInvite(url))) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW,url).addCategory(Intent.CATEGORY_BROWSABLE)); }
                    catch (android.content.ActivityNotFoundException ignored) {
                        android.widget.Toast.makeText(MainActivity.this,"Copy the address to open it in a browser.",android.widget.Toast.LENGTH_LONG).show();
                    }
                }
                return true;  // Keep remote documents out of the local player.
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri url = request.getUrl();
                if (!HOST.equals(url.getHost())) return null;
                String name = url.getPath() == null ? "" : url.getPath().replaceFirst("^/", "");
                String mime = ASSETS.get(name);
                if (mime != null) try { return new WebResourceResponse(mime, mime.startsWith("image/") ? null : "UTF-8", getAssets().open(name)); }
                catch (IOException ignored) { /* return a local miss */ }
                return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", null, new ByteArrayInputStream(new byte[0]));
            }
        });
        player.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) {
                String[] resources = request.getResources();
                if (!localMicOrigin(request) || resources.length != 1 ||
                    !PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[0]) || pendingMic != null) {
                    request.deny(); return;
                }
                if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) == android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE}); return;
                }
                pendingMic = request;
                requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO}, MIC_PERMISSION);
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request) {
                if (request == pendingMic) pendingMic = null;
            }
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> next, FileChooserParams params) {
                if (chooser != null) chooser.onReceiveValue(null);
                chooser = next;
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"audio/*","video/mp4","application/octet-stream","application/json","text/json","text/plain","application/javascript","text/javascript","application/xml","text/xml","application/ttml+xml"})
                    .putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);
                try { startActivityForResult(pick, PICK_AUDIO); }
                catch (android.content.ActivityNotFoundException e) { chooser.onReceiveValue(null); chooser = null; }
                return true;
            }
        });
        player.loadUrl("https://" + HOST + "/index.html");
    }
    private boolean localMicOrigin(PermissionRequest request) {
        Uri origin = request.getOrigin();
        return origin != null && "https".equals(origin.getScheme()) && HOST.equals(origin.getHost())
            && origin.getPort() == -1 && origin.getUserInfo() == null
            && ("https://" + HOST + "/index.html").equals(player.getUrl());
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code != MIC_PERMISSION || pendingMic == null) return;
        PermissionRequest request = pendingMic;
        pendingMic = null;
        if (results.length == 1 && results[0] == android.content.pm.PackageManager.PERMISSION_GRANTED && localMicOrigin(request))
            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
        else request.deny();
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request,result,data);
        if (request != PICK_AUDIO || chooser == null) return;
        ArrayList<Uri> items = new ArrayList<>();
        if (result == RESULT_OK && data != null) {
            ClipData clip = data.getClipData();
            if (clip == null) addContent(items, data.getData());
            else for (int i=0; i<clip.getItemCount(); i++) addContent(items,clip.getItemAt(i).getUri());
        }
        chooser.onReceiveValue(items.isEmpty() ? null : items.toArray(new Uri[0])); chooser = null;
    }
    private static String directoryKey(Uri url) {
        if (!"https".equalsIgnoreCase(url.getScheme()) || url.getHost() == null || url.getUserInfo() != null) return "";
        Uri.Builder key = url.normalizeScheme().buildUpon().fragment(null);
        if (url.getEncodedPath() == null || url.getEncodedPath().isEmpty()) key.encodedPath("/");
        return key.build().toString();
    }
    private void loadProviderLinks() {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(getAssets().open("account-providers.json"), "UTF-8"))) {
            StringBuilder data = new StringBuilder();
            for (String line; (line = reader.readLine()) != null;) data.append(line);
            JSONObject providers = new JSONObject(data.toString());
            for (java.util.Iterator<String> ids = providers.keys(); ids.hasNext();) {
                JSONObject entry = providers.getJSONObject(ids.next());
                directoryLinks.add(directoryKey(Uri.parse(entry.getString("site"))));
                providerProfiles.add(entry.getString("profile"));
            }
        } catch (IOException | JSONException ignored) { /* Leave unrecognized destinations in the web view. */ }
    }
    private boolean isProviderProfile(Uri url) {
        if (!"https".equals(url.getScheme()) || url.getHost() == null || url.getUserInfo() != null
            || url.getPort() != -1 || url.getQuery() != null || url.getFragment() != null) return false;
        String path = url.getPath();
        if (path == null) return false;
        for (String prefix : providerProfiles) {
            Uri base = Uri.parse(prefix);
            if (!base.getHost().equals(url.getHost()) || !path.startsWith(base.getPath())) continue;
            String handle = path.substring(base.getPath().length());
            if (!handle.equals(".") && !handle.equals("..") && handle.matches("[\\p{L}\\p{M}\\p{N}_. -]{1,80}")) return true;
        }
        return false;
    }
    private void loadDirectoryLinks() {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(getAssets().open("directory.json"),"UTF-8"))) {
            StringBuilder data = new StringBuilder();
            for (String line; (line = reader.readLine()) != null;) data.append(line);
            Object raw = new JSONTokener(data.toString()).nextValue();
            JSONArray entries = raw instanceof JSONArray ? (JSONArray)raw : ((JSONObject)raw).getJSONArray("sources");
            for (int i=0; i<entries.length(); i++) {
                String key = directoryKey(Uri.parse(entries.getJSONObject(i).getString("url")));
                if (!key.isEmpty()) directoryLinks.add(key);
            }
        } catch (IOException | JSONException ignored) {
            // The directory still displays copyable URLs when the asset cannot be read.
        }
    }
    private void addContent(ArrayList<Uri> items, Uri selected) {
        if (selected != null && "content".equals(selected.getScheme())) items.add(selected);
    }
    @Override protected void onDestroy() {
        if (chooser != null) { chooser.onReceiveValue(null); chooser=null; }
        if (pendingMic != null) { pendingMic.deny(); pendingMic = null; }
        clipShare.close();
        player.destroy(); super.onDestroy();
    }
}
