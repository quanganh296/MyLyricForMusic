import asyncio
import ctypes
import time
import uuid
from ctypes import wintypes
from modules.qt_compat import QObject, Signal, QThread

try:
    from winsdk.windows.devices.bluetooth import BluetoothLEDevice, BluetoothConnectionStatus
    from winsdk.windows.devices.bluetooth.advertisement import (
        BluetoothLEAdvertisementWatcher,
        BluetoothLEScanningMode,
    )
    from winsdk.windows.devices.bluetooth.genericattributeprofile import GattCommunicationStatus
    from winsdk.windows.devices.enumeration import DeviceInformation
    from winsdk.windows.storage.streams import DataReader
    WINRT_BT_AVAILABLE = True
except Exception as e:
    print(f"[BTMonitor Warning] WinRT Bluetooth unavailable: {e}")
    WINRT_BT_AVAILABLE = False


class HeadphoneBatteryState:
    """Represents connected Bluetooth headphone battery and Left/Right earbud status."""

    def __init__(
        self,
        connected: bool = False,
        device_name: str = "",
        has_lr_split: bool = False,
        left_connected: bool = False,
        right_connected: bool = False,
        left_battery: int = None,
        right_battery: int = None,
        case_battery: int = None,
        left_charging: bool = False,
        right_charging: bool = False,
        overall_battery: int = None,
        source: str = "",
    ):
        self.connected = connected
        self.device_name = device_name
        self.has_lr_split = has_lr_split
        self.left_connected = left_connected
        self.right_connected = right_connected
        self.left_battery = left_battery
        self.right_battery = right_battery
        self.case_battery = case_battery
        self.left_charging = left_charging
        self.right_charging = right_charging
        self.overall_battery = overall_battery
        self.source = source

    def signature(self):
        return (
            self.connected,
            self.device_name,
            self.has_lr_split,
            self.left_connected,
            self.right_connected,
            self.left_battery,
            self.right_battery,
            self.case_battery,
            self.left_charging,
            self.right_charging,
            self.overall_battery,
        )

    def effective_min_battery(self):
        vals = []
        if self.has_lr_split:
            if self.left_connected and self.left_battery is not None:
                vals.append(self.left_battery)
            if self.right_connected and self.right_battery is not None:
                vals.append(self.right_battery)
        if not vals and self.overall_battery is not None:
            vals.append(self.overall_battery)
        return min(vals) if vals else None


# ---------------------------------------------------------------------------
# Fast Native Win32 SetupAPI PnP Bluetooth Audio Reader (<60ms, zero shell)
# ---------------------------------------------------------------------------
_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_DIGCF_PRESENT = 0x00000002
_DIGCF_ALLCLASSES = 0x00000004


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.ULONG)]


class _SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", _GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(wintypes.ULONG)),
    ]


def _make_guid(s: str) -> _GUID:
    u = uuid.UUID(s)
    g = _GUID()
    ctypes.memmove(ctypes.byref(g), u.bytes_le, 16)
    return g


_DEVPKEY_NAME = _DEVPROPKEY(_make_guid("B725F130-47EF-101A-A5F1-02608C9EEBAC"), 10)
_DEVPKEY_FRIENDLY_NAME = _DEVPROPKEY(_make_guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)
_DEVPKEY_CONTAINER_ID = _DEVPROPKEY(_make_guid("8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C"), 2)
_DEVPKEY_INSTANCE_ID = _DEVPROPKEY(_make_guid("78C34FC8-104A-4ACA-9EA4-524D52996E57"), 256)
_DEVPKEY_BT_CONNECTED = _DEVPROPKEY(_make_guid("83DA6326-97A6-4088-9453-A1923F573B29"), 15)
_DEVPKEY_BT_BATTERY = _DEVPROPKEY(_make_guid("104EA319-6EE2-4701-BD47-8DDBF425BBE5"), 2)
_DEVPKEY_BT_ADDRESS = _DEVPROPKEY(_make_guid("2BD67D8B-8BEB-48D5-87E0-6CDA3428040A"), 1)

_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(_GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiEnumDeviceInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(_SP_DEVINFO_DATA)]
_setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
_setupapi.SetupDiGetDevicePropertyW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_SP_DEVINFO_DATA), ctypes.POINTER(_DEVPROPKEY),
    ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
]
_setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL


def _get_dev_prop(hdev, devinfo, key):
    prop_type = wintypes.ULONG(0)
    req_size = wintypes.DWORD(0)
    _setupapi.SetupDiGetDevicePropertyW(
        hdev, ctypes.byref(devinfo), ctypes.byref(key),
        ctypes.byref(prop_type), None, 0, ctypes.byref(req_size), 0
    )
    if req_size.value == 0:
        return None
    buf = ctypes.create_string_buffer(req_size.value)
    ok = _setupapi.SetupDiGetDevicePropertyW(
        hdev, ctypes.byref(devinfo), ctypes.byref(key),
        ctypes.byref(prop_type), buf, req_size.value, ctypes.byref(req_size), 0
    )
    if not ok:
        return None
    pt = prop_type.value
    if pt == 18:  # STRING
        return buf.raw.decode("utf-16le", errors="ignore").rstrip("\x00")
    if pt == 3:   # BYTE
        return buf.raw[0]
    if pt == 17:  # BOOLEAN
        return buf.raw[0] != 0
    if pt == 13:  # GUID
        return str(uuid.UUID(bytes_le=buf.raw[:16]))
    return None


def _clean_bt_name(names: list) -> str:
    """Pick the cleanest human-readable Bluetooth headset name from container nodes."""
    best = ""
    for n in names:
        n = n.strip()
        if not n:
            continue
        lower = n.lower()
        if any(skip in lower for skip in ("avrcp", "hands-free", "serial over bluetooth", "service", "generic attribute", "device information")):
            continue
        if len(n) > len(best):
            best = n
    if best:
        return best
    for n in names:
        cleaned = n.replace("Hands-Free AG", "").replace("Hands-Free", "").replace("Avrcp Transport", "").strip()
        if cleaned:
            return cleaned
    return "Bluetooth Audio"


def _is_audio_container(info: dict) -> bool:
    """Ensure we only detect Bluetooth audio headphones/earbuds (never keyboards, mice, controllers)."""
    audio_uuids = ("0000110b", "0000111e", "0000110e", "0000110c", "00001108", "0000184e", "00001853")
    for inst in info.get("ids", []):
        il = inst.lower()
        if any(u in il for u in audio_uuids):
            return True
    for n in info.get("names", []):
        nl = n.lower()
        if any(kw in nl for kw in ("hands-free", "avrcp", "headphone", "headset", "airpods", "buds", "earbud", "earphone", "tws", "pods")):
            return True
    return False


def _is_apple_audio(info: dict) -> bool:
    for inst in info.get("ids", []):
        if "vid&0001004c" in inst.lower() or "vid_004c" in inst.lower():
            return True
    for n in info.get("names", []):
        nl = n.lower()
        if "airpods" in nl or "beats" in nl:
            return True
    return False


def scan_pnp_connected_headsets() -> list:
    """Returns list of connected Bluetooth audio headset dicts from Windows PnP in ~50ms."""
    containers = {}
    invalid_handle = wintypes.HANDLE(-1).value
    for enum_name in ("BTHENUM", "BTHLE", "BTHLEDEVICE"):
        hdev = _setupapi.SetupDiGetClassDevsW(None, enum_name, None, _DIGCF_PRESENT | _DIGCF_ALLCLASSES)
        if hdev == invalid_handle:
            continue
        try:
            idx = 0
            devinfo = _SP_DEVINFO_DATA()
            devinfo.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            while _setupapi.SetupDiEnumDeviceInfo(hdev, idx, ctypes.byref(devinfo)):
                idx += 1
                cid = _get_dev_prop(hdev, devinfo, _DEVPKEY_CONTAINER_ID)
                if not cid or cid == "00000000-0000-0000-ffff-ffffffffffff":
                    continue
                name = _get_dev_prop(hdev, devinfo, _DEVPKEY_FRIENDLY_NAME) or _get_dev_prop(hdev, devinfo, _DEVPKEY_NAME) or ""
                inst_id = _get_dev_prop(hdev, devinfo, _DEVPKEY_INSTANCE_ID) or ""
                conn = _get_dev_prop(hdev, devinfo, _DEVPKEY_BT_CONNECTED)
                batt = _get_dev_prop(hdev, devinfo, _DEVPKEY_BT_BATTERY)
                addr = _get_dev_prop(hdev, devinfo, _DEVPKEY_BT_ADDRESS)

                entry = containers.setdefault(cid, {
                    "cid": cid,
                    "names": [],
                    "connected": False,
                    "batteries": [],
                    "addr": None,
                    "ids": [],
                })
                if name:
                    entry["names"].append(name)
                if conn:
                    entry["connected"] = True
                if batt is not None and 0 <= batt <= 100:
                    entry["batteries"].append((name, int(batt), inst_id))
                if addr:
                    entry["addr"] = addr
                if inst_id:
                    entry["ids"].append(inst_id)
        finally:
            _setupapi.SetupDiDestroyDeviceInfoList(hdev)

    results = []
    for cid, info in containers.items():
        if not info["connected"]:
            continue
        if not _is_audio_container(info):
            continue
        info["display_name"] = _clean_bt_name(info["names"])
        info["is_apple"] = _is_apple_audio(info)
        results.append(info)
    return results


# ---------------------------------------------------------------------------
# BLE Decoders for Per-Earbud (Left / Right / Case) Battery
# ---------------------------------------------------------------------------
def decode_apple_airpods_adv(data: bytes) -> dict:
    """
    Decode Apple Proximity Pairing (Company ID 0x004C, Type 0x07, Len 0x19, exact 27-byte payload).
    Follows the verified CAPod (DualApplePods) & AirPodsDesktop (AppleCP) bitfield specification,
    including bit-6 in-case broadcaster XOR and optical in-ear detection so wearing ONLY the Right
    AirPod always reports Right (never Left even if Left is sitting charged in the case!).
    """
    if not data or len(data) != 27:
        return None
    if data[0] != 0x07 or data[1] != 0x19:
        return None

    status = data[5]
    # Bit 5 (0x20): 1 = Left pod is primary broadcaster, 0 = Right pod is primary broadcaster (values flipped)
    flip = (status & 0x20) == 0
    is_this_in_case = bool(status & 0x40)
    both_in_case = bool(status & 0x04)

    high6 = (data[6] >> 4) & 0x0F
    low6 = data[6] & 0x0F
    left_raw = high6 if flip else low6
    right_raw = low6 if flip else high6

    charge_flags = (data[7] >> 4) & 0x0F
    case_raw = data[7] & 0x0F

    left_batt = min(100, left_raw * 10) if 0 <= left_raw <= 10 else None
    right_batt = min(100, right_raw * 10) if 0 <= right_raw <= 10 else None
    case_batt = min(100, case_raw * 10) if 0 <= case_raw <= 10 else None

    if left_batt is None and right_batt is None:
        return None

    left_charging = bool(charge_flags & (0x02 if flip else 0x01))
    right_charging = bool(charge_flags & (0x01 if flip else 0x02))

    # In-ear optical sensor bits (bit 1 = broadcasting pod, bit 3 = other pod).
    # Per CAPod DualApplePods: when the broadcasting pod itself is inside the case (bit 6),
    # the in-ear mapping flips once more (flip ^ is_this_in_case).
    in_ear_flip = flip ^ is_this_in_case
    left_in_ear = (not left_charging) and bool(status & (0x08 if in_ear_flip else 0x02))
    right_in_ear = (not right_charging) and bool(status & (0x02 if in_ear_flip else 0x08))

    # Determine actively worn/connected earbud(s):
    # 1. If optical in-ear sensor confirms one or both pods are physically in ear, trust it strictly!
    # 2. Otherwise fall back to presence & charging state (for out-of-ear desk listening or sensor disabled).
    if left_in_ear or right_in_ear:
        left_active = (left_batt is not None) and left_in_ear
        right_active = (right_batt is not None) and right_in_ear
    else:
        left_active = (left_batt is not None) and not (left_charging and right_batt is not None and not right_charging)
        right_active = (right_batt is not None) and not (right_charging and left_batt is not None and not left_charging)

    return {
        "left_connected": left_active,
        "right_connected": right_active,
        "left_battery": left_batt,
        "right_battery": right_batt,
        "case_battery": case_batt,
        "left_charging": left_charging,
        "right_charging": right_charging,
        "left_in_ear": left_in_ear,
        "right_in_ear": right_in_ear,
        "is_this_in_case": is_this_in_case,
        "both_in_case": both_in_case,
        "source": "Apple BLE",
    }


def decode_fast_pair_service_data(data: bytes) -> dict:
    """
    Strictly decode Google Fast Pair (Service UUID 0xFE2C) BLE Service Data for Left / Right / Case battery.
    Follows the official TLV framing (i += 1 + field_len) so random Account Key Bloom filter bytes
    are NEVER misread as fake 50%/60%/70% earbud battery percentages!
    """
    if not data or len(data) < 7:
        return None
    if data[0] != 0x2C or data[1] != 0xFE:
        return None

    # Byte 2 is Flags byte (version bits 7..4 MUST be 0 in Fast Pair Account Key Data)
    flags = data[2]
    if (flags & 0xF0) != 0x00:
        return None

    # Walk strict length-prefixed TLV fields starting at index 3:
    # Each TLV header byte: high nibble = field_len, low nibble = field_type.
    # Battery info is strictly field_type 0x03 (show UI) or 0x04 (hide UI) with field_len == 3.
    i = 3
    n = len(data)
    while i < n:
        header = data[i]
        field_len = (header >> 4) & 0x0F
        field_type = header & 0x0F
        next_i = i + 1 + field_len
        if next_i > n:
            return None  # Malformed/truncated TLV frame -> reject entire packet

        if field_type in (0x03, 0x04) and field_len == 3:
            lb = data[i + 1]
            rb = data[i + 2]
            cb = data[i + 3]

            l_chg = bool(lb & 0x80)
            r_chg = bool(rb & 0x80)
            l_pct = lb & 0x7F
            r_pct = rb & 0x7F
            c_pct = cb & 0x7F

            # Per Fast Pair spec, 0x7F (127) means unknown; 101..126 are invalid -> reject noise
            for v in (l_pct, r_pct, c_pct):
                if 100 < v < 0x7F:
                    return None

            left_batt = l_pct if l_pct <= 100 else None
            right_batt = r_pct if r_pct <= 100 else None
            case_batt = c_pct if c_pct <= 100 else None

            if left_batt is not None or right_batt is not None:
                left_active = (left_batt is not None) and not (l_chg and right_batt is not None and not r_chg)
                right_active = (right_batt is not None) and not (r_chg and left_batt is not None and not l_chg)
                return {
                    "left_connected": left_active,
                    "right_connected": right_active,
                    "left_battery": left_batt,
                    "right_battery": right_batt,
                    "case_battery": case_batt,
                    "left_charging": l_chg,
                    "right_charging": r_chg,
                    "source": "Fast Pair BLE",
                }
        i = next_i
    return None


def _bt_addrs_match(pnp_addr: str, ble_addr: str) -> bool:
    """Checks if a BLE advertisement address matches (or is adjacent to) the connected headset's Classic BT MAC."""
    if not pnp_addr or not ble_addr:
        return False
    a = pnp_addr.replace(":", "").replace("-", "").upper()
    b = ble_addr.replace(":", "").replace("-", "").upper()
    if len(a) != 12 or len(b) != 12:
        return False
    if a == b:
        return True
    try:
        # Dual-mode BT Classic / BLE headsets often differ by 1-2 in the last octet (same OUI prefix)
        return a[:6] == b[:6] and abs(int(a, 16) - int(b, 16)) <= 4
    except Exception:
        return False


class _BatteryValueFilter:
    """
    Rejects transient HFP/BLE battery spikes (e.g. 90% -> 60% -> 50% -> 90%) while still
    reflecting real gradual discharge (<=10% steps) immediately and real step-changes
    once confirmed across 3 consecutive polls (~12s).
    """

    def __init__(self, confirm_count: int = 3):
        self.confirm_count = max(2, int(confirm_count))
        self._stable = None
        self._pending_val = None
        self._pending_streak = 0

    def reset(self):
        self._stable = None
        self._pending_val = None
        self._pending_streak = 0

    def update(self, raw_val):
        if raw_val is None:
            return self._stable
        val = max(0, min(100, int(raw_val)))
        if self._stable is None:
            self._stable = val
            self._pending_val = None
            self._pending_streak = 0
            return self._stable

        # Normal discharge/charge step (HFP uses 10% increments) -> accept immediately!
        if abs(val - self._stable) <= 10:
            self._stable = val
            self._pending_val = None
            self._pending_streak = 0
            return self._stable

        # Sudden large jump (>10%, e.g. 90 -> 60 or 90 -> 50): confirm across consecutive consistent polls!
        if self._pending_val is not None and abs(val - self._pending_val) <= 10:
            self._pending_streak += 1
            self._pending_val = val
        else:
            self._pending_val = val
            self._pending_streak = 1

        if self._pending_streak >= self.confirm_count:
            self._stable = val
            self._pending_val = None
            self._pending_streak = 0
        return self._stable


class BluetoothBatteryWorker(QObject):
    """
    Background worker that monitors connected Bluetooth headphones and reports:
    - Overall battery percentage (via fast Win32 PnP HFP)
    - Per-earbud Left / Right battery & Left / Right connection status (via Apple BLE, Fast Pair BLE, or Multi-GATT / PnP)
    """
    battery_updated = Signal(object)  # Emits HeadphoneBatteryState

    def __init__(self, poll_interval: float = 4.0):
        super().__init__()
        self.poll_interval = poll_interval
        self._running = True
        self._last_sig = None

        # Cached recent BLE per-earbud readings (timestamped, expire after 25s)
        self._apple_ble_cache = None     # (timestamp, rssi, ble_addr, local_name, decoded_dict)
        self._fastpair_ble_cache = None  # (timestamp, rssi, ble_addr, local_name, decoded_dict)

        # Spike-rejection stability filters per device (eliminates 90 -> 60 -> 50 -> 90 HFP/BLE bounce)
        self._filter_device_key = None
        self._flt_overall = _BatteryValueFilter(confirm_count=3)
        self._flt_left = _BatteryValueFilter(confirm_count=3)
        self._flt_right = _BatteryValueFilter(confirm_count=3)
        self._flt_case = _BatteryValueFilter(confirm_count=3)

    def _reset_filters(self, dev_key=None):
        self._filter_device_key = dev_key
        self._flt_overall.reset()
        self._flt_left.reset()
        self._flt_right.reset()
        self._flt_case.reset()

    def _stabilize_state(self, state: HeadphoneBatteryState) -> HeadphoneBatteryState:
        if not state or not state.connected:
            self._reset_filters(None)
            return state
        dev_key = (state.device_name or "").strip().lower()
        if dev_key != self._filter_device_key:
            self._reset_filters(dev_key)

        if state.overall_battery is not None:
            state.overall_battery = self._flt_overall.update(state.overall_battery)
        if state.has_lr_split:
            if state.left_battery is not None:
                state.left_battery = self._flt_left.update(state.left_battery)
            if state.right_battery is not None:
                state.right_battery = self._flt_right.update(state.right_battery)
            if state.case_battery is not None:
                state.case_battery = self._flt_case.update(state.case_battery)
        return state

    def stop(self):
        self._running = False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._monitor_loop())
        finally:
            loop.close()

    def _start_ble_watcher(self):
        if not WINRT_BT_AVAILABLE:
            return None, None
        try:
            watcher = BluetoothLEAdvertisementWatcher()
            watcher.scanning_mode = BluetoothLEScanningMode.PASSIVE

            def on_adv(sender, args):
                try:
                    rssi = args.raw_signal_strength_in_d_bm
                    if rssi < -64:
                        return
                    now = time.time()
                    ble_addr = f"{args.bluetooth_address:012X}"
                    local_name = (args.advertisement.local_name or "").strip()

                    # 1. Apple AirPods / Beats (Company ID 0x004C, exact 27-byte Proximity Pairing packet)
                    for m in args.advertisement.manufacturer_data:
                        if m.company_id == 0x004C and m.data.length == 27:
                            rdr = DataReader.from_buffer(m.data)
                            buf = bytearray(m.data.length)
                            rdr.read_bytes(buf)
                            decoded = decode_apple_airpods_adv(bytes(buf))
                            if decoded:
                                prev = self._apple_ble_cache
                                new_prio = (
                                    1 if (decoded.get("left_in_ear") or decoded.get("right_in_ear")) else 0,
                                    0 if decoded.get("is_this_in_case") else 1,
                                    0 if decoded.get("both_in_case") else 1,
                                )
                                if not prev or (now - prev[0] > 8.0):
                                    self._apple_ble_cache = (now, rssi, ble_addr, local_name, decoded)
                                else:
                                    prev_dec = prev[4]
                                    prev_prio = (
                                        1 if (prev_dec.get("left_in_ear") or prev_dec.get("right_in_ear")) else 0,
                                        0 if prev_dec.get("is_this_in_case") else 1,
                                        0 if prev_dec.get("both_in_case") else 1,
                                    )
                                    # Prefer worn/out-of-case AirPod over an in-case pod's broadcast!
                                    if new_prio > prev_prio or (new_prio == prev_prio and rssi >= prev[1] - 4):
                                        self._apple_ble_cache = (now, rssi, ble_addr, local_name, decoded)

                    # 2. Google Fast Pair (Service Data 0x16 -> 2C FE)
                    for ds in args.advertisement.data_sections:
                        if ds.data_type == 0x16 and ds.data.length >= 7:
                            rdr = DataReader.from_buffer(ds.data)
                            buf = bytearray(ds.data.length)
                            rdr.read_bytes(buf)
                            decoded = decode_fast_pair_service_data(bytes(buf))
                            if decoded:
                                prev = self._fastpair_ble_cache
                                if not prev or (now - prev[0] > 8.0) or rssi >= prev[1] - 4:
                                    self._fastpair_ble_cache = (now, rssi, ble_addr, local_name, decoded)
                except Exception:
                    pass

            token = watcher.add_received(on_adv)
            watcher.start()
            return watcher, token
        except Exception as e:
            print(f"[BTMonitor BLE Watcher Warning] {e}")
            return None, None

    async def _read_ble_gatt_lr(self, device_name: str) -> dict:
        """For connected LE Audio / BLE TWS headsets exposing multiple 0x2A19 Battery characteristics."""
        if not WINRT_BT_AVAILABLE:
            return None
        try:
            sel = BluetoothLEDevice.get_device_selector_from_connection_status(BluetoothConnectionStatus.CONNECTED)
            le_devs = await DeviceInformation.find_all_async(sel, [])
            if not le_devs:
                return None

            batt_svc_uuid = uuid.UUID("0000180f-0000-1000-8000-00805f9b34fb")
            batt_char_uuid = uuid.UUID("00002a19-0000-1000-8000-00805f9b34fb")
            name_low = device_name.lower()

            left_b = right_b = case_b = None
            for d in le_devs:
                dn = (d.name or "").lower()
                if not dn or (name_low not in dn and dn not in name_low):
                    continue
                ble = await BluetoothLEDevice.from_id_async(d.id)
                svcs = await ble.get_gatt_services_for_uuid_async(batt_svc_uuid)
                for svc in svcs.services:
                    chars = await svc.get_characteristics_for_uuid_async(batt_char_uuid)
                    for ch in chars.characteristics:
                        vr = await ch.read_value_async()
                        if vr.status != GattCommunicationStatus.SUCCESS:
                            continue
                        pct = DataReader.from_buffer(vr.value).read_byte()
                        if pct > 100:
                            continue
                        label = dn
                        try:
                            descs = await ch.get_descriptors_async()
                            for ds in descs.descriptors:
                                if str(ds.uuid).startswith("00002901"):
                                    dv = await ds.read_value_async()
                                    if dv.status == GattCommunicationStatus.SUCCESS:
                                        dr = DataReader.from_buffer(dv.value)
                                        b = bytearray(dv.value.length)
                                        dr.read_bytes(b)
                                        label += " " + b.decode("utf-8", errors="ignore").lower()
                        except Exception:
                            pass

                        if "left" in label or " l " in f" {label} ":
                            left_b = int(pct)
                        elif "right" in label or " r " in f" {label} ":
                            right_b = int(pct)
                        elif "case" in label or "box" in label:
                            case_b = int(pct)

            if left_b is not None or right_b is not None:
                return {
                    "left_connected": left_b is not None,
                    "right_connected": right_b is not None,
                    "left_battery": left_b,
                    "right_battery": right_b,
                    "case_battery": case_b,
                    "left_charging": False,
                    "right_charging": False,
                    "source": "BLE GATT",
                }
        except Exception:
            pass
        return None

    async def _poll_once(self) -> HeadphoneBatteryState:
        headsets = scan_pnp_connected_headsets()
        if not headsets:
            return self._stabilize_state(HeadphoneBatteryState(connected=False))

        # Prefer headset that reports a battery value
        headsets.sort(key=lambda h: (len(h["batteries"]) > 0, h["is_apple"]), reverse=True)
        primary = headsets[0]
        dev_name = primary["display_name"]
        now = time.time()

        # Check if multiple PnP nodes explicitly name Left / Right earbuds (e.g. LE Audio dual nodes)
        # Sort deterministically by instance ID so multiple nodes never flicker in random order!
        pnp_left = pnp_right = pnp_case = overall = None
        for b_name, b_val, _ in sorted(primary["batteries"], key=lambda x: (x[2] or "", x[0] or "")):
            nl = b_name.lower()
            if "left" in nl or nl.endswith(" l"):
                pnp_left = b_val
            elif "right" in nl or nl.endswith(" r"):
                pnp_right = b_val
            elif "case" in nl:
                pnp_case = b_val
            elif overall is None:
                overall = b_val

        # Also check if two separate connected containers exist for Left & Right earbuds of same model
        if pnp_left is None and pnp_right is None and len(headsets) >= 2:
            for h in headsets:
                hl = h["display_name"].lower()
                if h["batteries"]:
                    val = h["batteries"][0][1]
                    if "left" in hl or hl.endswith(" l") or hl.endswith("-l"):
                        pnp_left = val
                    elif "right" in hl or hl.endswith(" r") or hl.endswith("-r"):
                        pnp_right = val

        if pnp_left is not None or pnp_right is not None:
            return self._stabilize_state(HeadphoneBatteryState(
                connected=True,
                device_name=dev_name,
                has_lr_split=True,
                left_connected=pnp_left is not None,
                right_connected=pnp_right is not None,
                left_battery=pnp_left,
                right_battery=pnp_right,
                case_battery=pnp_case,
                overall_battery=overall,
                source="Windows PnP L/R",
            ))

        # Layer 2: Apple AirPods / Beats BLE Proximity Pairing (exact Left / Right / Case %)
        if primary["is_apple"] and self._apple_ble_cache:
            ts, rssi, _, _, dec = self._apple_ble_cache
            if (now - ts <= 30.0) and rssi >= -62:
                return self._stabilize_state(HeadphoneBatteryState(
                    connected=True,
                    device_name=dev_name,
                    has_lr_split=True,
                    left_connected=dec["left_connected"],
                    right_connected=dec["right_connected"],
                    left_battery=dec["left_battery"],
                    right_battery=dec["right_battery"],
                    case_battery=dec["case_battery"],
                    left_charging=dec["left_charging"],
                    right_charging=dec["right_charging"],
                    overall_battery=overall,
                    source=dec["source"],
                ))

        # Layer 3: Google Fast Pair BLE — ONLY accept when BLE device matches our connected headset
        # (prevents random nearby phones/earbuds in the room from hijacking battery %!)
        if not primary["is_apple"] and self._fastpair_ble_cache:
            ts, rssi, ble_addr, ble_name, dec = self._fastpair_ble_cache
            name_match = bool(
                ble_name and dev_name
                and (ble_name.lower() in dev_name.lower() or dev_name.lower() in ble_name.lower())
            )
            addr_match = _bt_addrs_match(primary.get("addr") or "", ble_addr)
            if (now - ts <= 30.0) and rssi >= -60 and (addr_match or name_match):
                return self._stabilize_state(HeadphoneBatteryState(
                    connected=True,
                    device_name=dev_name,
                    has_lr_split=True,
                    left_connected=dec["left_connected"],
                    right_connected=dec["right_connected"],
                    left_battery=dec["left_battery"],
                    right_battery=dec["right_battery"],
                    case_battery=dec["case_battery"],
                    left_charging=dec["left_charging"],
                    right_charging=dec["right_charging"],
                    overall_battery=overall,
                    source=dec["source"],
                ))

        # Layer 4: BLE GATT Multi-Battery service (for connected LE Audio / BLE TWS)
        gatt_lr = await self._read_ble_gatt_lr(dev_name)
        if gatt_lr:
            return self._stabilize_state(HeadphoneBatteryState(
                connected=True,
                device_name=dev_name,
                has_lr_split=True,
                left_connected=gatt_lr["left_connected"],
                right_connected=gatt_lr["right_connected"],
                left_battery=gatt_lr["left_battery"],
                right_battery=gatt_lr["right_battery"],
                case_battery=gatt_lr["case_battery"],
                overall_battery=overall,
                source=gatt_lr["source"],
            ))

        # Layer 5: Universal Windows Classic HFP Battery fallback (spike-filtered!)
        return self._stabilize_state(HeadphoneBatteryState(
            connected=True,
            device_name=dev_name,
            has_lr_split=False,
            left_connected=True,
            right_connected=True,
            overall_battery=overall,
            source="Windows HFP",
        ))

    async def _monitor_loop(self):
        watcher, token = self._start_ble_watcher()
        try:
            while self._running:
                try:
                    state = await self._poll_once()
                    sig = state.signature()
                    if sig != self._last_sig:
                        self._last_sig = sig
                        self.battery_updated.emit(state)
                except Exception as e:
                    print(f"[BTMonitor Poll Error] {e}")
                # Sleep in short increments so stop() exits promptly
                steps = max(1, int(self.poll_interval / 0.25))
                for _ in range(steps):
                    if not self._running:
                        break
                    await asyncio.sleep(0.25)
        finally:
            if watcher:
                try:
                    watcher.stop()
                    if token is not None:
                        watcher.remove_received(token)
                except Exception:
                    pass

