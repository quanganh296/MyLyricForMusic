import ctypes
from ctypes import POINTER, HRESULT, c_uint32, c_void_p
from ctypes.wintypes import LPCWSTR
import time

try:
    import comtypes
    from comtypes import GUID, IUnknown, COMMETHOD
    from pycaw.pycaw import AudioUtilities, EDataFlow, DEVICE_STATE
    PYCAW_AVAILABLE = True
except Exception as e:
    print(f"[VolumeManager Warning] pycaw import failed: {e}")
    PYCAW_AVAILABLE = False


if PYCAW_AVAILABLE:
    _CLSID_CPolicyConfigClient = GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")

    class _IPolicyConfig(IUnknown):
        _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetMixFormat", (["in"], LPCWSTR, "pwstrDeviceId"), (["out"], POINTER(c_void_p), "ppFormat")),
            COMMETHOD([], HRESULT, "GetDeviceFormat", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_uint32, "bDefault"), (["out"], POINTER(c_void_p), "ppFormat")),
            COMMETHOD([], HRESULT, "ResetDeviceFormat", (["in"], LPCWSTR, "pwstrDeviceId")),
            COMMETHOD([], HRESULT, "SetDeviceFormat", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_void_p, "pEndpointFormat"), (["in"], c_void_p, "pMixFormat")),
            COMMETHOD([], HRESULT, "GetProcessingPeriod", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_uint32, "bDefault"), (["out"], POINTER(c_void_p), "pmftDefaultPeriod"), (["out"], POINTER(c_void_p), "pmftMinimumPeriod")),
            COMMETHOD([], HRESULT, "SetProcessingPeriod", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_void_p, "pftPeriod")),
            COMMETHOD([], HRESULT, "GetShareMode", (["in"], LPCWSTR, "pwstrDeviceId"), (["out"], POINTER(c_void_p), "pMode")),
            COMMETHOD([], HRESULT, "SetShareMode", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_void_p, "pMode")),
            COMMETHOD([], HRESULT, "GetPropertyValue", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_void_p, "key"), (["out"], POINTER(c_void_p), "pv")),
            COMMETHOD([], HRESULT, "SetPropertyValue", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_void_p, "key"), (["in"], c_void_p, "pv")),
            COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_uint32, "role")),
            COMMETHOD([], HRESULT, "SetEndpointVisibility", (["in"], LPCWSTR, "pwstrDeviceId"), (["in"], c_uint32, "bVisible")),
        ]


def _classify_output_device(friendly_name: str, bt_device_name: str = "") -> str:
    """Classifies a Windows render endpoint as 'bluetooth', 'headphones', or 'speaker'."""
    low = (friendly_name or "").lower()
    bt_low = (bt_device_name or "").strip().lower()
    if bt_low and len(bt_low) >= 3 and (bt_low in low or any(w in low for w in bt_low.split() if len(w) >= 4)):
        return "bluetooth"
    bt_hints = ("bluetooth", "airpods", "buds", "hands-free", "a2dp", "tws", "wireless", "bt ")
    if any(h in low for h in bt_hints):
        return "bluetooth"
    hp_hints = ("headphone", "headset", "earphone", "tai nghe", "earbuds")
    if any(h in low for h in hp_hints):
        return "headphones"
    return "speaker"


class VolumeManager:
    """
    Handles Windows master volume control for whichever playback device is currently active
    (Laptop Speakers, Bluetooth Headphones, Wired/USB Headphones, etc.) and automatically
    re-binds whenever the user switches audio output devices.
    """

    def __init__(self):
        self.spk = None
        self._enumerator = None
        self._current_device_id = None
        self._device_name = ""
        self._last_bind_attempt = 0.0

        if PYCAW_AVAILABLE:
            try:
                self._enumerator = AudioUtilities.GetDeviceEnumerator()
            except Exception as e:
                print(f"[VolumeManager Warning] Failed to get audio enumerator: {e}")
            self._bind_active_device(force=True)

    def _get_default_endpoint_id(self):
        """Fast (~0.5ms) check for the currently active Windows multimedia playback device ID."""
        if not PYCAW_AVAILABLE:
            return None
        try:
            if self._enumerator is None:
                self._enumerator = AudioUtilities.GetDeviceEnumerator()
            # eRender = 0, eMultimedia = 1 (fallback eConsole = 0)
            for role in (1, 0):
                try:
                    dev = self._enumerator.GetDefaultAudioEndpoint(0, role)
                    if dev:
                        dev_id = dev.GetId()
                        if dev_id:
                            return dev_id
                except Exception:
                    continue
        except Exception:
            self._enumerator = None
        return None

    def _bind_active_device(self, force: bool = False) -> bool:
        """Binds self.spk to the currently active default playback endpoint when device changes."""
        if not PYCAW_AVAILABLE:
            return False

        active_id = self._get_default_endpoint_id()
        if not force and self.spk is not None and active_id and active_id == self._current_device_id:
            return True

        now = time.monotonic()
        if not force and self.spk is None and (now - self._last_bind_attempt) < 1.0:
            return False
        self._last_bind_attempt = now

        try:
            spk = AudioUtilities.GetSpeakers()
            if spk is not None:
                self.spk = spk
                self._current_device_id = getattr(spk, "id", None) or active_id
                self._device_name = (getattr(spk, "FriendlyName", None) or "").strip()
                return True
        except Exception as e:
            print(f"[VolumeManager Error] Failed to bind active audio device: {e}")
            self.spk = None
            self._current_device_id = None
            self._device_name = ""
        return False

    def _read_endpoint_state(self):
        """Reads (volume_percent, is_muted, device_name) from current bound endpoint; raises on COM failure."""
        ep = self.spk.EndpointVolume
        scalar = float(ep.GetMasterVolumeLevelScalar())
        vol_pct = max(0, min(100, int(round(scalar * 100.0))))
        muted = bool(ep.GetMute())
        return vol_pct, muted, self._device_name

    def get_state(self) -> tuple:
        """
        Returns (volume_percent: int, is_muted: bool, device_name: str) for the currently
        active Windows audio playback device (speakers or headphones).
        """
        if PYCAW_AVAILABLE:
            self._bind_active_device(force=False)
            if self.spk is not None:
                try:
                    return self._read_endpoint_state()
                except Exception:
                    # Endpoint likely invalidated (headphone unplugged/reconnected) -> force rebind once
                    if self._bind_active_device(force=True) and self.spk is not None:
                        try:
                            return self._read_endpoint_state()
                        except Exception:
                            pass
        return 75, False, self._device_name

    def get_device_name(self) -> str:
        self._bind_active_device(force=False)
        return self._device_name

    def list_output_devices(self, bt_device_name: str = "") -> list:
        """
        Lists all currently active Windows audio playback (render) endpoints
        (e.g. Bluetooth Headphones, PC Speakers, Wired Headphones, HDMI Audio).
        Returns list of dicts: [{"id", "name", "is_default", "kind"}].
        """
        if not PYCAW_AVAILABLE:
            return []
        devices = []
        try:
            if self._enumerator is None:
                self._enumerator = AudioUtilities.GetDeviceEnumerator()
            active_id = self._get_default_endpoint_id()
            col = self._enumerator.EnumAudioEndpoints(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value)
            count = col.GetCount()
            for i in range(count):
                try:
                    raw = col.Item(i)
                    dev = AudioUtilities.CreateDevice(raw)
                    dev_id = getattr(dev, "id", None)
                    name = (getattr(dev, "FriendlyName", None) or "").strip()
                    if not dev_id or not name:
                        continue
                    devices.append({
                        "id": dev_id,
                        "name": name,
                        "is_default": bool(active_id and dev_id == active_id),
                        "kind": _classify_output_device(name, bt_device_name=bt_device_name),
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"[VolumeManager Error] Failed to enumerate output devices: {e}")

        # Show currently active device first, then Bluetooth/headphones, then speakers
        kind_order = {"bluetooth": 0, "headphones": 1, "speaker": 2}
        devices.sort(key=lambda d: (0 if d["is_default"] else 1, kind_order.get(d["kind"], 3), d["name"].lower()))
        return devices

    def set_default_output_device(self, device_id: str) -> bool:
        """
        Switches the Windows default playback device immediately across Console, Multimedia,
        and Communications roles WITHOUT disconnecting or toggling Bluetooth.
        """
        if not PYCAW_AVAILABLE or not device_id:
            return False
        try:
            pc = comtypes.CoCreateInstance(
                _CLSID_CPolicyConfigClient,
                interface=_IPolicyConfig,
                clsctx=comtypes.CLSCTX_ALL,
            )
            ok = False
            for role in (0, 1, 2):  # eConsole, eMultimedia, eCommunications
                hr = pc.SetDefaultEndpoint(device_id, role)
                if hr == 0:
                    ok = True
            if ok:
                # Immediately re-bind active volume endpoint to the newly chosen speaker/headphone!
                self._current_device_id = None
                self._bind_active_device(force=True)
            return ok
        except Exception as e:
            print(f"[VolumeManager Error] Failed to switch default audio device: {e}")
            return False

    def get_volume(self) -> int:
        """Returns current active device volume percentage (0 - 100)."""
        vol, _, _ = self.get_state()
        return vol

    def set_volume(self, percent: int):
        """Sets master volume percentage (0 - 100) on the currently active playback device."""
        clamped = max(0, min(100, int(percent)))
        if PYCAW_AVAILABLE:
            self._bind_active_device(force=False)
            for attempt in range(2):
                if self.spk is not None:
                    try:
                        ep = self.spk.EndpointVolume
                        ep.SetMasterVolumeLevelScalar(clamped / 100.0, None)
                        # Automatically unmute when user raises volume above 0% (matches Windows taskbar UX)
                        if clamped > 0 and bool(ep.GetMute()):
                            ep.SetMute(0, None)
                        return
                    except Exception as e:
                        if attempt == 0:
                            self._bind_active_device(force=True)
                            continue
                        print(f"[VolumeManager Error] Set master volume failed: {e}")

        # Fallback if pycaw fails: calculate delta and send volume keys
        current = self.get_volume()
        diff = clamped - current
        steps = abs(diff) // 2
        key = 0xAF if diff > 0 else 0xAE  # VK_VOLUME_UP or VK_VOLUME_DOWN
        for _ in range(steps):
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
            ctypes.windll.user32.keybd_event(key, 0, 2, 0)

    def is_muted(self) -> bool:
        """Returns True if the currently active playback device is muted."""
        _, muted, _ = self.get_state()
        return muted

    def toggle_mute(self) -> bool:
        """Toggles audio mute state on the currently active playback device. Returns new muted state."""
        if PYCAW_AVAILABLE:
            self._bind_active_device(force=False)
            for attempt in range(2):
                if self.spk is not None:
                    try:
                        ep = self.spk.EndpointVolume
                        current_mute = bool(ep.GetMute())
                        new_mute = 0 if current_mute else 1
                        ep.SetMute(new_mute, None)
                        return bool(new_mute)
                    except Exception as e:
                        if attempt == 0:
                            self._bind_active_device(force=True)
                            continue
                        print(f"[VolumeManager Error] Toggle mute failed: {e}")

        # Fallback send VK_VOLUME_MUTE
        ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
        return not self.is_muted()
