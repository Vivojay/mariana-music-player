import hashlib
import io
import struct
import wave
import zipfile

import pytest

from mariana import wavetables as bank


def test_entire_bank_is_distinct_and_framed():
    names = bank.names()
    assert len(names) == len(set(names)) == 64
    coefficients = [tuple(tuple(frame) for frame in bank.spectrum(name)) for name in names]
    assert len(set(coefficients)) == 64
    assert all(len(set(table)) == bank.FRAMES for table in coefficients)
    wav = bank.table_wav('glass-opal')
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getnframes()) == (1, 2, bank.FRAMES*bank.FRAME)
        signal = struct.unpack(f'<{w.getnframes()}h', w.readframes(w.getnframes()))
        assert max(signal) <= 32000 and min(signal) >= -32000


def test_preview_duration_level_and_pitch_are_usable():
    with wave.open(io.BytesIO(bank.preview_wav('bass-velvet', 220))) as w:
        assert w.getnframes() == w.getframerate() * 2
        sig = struct.unpack(f'<{w.getnframes()}h',w.readframes(w.getnframes()))
    assert sig[0] == sig[-1] == 0 and 500 < max(sig) <= 7500
    middle = sig[bank.RATE//4:bank.RATE*3//4]
    up = sum(a <= 0 < b for a,b in zip(middle,middle[1:]))
    assert abs(2*up - 220) < 4
    for bad in (float('nan'), 0, 42000):
        with pytest.raises(ValueError): bank.preview_wav('reed-amber',bad)


def test_bank_export_never_replaces_an_existing_file(tmp_path, monkeypatch):
    out = tmp_path / 'bank.zip'
    # Verify filenames, metadata and exclusive creation without synthesizing 64 banks twice.
    monkeypatch.setattr(bank, 'names', lambda: ['reed-amber', 'glass-opal'])
    monkeypatch.setattr(bank, 'table_wav', lambda n: n.encode())
    bank.export_bank(out)
    digest = hashlib.sha256(out.read_bytes()).digest()
    with zipfile.ZipFile(out) as z:
        assert z.read('glass/glass-opal.wav') == b'glass-opal'
        assert '2048' in z.read('README.txt').decode()
    with pytest.raises(FileExistsError):
        bank.export_bank(out)
    assert hashlib.sha256(out.read_bytes()).digest() == digest
