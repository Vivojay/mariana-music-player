from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, ISimpleAudioVolume

devices = AudioUtilities.GetSpeakers()
interface = devices.Activate(
   IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
volume = cast(interface, POINTER(IAudioEndpointVolume))

systemIsMuted = 0

def get_master_volume():
    return int(round(volume.GetMasterVolumeLevelScalar() * 100))

def set_master_volume(scalarVolume):
    if scalarVolume > 0:
        volume.SetMasterVolumeLevelScalar(scalarVolume/100, None)
    else: pass

