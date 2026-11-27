import concurrent.futures
import wave

import numpy as np
import pytest

from mariana.tone_keys import KeyboardMixer
from mariana.tone_procedures import BANK, RATE, command, procedure_names
from mariana.tones import render_tone


def frames(path):
    with wave.open(str(path),"rb") as f:
        assert (f.getnchannels(),f.getframerate(),f.getsampwidth()) == (2,RATE,2)
        return np.frombuffer(f.readframes(f.getnframes()),dtype="<i2").reshape(-1,2)


def test_twinkle_full_melody_chords_bass_and_stereo_chorus(tmp_path):
    library = tmp_path/"library.db"
    song = command(["procedure","play","twinkle"], library)
    assert not library.exists()
    assert song.title == "Twinkle, Twinkle, Little Star" and song.seconds == 28.8
    melody,chords,bass = song.parts
    assert [step.pitches for step in melody.notes[:7]] == [(72,),(72,),(79,),(79,),(81,),(81,),(79,)]
    assert len(melody.notes)==42 and all(len(step.pitches)==3 for step in chords.notes)
    assert len(bass.notes)==24 and bass.notes[-1].pitches==(48,)
    data = frames(render_tone(song,tmp_path))
    assert len(data)==RATE*song.seconds and np.abs(data.astype(int)).max() <= .32*32768 + 1
    assert np.max(np.abs(data[:,0]-data[:,1]))>100
    dry = command("procedure play twinkle --bpm 200 --chorus 0".split(),library)
    data = frames(render_tone(dry,tmp_path))
    assert dry.seconds==song.seconds/2 and np.array_equal(data[:,0],data[:,1])


def test_save_reopen_custom_hybrid_procedure_and_guard_duplicates(tmp_path):
    library = tmp_path/"scores.db"
    args="procedure save hearts 100 @glass C5 C5+E5+G5:2 R @choir C4+E4+G4:4 --chorus 45".split()
    def save():
        try: return command(args,library)
        except ValueError as error: return str(error)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda _:save(),range(2)))
    assert sum(x.startswith("Saved hearts") for x in replies)==1
    plan = command("procedure play hearts".split(),library)
    assert plan.parts[0].notes[1].pitches==(72,76,79) and plan.chorus==45
    assert plan.parts[0].notes[-1].pitches==()
    assert procedure_names(library,'he')==['hearts']
    assert "hearts" not in command(["procedure","list"], tmp_path/"other-profile.db")
    with pytest.raises(ValueError): command("procedure save twinkle 100 C4".split(), library)


@pytest.mark.parametrize("args",["synth glass C10", "synth glass C4:0","procedure play twinkle --bpm 30",
                                 "synth glass C4+E4+G4+C5+D5+F5+A5","synth bad A4","sfx ghost",
                                 "procedure save ../example 120 A4","synth glass C4 --chorus nan"])
def test_invalid_score(args,tmp_path):
    with pytest.raises(ValueError): command(args.split(),tmp_path/"library.db")


def test_sfx_bank_and_live_keys_release(tmp_path):
    for name in BANK["sfx"]:
        plan = command(["sfx",name],tmp_path/"library.db")
        path = render_tone(plan,tmp_path)
        sig = frames(path)
        assert np.max(sig)>50
    mixer = KeyboardMixer("glass",48000)
    mixer.pressed.put((0,True))
    mixer.pressed.put((4,True))
    out=np.zeros((2048,1))
    mixer.fill(out)
    assert set(mixer.active)=={0,4} and np.max(np.abs(out))>.01
    mixer.pressed.put((0,False)); mixer.pressed.put((4,False))
    for _ in range(12): mixer.fill(out)
    assert not mixer.active and np.max(abs(out))==0
