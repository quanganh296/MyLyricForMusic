import ctypes
import time

try:
    from pycaw.pycaw import AudioUtilities
    PYCAW_AVAILABLE = True
except Exception as e:
    print(f"[VolumeManager Warning] pycaw import failed: {e}")
    PYCAW_AVAILABLE = False


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
