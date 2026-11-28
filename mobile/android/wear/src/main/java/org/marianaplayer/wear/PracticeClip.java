package org.marianaplayer.wear;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Slice the bundled generator's canonical 44-byte-header PCM wave at sample boundaries. */
final class PracticeClip {
    static byte[] encode(byte[] wave, int fromMs, int toMs) {
        if (wave.length < 44 || !tag(wave, 0, "RIFF") || !tag(wave, 8, "WAVE")
                || !tag(wave, 12, "fmt ") || !tag(wave, 36, "data")) {
            throw new IllegalArgumentException("The rehearsal audio format changed.");
        }
        ByteBuffer header = ByteBuffer.wrap(wave).order(ByteOrder.LITTLE_ENDIAN);
        int rate = header.getInt(24), stride = header.getShort(32);
        if (header.getInt(16) != 16 || header.getShort(20) != 1 || rate <= 0 || rate > 384000
                || stride <= 0 || header.getInt(40) != wave.length - 44 || fromMs < 0 || toMs <= fromMs) {
            throw new IllegalArgumentException("Choose a valid PCM clip range.");
        }
        long first = ((long) fromMs * rate + 500) / 1000 * stride;
        long last = ((long) toMs * rate + 500) / 1000 * stride;
        if (last <= first || last > wave.length - 44) throw new IllegalArgumentException("Choose an end within the duet.");
        int size = (int)(last - first);
        byte[] out = Arrays.copyOf(wave, 44 + size);
        System.arraycopy(wave, 44 + (int)first, out, 44, size);
        ByteBuffer.wrap(out).order(ByteOrder.LITTLE_ENDIAN).putInt(4, 36 + size).putInt(40, size);
        return out;
    }
    private static boolean tag(byte[] data, int at, String name) {
        return new String(data, at, 4, StandardCharsets.US_ASCII).equals(name);
    }
}
