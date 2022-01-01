from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, ISimpleAudioVolume

systemIsMuted = 0

def device_refresh():
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))

    return volume

def get_master_volume():
    volume = device_refresh()
    return int(round(volume.GetMasterVolumeLevelScalar() * 100))

def set_master_volume(scalarVolume):
    volume = device_refresh()
    if scalarVolume > 0:
        volume.SetMasterVolumeLevelScalar(scalarVolume/100, None)
    else: pass

# TODO - Implement voltransition... (soft vol change...)

