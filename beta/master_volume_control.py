from pycaw.pycaw import AudioUtilities

systemIsMuted = 0

def device_refresh():
    return AudioUtilities.GetSpeakers().EndpointVolume

def get_master_volume():
    volume = device_refresh()
    return int(round(volume.GetMasterVolumeLevelScalar() * 100))

def set_master_volume(scalarVolume):
    volume = device_refresh()
    if scalarVolume >= 0:
        volume.SetMasterVolumeLevelScalar(scalarVolume/100, None)

# TODO - Implement voltransition... (soft vol change...)

