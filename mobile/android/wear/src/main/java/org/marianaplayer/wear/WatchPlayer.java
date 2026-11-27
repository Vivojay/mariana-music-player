package org.marianaplayer.wear;

import android.app.Activity;
import android.content.res.AssetFileDescriptor;
import android.os.Handler;
import android.content.ClipData;
import android.content.Intent;
import android.content.ActivityNotFoundException;
import java.io.InputStream;
import java.io.File;
import java.nio.file.Files;
import java.util.Locale;
import androidx.core.content.FileProvider;
import android.os.Looper;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.widget.*;
import java.io.IOException;

/** Standalone, foreground-only stream playback for Wear OS. */
public final class WatchPlayer extends Activity {
    private MediaPlayer player;
    private AudioManager audioManager;
    private AudioFocusRequest focus;
    private final AudioAttributes attributes = new AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build();
    private boolean ready;
    private EditText url;
    private Button play;
    private TextView status, lyric;
    private SeekBar practiceSeek;
    private LinearLayout clipActions;
    private TextView clipMarks;
    private int clipStart, clipEnd;
    private PracticeScore practice;
    private boolean dragging;
    private final Handler clock = new Handler(Looper.getMainLooper());
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (ready && practice != null && player != null) {
                int position = player.getCurrentPosition();
                lyric.setText(practice.at(position));
                if (!dragging) practiceSeek.setProgress(position);
                if (player.isPlaying()) clock.postDelayed(this, 80);
            }
        }
    };
    private void refreshClock() {
        clock.removeCallbacks(tick);
        tick.run();
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        audioManager = (AudioManager)getSystemService(AUDIO_SERVICE);
        focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(attributes)
            .setWillPauseWhenDucked(true)
            .setOnAudioFocusChangeListener(change -> {
                if (change < 0 && ready) pauseStream();
            }).build();
        ScrollView scroll = new ScrollView(this);
        LinearLayout ui = new LinearLayout(this);
        ui.setOrientation(LinearLayout.VERTICAL); ui.setGravity(Gravity.CENTER_HORIZONTAL);
        int inset = (int)(getResources().getDisplayMetrics().widthPixels*.14);
        ui.setPadding(inset,inset,inset,inset);
        status = new TextView(this); status.setText("Mariana Wear"); ui.addView(status);
        url = new EditText(this); url.setSingleLine(true); url.setHint("HTTPS audio URL");
        url.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        url.setText(getPreferences(MODE_PRIVATE).getString("lastURL", "")); ui.addView(url);
        Button open = new Button(this); open.setText("Load stream"); open.setOnClickListener(v -> load()); ui.addView(open);
        Button duet = new Button(this); duet.setText("Practice duet"); duet.setOnClickListener(v -> loadPractice()); ui.addView(duet);
        lyric = new TextView(this); lyric.setGravity(Gravity.CENTER); ui.addView(lyric);
        practiceSeek = new SeekBar(this); practiceSeek.setContentDescription("Duet playback position");
        practiceSeek.setVisibility(android.view.View.GONE);
        practiceSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar bar, int position, boolean user) {
                if (user && !dragging && ready && practice != null) seek(position);
            }
            public void onStartTrackingTouch(SeekBar bar) { dragging = true; }
            public void onStopTrackingTouch(SeekBar bar) { dragging = false; seek(bar.getProgress()); }
        });
        ui.addView(practiceSeek, new LinearLayout.LayoutParams(-1, -2));
        play = new Button(this); play.setText("Play"); play.setEnabled(false);
        play.setOnClickListener(v -> { if (!ready) return;
            if (player.isPlaying()) {
                pauseStream();
            } else if (audioManager.requestAudioFocus(focus) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
                player.start(); refreshClock();
                play.setText("Pause");
            } else {
                status.setText("Audio output is busy");
            }
        }); ui.addView(play);
        Button back = new Button(this); back.setText("Back 15 seconds");
        back.setOnClickListener(v -> { if (ready && player.getDuration() > 0) player.seekTo(Math.max(0,player.getCurrentPosition()-15000)); }); ui.addView(back);
        clipActions = new LinearLayout(this); clipActions.setOrientation(LinearLayout.VERTICAL);
        clipMarks = new TextView(this); clipActions.addView(clipMarks);
        Button in = new Button(this); in.setText("Mark start here");
        in.setOnClickListener(v -> { if (ready && practice != null) { clipStart = player.getCurrentPosition(); updateMarks(); } });
        Button out = new Button(this); out.setText("Mark end here");
        out.setOnClickListener(v -> { if (ready && practice != null) { clipEnd = player.getCurrentPosition(); updateMarks(); } });
        Button share = new Button(this); share.setText("Share selected WAV"); share.setOnClickListener(v -> sharePractice());
        clipActions.addView(in); clipActions.addView(out); clipActions.addView(share);
        clipActions.setVisibility(android.view.View.GONE); ui.addView(clipActions);
        WatchThemes.install(this,ui,status);
        scroll.addView(ui); setContentView(scroll);
    }
    private void updateMarks() {
        clipMarks.setText(String.format(Locale.getDefault(), "Clip %.2fs → %.2fs", clipStart / 1000.0, clipEnd / 1000.0));
    }
    private void sharePractice() {
        if (practice == null || !ready) return;
        try (InputStream wave = getAssets().open("practice-duet.wav")) {
            // The packaged asset is bounded. Each range has an immutable name while its read grant is active.
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            byte[] b = new byte[8192];
            for (int n; (n = wave.read(b)) != -1;) bytes.write(b, 0, n);
            byte[] clip = PracticeClip.encode(bytes.toByteArray(), clipStart, clipEnd);
            File root = new File(getCacheDir(), "watch-clips");
            Files.createDirectories(root.toPath());
            File[] old = root.listFiles();
            if (old != null) for (File f : old) if (f.lastModified() < System.currentTimeMillis() - 86400000L) f.delete();
            File file = File.createTempFile("Mariana-duet-" + clipStart + "-" + clipEnd + "-", ".wav", root);
            Files.write(file.toPath(), clip);
            Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".clips", file);
            Intent send = new Intent(Intent.ACTION_SEND).setType("audio/wav").putExtra(Intent.EXTRA_STREAM, uri);
            send.setClipData(ClipData.newRawUri("Mariana duet clip", uri));
            send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            if (send.resolveActivity(getPackageManager()) == null) {
                status.setText("No installed watch app accepts WAV files."); return;
            }
            startActivity(Intent.createChooser(send, "Share duet clip"));
        } catch (IllegalArgumentException | IOException | ActivityNotFoundException error) {
            status.setText("Could not share. Choose a start before the end and an app that accepts audio.");
        }
    }
    private void loadPractice() {
        closePlayer();
        try {
            PracticeScore score = PracticeScore.load(getAssets());
            try (AssetFileDescriptor fd = getAssets().openFd("practice-duet.wav")) {
                configurePlayer("Practice duet", score);
                player.setDataSource(fd.getFileDescriptor(), fd.getStartOffset(), fd.getLength());
            }
            player.prepareAsync();
        } catch (Exception error) { closePlayer(); status.setText("Practice unavailable: recording or timing could not be verified."); }
    }
    private void seek(int ms) {
        if (ready && practice != null) player.seekTo(ms, MediaPlayer.SEEK_CLOSEST);
    }
    private void load() {
        Uri uri = Uri.parse(url.getText().toString().trim());
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null) { status.setText("Enter an HTTPS media URL"); return; }
        closePlayer();
        configurePlayer(uri.getHost(), null);
        try { player.setDataSource(this,uri); player.prepareAsync(); getPreferences(MODE_PRIVATE).edit().putString("lastURL",uri.toString()).apply(); }
        catch (IOException | RuntimeException e) { closePlayer(); status.setText("Cannot load stream"); }
    }
    private void configurePlayer(String title, PracticeScore score) {
        player = new MediaPlayer(); status.setText("Loading…");
        practice = score;
        if (score == null) lyric.setText("Karaoke unavailable · no verified 90% timing sheet for this stream.");
        player.setAudioAttributes(attributes);
        player.setOnPreparedListener(p -> {
            if (player != p) return;
            if (practice != null && Math.abs((long)p.getDuration() - practice.duration) > 250) {
                closePlayer(); status.setText("Karaoke unavailable · recording duration differs from timing sheet."); return;
            }
            ready = true; play.setEnabled(true); play.setText("Play"); status.setText(title);
            if (practice != null) {
                status.setText(title + " · " + (int)Math.round(100 * practice.confidence) + "% timing");
                clipStart = 0; clipEnd = practice.duration; updateMarks();
                clipActions.setVisibility(android.view.View.VISIBLE);
                practiceSeek.setMax(practice.duration);
                practiceSeek.setVisibility(android.view.View.VISIBLE);
                refreshClock();
            }
        });
        player.setOnSeekCompleteListener(p -> { if (p == player) refreshClock(); });
        player.setOnErrorListener((p, what, extra) -> { if (p == player) { closePlayer(); status.setText("Audio unavailable"); } return true; });
        player.setOnCompletionListener(p -> {
            if (p != player) return;
            audioManager.abandonAudioFocusRequest(focus);
            play.setText("Play");
            refreshClock();
        });
    }
    private void pauseStream() {
        if (ready && player.isPlaying()) player.pause();
        refreshClock();
        audioManager.abandonAudioFocusRequest(focus);
        play.setText("Play");
    }
    private void closePlayer() {
        ready = false; practice = null; dragging = false;
        clock.removeCallbacks(tick);
        clipActions.setVisibility(android.view.View.GONE); lyric.setText(""); practiceSeek.setVisibility(android.view.View.GONE);
        play.setEnabled(false);
        audioManager.abandonAudioFocusRequest(focus);
        if (player != null) {
            player.release();
            player = null;
        }
    }
    @Override protected void onStop() { super.onStop(); if (ready) pauseStream(); }
    @Override protected void onDestroy() { closePlayer(); super.onDestroy(); }
}
