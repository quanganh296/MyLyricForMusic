import sys
import os
import json
import ctypes

# Add project root directory to path
# When packaged via PyInstaller (--onefile), persist config.json & cache/ next to LyricNow.exe (not %TEMP%!)
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = BASE_DIR

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Set AppUserModelID on Windows so taskbar displays explicit icon and window identity
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LyricNow.OverlayApp.1")
except Exception as e:
    print(f"[WinAPI Warning] Could not set AppUserModelID: {e}")

from modules.qt_compat import QApplication, QThread, QIcon
from modules.cache_manager import LyricsCache
from modules.lyrics_provider import LyricsProvider
from modules.media_listener import MediaListenerWorker
from modules.bt_battery_monitor import BluetoothBatteryWorker
from modules.overlay_window import LyricOverlayWindow
from modules.settings_dialog import SettingsDialog
from modules.search_dialog import SearchDialog

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
ICO_FILE = os.path.join(RESOURCE_DIR, "assets", "app_icon.ico")
ICON_FILE = os.path.join(RESOURCE_DIR, "assets", "app_icon.png")

DEFAULT_SETTINGS = {
    "font_family": "Segoe UI",
    "font_size": 22,
    "theme_name": "Cyan Blue (Mặc định)",
    "color_highlight": "#38bdf8",
    "color_sub": "#94a3b8",
    "bg_opacity": 0.75,
    "display_mode": 1,   # 1: Video (Right) + Lyrics (Left) + Blurred BG, 2: Lyric-Only Centered
    "enable_translation": True,
    "enable_romanization": True,
    "translate_lang": "vi",
    "line_mode": 1,      # 0: 1 line, 1: 2 lines, 2: 3 lines (Mode 2)
    "align_mode": 0,     # 0: Center, 1: Left, 2: Right (Mode 2)
    "sync_offset": 0.0,
    "win_x": 350,
    "win_y": 120,
    "win_w": 680,
    "win_h": 220,
    "mode1_w": 940,
    "mode1_h": 430
}

def load_settings() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                merged = DEFAULT_SETTINGS.copy()
                merged.update(saved)
                return merged
        except Exception as e:
            print(f"[Config Error] Failed to load config.json: {e}")
    return DEFAULT_SETTINGS.copy()

def save_settings(settings: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        print("[Config] Settings saved to config.json")
    except Exception as e:
        print(f"[Config Error] Failed to save config.json: {e}")

class LyricOverlayApp:
    def __init__(self):
        self.app = QApplication(sys.argv)

        # Standard window behavior: Quit when main window is closed (No background running)
        self.app.setQuitOnLastWindowClosed(True)

        if os.path.exists(ICO_FILE):
            self.app.setWindowIcon(QIcon(ICO_FILE))
        elif os.path.exists(ICON_FILE):
            self.app.setWindowIcon(QIcon(ICON_FILE))

        self.settings = load_settings()
        self.cache_manager = LyricsCache(CACHE_DIR)
        self.lyrics_provider = LyricsProvider(self.cache_manager)

        # 1. Initialize Media Listener Worker in QThread
        self.media_thread = QThread()
        self.media_worker = MediaListenerWorker(poll_interval=0.3)
        self.media_worker.moveToThread(self.media_thread)

        self.media_thread.started.connect(self.media_worker.run)
        self.media_worker.session_closed.connect(lambda: self.overlay.on_media_updated(None))

        # 2. Create Overlay Window
        self.overlay = LyricOverlayWindow(self.settings, self.media_worker, self.lyrics_provider)
        self.media_worker.media_updated.connect(self.overlay.on_media_updated)

        # 2b. Initialize Bluetooth Headphone Battery Monitor in QThread
        self.bt_thread = QThread()
        self.bt_worker = BluetoothBatteryWorker(poll_interval=4.0)
        self.bt_worker.moveToThread(self.bt_thread)
        self.bt_thread.started.connect(self.bt_worker.run)
        self.bt_worker.battery_updated.connect(self.overlay.on_bt_battery_updated)

        # 3. Connect Overlay signals
        self.overlay.request_settings.connect(self.open_settings)
        self.overlay.request_search.connect(self.open_search)
        self.overlay.request_exit.connect(self.exit_app)
        self.overlay.settings_autosave.connect(save_settings)

        # Show Overlay
        self.overlay.show()
        self.media_thread.start()
        self.bt_thread.start()

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self.overlay)
        dlg.settings_changed.connect(self.on_settings_updated)
        dlg.exec()

    def on_settings_updated(self, new_settings: dict):
        self.settings = new_settings
        save_settings(self.settings)
        self.overlay.apply_settings(self.settings)

    def open_search(self):
        current_query = ""
        if self.overlay.current_media_state and self.overlay.current_media_state.title:
            title = (self.overlay.current_media_state.title or "").strip()
            artist = (self.overlay.current_media_state.artist or "").strip()
            if "-" in title or "|" in title:
                current_query = title
            else:
                clean_a = self.lyrics_provider._normalize_artist(artist)
                current_query = f"{title} {clean_a}".strip() if clean_a else title
        
        dlg = SearchDialog(self.lyrics_provider, initial_query=current_query, parent=self.overlay)
        dlg.lyric_selected.connect(self.overlay.set_custom_lyrics)
        dlg.exec()

    def exit_app(self):
        print("[App] Exiting LyricOverLay...")
        # Update settings with current window coordinates (ignore fullscreen geometry)
        if not self.overlay.is_fullscreen:
            self.settings["win_x"] = self.overlay.x()
            self.settings["win_y"] = self.overlay.y()
            if self.overlay.display_mode == 1:
                self.settings["mode1_w"] = self.overlay.width()
                self.settings["mode1_h"] = self.overlay.height()
            elif not self.overlay.is_compact:
                self.settings["win_w"] = self.overlay.width()
                self.settings["win_h"] = self.overlay.height()
        save_settings(self.settings)

        self.media_worker.stop()
        self.media_thread.quit()
        self.media_thread.wait(2000)

        self.bt_worker.stop()
        self.bt_thread.quit()
        self.bt_thread.wait(2000)

        self.app.quit()

    def run(self):
        return self.app.exec()

if __name__ == "__main__":
    app = LyricOverlayApp()
    sys.exit(app.run())

