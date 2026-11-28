"""Watch bundle packaging and lossless Wear wave export from the shared duet."""
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_both_watch_targets_package_the_canonical_duet():
    android = ROOT / "mobile/android/wear"
    assert "sourceSets.main.assets.srcDir '../../../res/karaoke'" in (android / "build.gradle").read_text()
    apple = ROOT / "mobile/apple"
    target = (apple / "project.yml").read_text().split("  MarianaWatch:", 1)[1]
    for name in ("practice-duet.wav", "practice-duet.json"):
        assert f"- path: ../../res/karaoke/{name}" in target
        assert (android / "../../../res/karaoke" / name).resolve() == (apple / "../../res/karaoke" / name).resolve()
        assert (ROOT / "res/karaoke" / name).is_file()


def test_wear_sample_accurate_export(tmp_path):
    compiler = shutil.which("javac")
    runtime = shutil.which("java")
    if not compiler or not runtime:
        pytest.skip("JDK required to execute the native Wear WAV writer")
    harness = tmp_path / "ClipCheck.java"
    harness.write_text("""
package org.marianaplayer.wear;
import java.nio.file.*;
class ClipCheck {
    public static void main(String[] args) throws Exception {
        byte[] sample = Files.readAllBytes(Paths.get(args[0]));
        Files.write(Paths.get(args[1]), PracticeClip.encode(sample, 3412, 4023));
        try { PracticeClip.encode(sample, 0, 7000); throw new AssertionError("Invalid range accepted"); }
        catch (IllegalArgumentException expected) {}
    }
}
""")
    writer = ROOT / "mobile/android/wear/src/main/java/org/marianaplayer/wear/PracticeClip.java"
    subprocess.run([compiler, "-d", str(tmp_path), str(writer), str(harness)], check=True)
    source = ROOT / "res/karaoke/practice-duet.wav"
    dest = tmp_path / "clip.wav"
    subprocess.run([runtime, "-cp", str(tmp_path), "org.marianaplayer.wear.ClipCheck", str(source), str(dest)], check=True)
    with wave.open(str(source)) as original, wave.open(str(dest)) as clip:
        assert clip.getframerate() == original.getframerate() == 12000
        original.setpos(40944)
        assert clip.getnframes() == 7332
        assert clip.readframes(7332) == original.readframes(7332)
