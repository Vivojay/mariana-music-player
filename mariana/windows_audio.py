"""Read only the Core Audio properties needed by Mariana.

Callers own COM initialization on their thread. Avoid full property-store
enumeration: optional driver properties can be unreadable on healthy devices.
"""

from __future__ import annotations

import sys
from typing import Any


def default_endpoint():
    if sys.platform != "win32":
        raise ImportError("Windows Core Audio is unavailable on this platform")
    import comtypes
    from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
    from pycaw.constants import CLSID_MMDeviceEnumerator, EDataFlow, ERole

    # comtypes supplies interface methods dynamically from the COM declaration.
    enumerator: Any = comtypes.CoCreateInstance(
        CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER,
    )
    return enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)


def endpoint_identity(endpoint) -> tuple[str, str]:
    if sys.platform != "win32":
        raise ImportError("Windows Core Audio is unavailable on this platform")
    from comtypes import GUID
    from pycaw.api.mmdeviceapi.depend.structures import PROPERTYKEY
    from pycaw.constants import STGM

    store = endpoint.OpenPropertyStore(STGM.STGM_READ.value)
    key = PROPERTYKEY()
    key.fmtid = GUID("{a45c254e-df1c-4efd-8020-67d146a850e0}")
    key.pid = 14  # DEVPKEY_Device_FriendlyName
    value = store.GetValue(key)
    try:
        name = str(value.GetValue() or "").strip()
    finally:
        value.clear()
    return str(endpoint.GetId() or "").strip(), name


def endpoint_volume():
    if sys.platform != "win32":
        raise ImportError("Windows Core Audio is unavailable on this platform")
    import comtypes
    from pycaw.api.endpointvolume import IAudioEndpointVolume

    endpoint = default_endpoint()
    if endpoint is None:
        return None
    interface = endpoint.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)
