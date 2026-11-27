import os
import re
import sys
import subprocess
import webbrowser
import requests

from modules.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QProgressBar, QFrame, Qt, QThread, Signal
)
from modules.icon_factory import IconFactory
from modules.i18n import tr

GITHUB_REPO = "quanganh296/MyLyricForMusic"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_WEB_LATEST = f"https://github.com/{GITHUB_REPO}/releases/latest"

_VER_NUM_RE = re.compile(r"\d+")
_TAG_URL_RE = re.compile(r"/releases/tag/(v?[\d\.]+)", re.IGNORECASE)


def parse_version(ver_str: str) -> tuple:
    """Parses version strings like 'v1.1.2' or '1.0.10' into integer tuples for exact comparison."""
    nums = [int(x) for x in _VER_NUM_RE.findall(str(ver_str or ""))]
    return tuple(nums) if nums else (0,)


def is_newer_version(latest: str, current: str) -> bool:
    """Returns True strictly when latest > current semantically."""
    a = list(parse_version(latest))
    b = list(parse_version(current))
    n = max(len(a), len(b))
    a.extend([0] * (n - len(a)))
    b.extend([0] * (n - len(b)))
    return tuple(a) > tuple(b)


def fetch_latest_release(timeout: float = 5.0):
    """
    Fetches the latest GitHub release metadata for LyricNow.
    Tries GitHub REST API first (gets exact changelog notes & .exe asset URL),
    then falls back to the rate-limit-free /releases/latest redirect URL.
    Returns dict or None when offline/unreachable.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "LyricNow-Updater/1.0",
    }
    try:
        resp = requests.get(GITHUB_API_LATEST, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json() or {}
            tag = (data.get("tag_name") or "").strip()
            if tag:
                html_url = (data.get("html_url") or GITHUB_WEB_LATEST).strip()
                notes = (data.get("body") or "").strip()
                dl_url = ""
                dl_size = 0
                for asset in (data.get("assets") or []):
                    name = (asset.get("name") or "").lower()
                    if name.endswith(".exe"):
                        dl_url = (asset.get("browser_download_url") or "").strip()
                        dl_size = int(asset.get("size") or 0)
                        break
                return {
                    "version": tag,
                    "release_url": html_url,
                    "download_url": dl_url,
                    "download_size": dl_size,
                    "notes": notes,
                }
    except Exception:
        pass

    # Fallback (immune to GitHub REST API 60/hr unauthenticated IP rate limit)
    try:
        resp = requests.get(
            GITHUB_WEB_LATEST,
            headers={"User-Agent": "LyricNow-Updater/1.0"},
            timeout=timeout,
            allow_redirects=True,
        )
        m = _TAG_URL_RE.search(resp.url or "")
        if m:
            tag = m.group(1)
            return {
                "version": tag,
                "release_url": resp.url,
                "download_url": f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/LyricNow.exe",
                "download_size": 0,
                "notes": "",
            }
    except Exception:
        pass

    return None


class UpdateCheckWorker(QThread):
    """Background worker checking GitHub Releases for mandatory updates."""
    update_required = Signal(dict)
    check_completed = Signal(bool)

    def __init__(self, current_version: str, timeout: float = 5.0, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.timeout = timeout

    def run(self):
        info = fetch_latest_release(timeout=self.timeout)
        if info and is_newer_version(info.get("version", ""), self.current_version):
            self.update_required.emit(info)
            self.check_completed.emit(True)
        else:
            self.check_completed.emit(False)


class UpdateDownloadWorker(QThread):
    """Streams the new LyricNow.exe safely into a staged file before swapping."""
    progress = Signal(int, int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, download_url: str, dest_path: str, parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.dest_path = dest_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            with requests.get(
                self.download_url,
                headers={"User-Agent": "LyricNow-Updater/1.0"},
                stream=True,
                timeout=20,
                allow_redirects=True,
            ) as resp:
                if resp.status_code != 200:
                    self.failed.emit(f"Không thể tải tệp cập nhật (HTTP {resp.status_code}).")
                    return
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(self.dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if self._cancelled:
                            return
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            self.progress.emit(downloaded, total)

            # Verify valid Windows PE executable (> 5 MB and starts with MZ)
            if not os.path.exists(self.dest_path) or os.path.getsize(self.dest_path) < 5 * 1024 * 1024:
                self.failed.emit("Tệp cập nhật tải về chưa hoàn chỉnh hoặc không hợp lệ.")
                return
            with open(self.dest_path, "rb") as vf:
                if vf.read(2) != b"MZ":
                    self.failed.emit("Tệp tải về không phải tệp thực thi Windows hợp lệ.")
                    return

            self.finished_ok.emit(self.dest_path)
        except Exception as e:
            self.failed.emit(f"Lỗi khi tải bản cập nhật: {e}")


def apply_windows_self_update(new_exe_path: str, current_exe_path: str) -> bool:
    """Spawns a detached hidden batch helper to replace LyricNow.exe after exit and relaunch it."""
    try:
        exe_dir = os.path.dirname(os.path.abspath(current_exe_path))
        bat_path = os.path.join(exe_dir, "_lyricnow_updater.bat")
        cur_p = os.path.abspath(current_exe_path)
        new_p = os.path.abspath(new_exe_path)
        bat_content = (
            "@echo off\r\n"
            "setlocal\r\n"
            "set \"TRIES=0\"\r\n"
            ":WAIT_LOOP\r\n"
            "ping 127.0.0.1 -n 2 > nul\r\n"
            f"move /Y \"{new_p}\" \"{cur_p}\" > nul 2>&1\r\n"
            "if errorlevel 1 (\r\n"
            "  set /a TRIES+=1\r\n"
            "  if %TRIES% LSS 20 goto WAIT_LOOP\r\n"
            "  goto DONE\r\n"
            ")\r\n"
            f"start \"\" \"{cur_p}\"\r\n"
            ":DONE\r\n"
            "del \"%~f0\" > nul 2>&1\r\n"
        )
        with open(bat_path, "w", encoding="utf-8") as bf:
            bf.write(bat_content)

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(["cmd.exe", "/c", bat_path], cwd=exe_dir, creationflags=flags)
        return True
    except Exception as e:
        print(f"[Updater Error] Could not launch self-update helper: {e}")
        return False


class MandatoryUpdateDialog(QDialog):
    """
    Blocking modal update dialog shown when a newer release is available.
    Does not offer a Skip/Later option — users must update to continue using LyricNow.
    """

    def __init__(self, current_version: str, release_info: dict, app_lang: str = "vi", parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.app_lang = app_lang or "vi"
        self.release_info = release_info or {}
        self.latest_version = self.release_info.get("version", "")
        self.release_url = self.release_info.get("release_url") or GITHUB_WEB_LATEST
        self.download_url = self.release_info.get("download_url") or ""
        self.notes = (self.release_info.get("notes") or "").strip()
        self.download_worker = None
        self.update_applied = False

        self.setWindowTitle(tr(self.app_lang, "upd_win_title", ver=self.latest_version))
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(True)
        self.setFixedSize(490, 410)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f1f5f9;
                font-family: 'Segoe UI', sans-serif;
            }
            #HeaderCard {
                background-color: rgba(56, 189, 248, 0.12);
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: 10px;
            }
            #TitleLabel {
                font-size: 16px;
                font-weight: bold;
                color: #ffffff;
            }
            #SubLabel {
                font-size: 12px;
                color: #cbd5e1;
            }
            #VerBadgeOld {
                background-color: rgba(244, 63, 94, 0.18);
                border: 1px solid rgba(244, 63, 94, 0.45);
                color: #fda4af;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: bold;
            }
            #VerBadgeNew {
                background-color: rgba(56, 189, 248, 0.22);
                border: 1px solid rgba(56, 189, 248, 0.55);
                color: #7dd3fc;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QTextEdit {
                background-color: rgba(15, 23, 42, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 8px;
                color: #e2e8f0;
                padding: 8px;
                font-size: 12px;
            }
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.10);
                border: none;
                border-radius: 5px;
                height: 10px;
                text-align: center;
                color: #ffffff;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #38bdf8;
                border-radius: 5px;
            }
            #PrimaryUpdateBtn {
                background-color: #38bdf8;
                color: #09090b;
                border: none;
                border-radius: 8px;
                padding: 9px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            #PrimaryUpdateBtn:hover {
                background-color: #7dd3fc;
            }
            #PrimaryUpdateBtn:disabled {
                background-color: rgba(56, 189, 248, 0.40);
                color: rgba(9, 9, 11, 0.65);
            }
            #SecondaryBtn {
                background-color: rgba(255, 255, 255, 0.10);
                color: #f1f5f9;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            #SecondaryBtn:hover {
                background-color: rgba(255, 255, 255, 0.18);
            }
            #ExitBtn {
                background-color: rgba(232, 17, 35, 0.18);
                color: #fca5a5;
                border: 1px solid rgba(232, 17, 35, 0.45);
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            #ExitBtn:hover {
                background-color: #e81123;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header card
        header = QFrame()
        header.setObjectName("HeaderCard")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(14, 12, 14, 12)
        h_lay.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(IconFactory.create_pixmap("arrow_up", "#38bdf8", 32))
        icon_lbl.setFixedSize(34, 34)
        h_lay.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        lbl_title = QLabel(tr(self.app_lang, "upd_heading"))
        lbl_title.setObjectName("TitleLabel")
        lbl_sub = QLabel(tr(self.app_lang, "upd_sub"))
        lbl_sub.setObjectName("SubLabel")
        lbl_sub.setWordWrap(True)
        text_col.addWidget(lbl_title)
        text_col.addWidget(lbl_sub)
        h_lay.addLayout(text_col, stretch=1)
        layout.addWidget(header)

        # Version comparison row
        ver_row = QHBoxLayout()
        ver_row.setSpacing(10)
        lbl_old = QLabel(tr(self.app_lang, "upd_cur_ver", ver=self.current_version))
        lbl_old.setObjectName("VerBadgeOld")
        lbl_arrow = QLabel("->")
        lbl_arrow.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 13px;")
        lbl_new = QLabel(tr(self.app_lang, "upd_new_ver", ver=self.latest_version))
        lbl_new.setObjectName("VerBadgeNew")
        ver_row.addWidget(lbl_old)
        ver_row.addWidget(lbl_arrow)
        ver_row.addWidget(lbl_new)
        ver_row.addStretch(1)
        layout.addLayout(ver_row)

        # Release notes box
        lbl_notes_hdr = QLabel(tr(self.app_lang, "upd_notes_hdr"))
        lbl_notes_hdr.setStyleSheet("font-size: 12px; font-weight: bold; color: #cbd5e1;")
        layout.addWidget(lbl_notes_hdr)

        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        default_notes = f"LyricNow {self.latest_version} — GitHub Releases."
        self.txt_notes.setPlainText(self.notes if self.notes else default_notes)
        layout.addWidget(self.txt_notes, stretch=1)

        # Progress bar + status
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self.lbl_status.setVisible(False)
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Action buttons (NO Skip/Continue button!)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        can_auto = bool(getattr(sys, "frozen", False) and self.download_url)
        self.btn_update = QPushButton(tr(self.app_lang, "upd_btn_auto" if can_auto else "upd_btn_web"))
        self.btn_update.setObjectName("PrimaryUpdateBtn")
        self.btn_update.setIcon(IconFactory.create_icon("download", "#09090b", 14))
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.clicked.connect(self._on_update_clicked)

        self.btn_open_web = QPushButton(tr(self.app_lang, "upd_btn_github"))
        self.btn_open_web.setObjectName("SecondaryBtn")
        self.btn_open_web.setIcon(IconFactory.create_icon("external_link", "#f1f5f9", 12))
        self.btn_open_web.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_web.clicked.connect(self._open_release_page)

        self.btn_exit = QPushButton(tr(self.app_lang, "upd_btn_exit"))
        self.btn_exit.setObjectName("ExitBtn")
        self.btn_exit.setIcon(IconFactory.create_icon("close", "#fca5a5", 12))
        self.btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_exit.clicked.connect(self.reject)

        btn_row.addWidget(self.btn_update, stretch=1)
        btn_row.addWidget(self.btn_open_web)
        btn_row.addWidget(self.btn_exit)
        layout.addLayout(btn_row)

    def _open_release_page(self):
        webbrowser.open(self.release_url)

    def _on_update_clicked(self):
        if getattr(sys, "frozen", False) and self.download_url:
            self._start_auto_download()
        else:
            self._open_release_page()
            self.lbl_status.setText("Đã mở trang tải bản mới trên trình duyệt. Hãy chạy bản mới sau khi tải xong.")
            self.lbl_status.setVisible(True)

    def _start_auto_download(self):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        staged_path = os.path.join(exe_dir, "LyricNow_update.exe")
        self.btn_update.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText(f"Đang tải LyricNow {self.latest_version}...")
        self.lbl_status.setVisible(True)

        self.download_worker = UpdateDownloadWorker(self.download_url, staged_path, parent=self)
        self.download_worker.progress.connect(self._on_dl_progress)
        self.download_worker.finished_ok.connect(self._on_dl_finished)
        self.download_worker.failed.connect(self._on_dl_failed)
        self.download_worker.start()

    def _on_dl_progress(self, done: int, total: int):
        if total > 0:
            pct = int(min(100, round((done / total) * 100)))
            self.progress_bar.setValue(pct)
            self.lbl_status.setText(
                f"Đang tải LyricNow {self.latest_version}: {done / (1024*1024):.1f} / {total / (1024*1024):.1f} MB ({pct}%)"
            )
        else:
            self.lbl_status.setText(f"Đang tải LyricNow {self.latest_version}: {done / (1024*1024):.1f} MB...")

    def _on_dl_finished(self, staged_path: str):
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Tải hoàn tất! Đang cài đặt và khởi động lại phiên bản mới...")
        ok = apply_windows_self_update(staged_path, sys.executable)
        if ok:
            self.update_applied = True
            self.accept()
        else:
            self.btn_update.setEnabled(True)
            self.lbl_status.setText("Không thể tự thay tệp. Vui lòng nhấn 'Mở GitHub' để tải thủ công.")

    def _on_dl_failed(self, err_msg: str):
        self.btn_update.setEnabled(True)
        self.lbl_status.setText(f"{err_msg} Bạn có thể nhấn 'Mở GitHub' để tải trực tiếp.")

    def closeEvent(self, event):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self.download_worker.wait(400)
        super().closeEvent(event)

