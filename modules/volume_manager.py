import ctypes

try:
    from pycaw.pycaw import AudioUtilities
    PYCAW_AVAILABLE = True
except Exception as e:
    print(f"[VolumeManager Warning] pycaw import failed: {e}")
    PYCAW_AVAILABLE = False


class VolumeManager:
    """Handles Windows volume control via pycaw API with ctypes keybd_event fallback."""

    def __init__(self):
        self.spk = None
        if PYCAW_AVAILABLE:
            try:
                self.spk = AudioUtilities.GetSpeakers()
            except Exception as e:
                print(f"[VolumeManager Error] Failed to get speakers: {e}")
                self.spk = None

    def get_volume(self) -> int:
        """Returns current volume percentage (0 - 100)."""
        if self.spk:
            try:
                vol_p = self.spk.volume_percent
                return int(round(vol_p))
            except Exception as e:
                pass
        return 75

    def set_volume(self, percent: int):
        """Sets master volume percentage (0 - 100)."""
        clamped = max(0, min(100, percent))
        if self.spk:
            try:
                val_scalar = clamped / 100.0
                self.spk.EndpointVolume.SetMasterVolumeLevelScalar(val_scalar, None)
                return
            except Exception as e:
                print(f"[VolumeManager Error] Set master volume failed: {e}")

        # Fallback if pycaw fails: calculate delta and send volume keys
        current = self.get_volume()
        diff = clamped - current
        steps = abs(diff) // 2
        key = 0xAF if diff > 0 else 0xAE # VK_VOLUME_UP or VK_VOLUME_DOWN
        for _ in range(steps):
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
            ctypes.windll.user32.keybd_event(key, 0, 2, 0)

    def is_muted(self) -> bool:
        """Returns True if audio is muted."""
        if self.spk:
            try:
                return bool(self.spk.EndpointVolume.GetMuted())
            except Exception:
                pass
        return False

    def toggle_mute(self) -> bool:
        """Toggles audio mute state. Returns new muted boolean state."""
        if self.spk:
            try:
                current_mute = self.spk.EndpointVolume.GetMuted()
                new_mute = 1 if not current_mute else 0
                self.spk.EndpointVolume.SetMute(new_mute, None)
                return bool(new_mute)
            except Exception as e:
                print(f"[VolumeManager Error] Toggle mute failed: {e}")

        # Fallback send VK_VOLUME_MUTE
        ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
        return not self.is_muted()
