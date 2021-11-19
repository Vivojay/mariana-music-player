import pyaudio
import sys
import numpy as np
import wave
import struct



File = r'D:\-COMPUTERS-\My Py Files\Music Player\new.wav'
start = 12
length=7
chunk = 1024

spf = wave.open(File, 'rb')
signal = spf.readframes(-1)
signal = np.fromstring(signal, 'Int16')
p = pyaudio.PyAudio()

stream = p.open(
            format = p.get_format_from_width(spf.getsampwidth()),
            channels = spf.getnchannels(),
            rate = spf.getframerate(),
            output = True
        )


pos=spf.getframerate()*length

signal =signal[start*spf.getframerate():(start*spf.getframerate()) + pos]

sig=signal[1:chunk]

sinc = 0
data=0


#play 
while data != '':
    data = struct.pack("%dh"%(len(sig)), *list(sig))    
    stream.write(data)
    inc=inc+chunk
    sig=signal[inc:inc+chunk]


stream.close()
p.terminate()
