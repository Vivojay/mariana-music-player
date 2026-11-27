package org.marianaplayer.wear;

import android.content.res.AssetManager;
import android.graphics.Typeface;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.StyleSpan;
import android.text.style.UnderlineSpan;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Locale;

/** Only the packaged rehearsal can provide a verified timing sheet on this watch. */
final class PracticeScore {
    final JSONArray segments;
    final int duration;
    final double confidence;

    static PracticeScore load(AssetManager assets) throws Exception {
        byte[] buffer = new byte[8192];
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream audio = assets.open("practice-duet.wav")) {
            for (int n; (n = audio.read(buffer)) != -1;) digest.update(buffer, 0, n);
        }
        StringBuilder hash = new StringBuilder();
        for (byte b : digest.digest()) hash.append(String.format(Locale.ROOT, "%02x", b & 255));
        try (InputStream input = assets.open("practice-duet.json"); ByteArrayOutputStream text = new ByteArrayOutputStream()) {
            for (int n; (n = input.read(buffer)) != -1;) text.write(buffer, 0, n);
            return new PracticeScore(new JSONObject(new String(text.toByteArray(), StandardCharsets.UTF_8)), hash.toString());
        }
    }

    private static void require(boolean valid) {
        if (!valid) throw new IllegalArgumentException("Timing coverage, identity or confidence is insufficient.");
    }
    private static double score(JSONObject item) throws Exception {
        Object value = item.get("confidence");
        require(value instanceof Number);
        double n = ((Number) value).doubleValue();
        require(n >= 0.90 && n <= 1);
        return n;
    }
    private static int ms(JSONObject item, String key) throws Exception {
        Object value = item.get(key);
        require(value instanceof Number);
        double n = ((Number) value).doubleValue();
        require(n >= 0 && n <= 86400000 && n == Math.floor(n));
        return (int) n;
    }
    PracticeScore(JSONObject doc, String hash) throws Exception {
        require("mariana.karaoke.v1".equals(doc.getString("schema")) && hash.equals(doc.getString("media_sha256")));
        double minimum = score(doc);
        segments = doc.getJSONArray("segments");
        duration = ms(doc, "duration_ms");
        int end = 0;
        boolean sung = false;
        for (int i = 0; i < segments.length(); i++) {
            JSONObject part = segments.getJSONObject(i);
            int start = ms(part, "start_ms");
            require(start == end);
            end = ms(part, "end_ms");
            require(end > start && end <= duration);
            JSONArray voices = part.getJSONArray("voices");
            HashSet<String> names = new HashSet<>();
            for (int j = 0; j < voices.length(); j++) {
                JSONObject voice = voices.getJSONObject(j);
                String singer = voice.getString("singer").trim();
                require(!singer.isEmpty() && names.add(singer));
                JSONArray words = voice.getJSONArray("words");
                require(words.length() > 0);
                int last = start;
                for (int k = 0; k < words.length(); k++) {
                    JSONObject word = words.getJSONObject(k);
                    int on = ms(word, "start_ms"), off = ms(word, "end_ms");
                    require(on >= last && off > on && off <= end && !word.getString("text").trim().isEmpty());
                    last = off;
                    minimum = Math.min(minimum, score(word));
                    sung = true;
                }
            }
        }
        require(end == duration && sung);
        confidence = minimum;
    }

    CharSequence at(int position) {
        if (position >= duration) return "End of duet";
        SpannableStringBuilder lyric = new SpannableStringBuilder();
        for (int i = 0; i < segments.length(); i++) {
            JSONObject part = segments.optJSONObject(i);
            if (position < part.optInt("start_ms") || position >= part.optInt("end_ms")) continue;
            JSONArray voices = part.optJSONArray("voices");
            if (voices.length() == 0) return "Instrumental";
            for (int j = 0; j < voices.length(); j++) {
                JSONObject voice = voices.optJSONObject(j);
                if (j > 0) lyric.append("\n");
                lyric.append(voice.optString("singer")).append(" · ");
                JSONArray words = voice.optJSONArray("words");
                for (int k = 0; k < words.length(); k++) {
                    JSONObject word = words.optJSONObject(k);
                    if (k > 0) lyric.append(" ");
                    int start = lyric.length();
                    lyric.append(word.optString("text"));
                    if (position >= word.optInt("start_ms") && position < word.optInt("end_ms")) {
                        lyric.setSpan(new StyleSpan(Typeface.BOLD), start, lyric.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                        lyric.setSpan(new UnderlineSpan(), start, lyric.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                    }
                }
            }
            return lyric;
        }
        return "";
    }
}
