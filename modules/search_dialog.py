import re
import requests
from modules.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, Qt, Signal, QThread, QTimer,
    QTabWidget, QTextEdit, QWidget, QLabel, QFrame, QApplication
)
from modules.icon_factory import IconFactory
from modules.i18n import tr


class _OnlineSearchWorker(QThread):
    """Background worker for Tab 1 online lyrics search so playback, lyrics & video NEVER lag."""
    status_changed = Signal(int, str)
    finished_search = Signal(int, str, list)

    def __init__(self, req_id: int, provider, query: str):
        super().__init__()
        self.req_id = req_id
        self.provider = provider
        self.query = query
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        q = self.query
        try:
            yt_id = self.provider.extract_youtube_id(q)
            if yt_id and not self._cancelled:
                self.status_changed.emit(self.req_id, "Đang nhận diện link YouTube...")
                yt_info = self.provider.fetch_youtube_info(yt_id)
                if yt_info and yt_info.get("title") and not self._cancelled:
                    q = yt_info["title"]
                    self.status_changed.emit(
                        self.req_id,
                        f"Video: {q} (Kênh: {yt_info.get('author', '')})"
                    )
            if self._cancelled:
                return
            results = self.provider.search_custom(q) or []
        except Exception as e:
            print(f"[SearchDialog OnlineSearchWorker Error] {e}")
            results = []
        if not self._cancelled:
            self.finished_search.emit(self.req_id, q, results)


class _YouTubeSearchWorker(QThread):
    """Background worker for Tab 2 YouTube URL lookup so playback, lyrics & video NEVER lag."""
    finished_yt = Signal(int, object)

    def __init__(self, req_id: int, provider, url_text: str):
        super().__init__()
        self.req_id = req_id
        self.provider = provider
        self.url_text = url_text
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        res_data = None
        try:
            res_data = self.provider.search_by_youtube_url(self.url_text)
        except Exception as e:
            print(f"[SearchDialog YouTubeSearchWorker Error] {e}")
        if not self._cancelled:
            self.finished_yt.emit(self.req_id, res_data)


class _RemoteLrcWorker(QThread):
    """Background worker downloading remote LRC URLs without freezing the overlay."""
    fetched = Signal(int, str, object)

    def __init__(self, req_id: int, url: str):
        super().__init__()
        self.req_id = req_id
        self.url = url
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        content = None
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://zingmp3.vn/",
            }
            resp = requests.get(self.url, headers=headers, timeout=6)
            if resp.status_code == 200 and resp.content:
                content = resp.content.decode("utf-8", errors="replace").lstrip("\ufeff")
        except Exception as e:
            print(f"[SearchDialog Fetch LRC Error] {e}")
        if not self._cancelled:
            self.fetched.emit(self.req_id, self.url, content)


class SearchDialog(QDialog):
    lyric_selected = Signal(dict)  # Emits selected lyric data dict

    def __init__(self, lyrics_provider, initial_query="", parent=None):
        super().__init__(parent)
        self.provider = lyrics_provider
        self.app_lang = parent.settings.get("app_lang", "vi") if (parent and hasattr(parent, "settings")) else "vi"
        self.setWindowTitle(tr(self.app_lang, "search_title"))
        self.resize(650, 580)
        self.setMinimumSize(540, 460)

        # Keep window non-modal friendly & synchronized with overlay opacity
        if parent and hasattr(parent, "settings"):
            op = float(parent.settings.get("bg_opacity", 0.75))
            self.setWindowOpacity(max(0.15, op))

        # Preserve version tags like (Solo Version), (Acoustic), (Remix), (Demo) in initial search query
        if initial_query and hasattr(self.provider, "clean_search_query"):
            self.clean_query = self.provider.clean_search_query(initial_query)
        else:
            self.clean_query = self.provider.clean_title(initial_query) if initial_query else ""
        if not self.clean_query:
            self.clean_query = initial_query

        self.yt_direct_lyric = None
        self.yt_current_info = None

        # Non-blocking background worker state (safe deferred teardown prevents PyQt6 GC aborts)
        self._online_req_id = 0
        self._yt_req_id = 0
        self._lrc_req_id = 0
        self._online_worker = None
        self._yt_worker = None
        self._lrc_worker = None
        self._lrc_context = None
        self._old_workers = []

        self.setup_ui()

    def _retire_worker(self, w):
        if w is None:
            return
        w.cancel()
        self._old_workers.append(w)
        if w.isRunning():
            w.finished.connect(lambda ww=w: QTimer.singleShot(600, lambda www=ww: self._cleanup_old_worker(www)))
        else:
            QTimer.singleShot(600, lambda ww=w: self._cleanup_old_worker(ww))

    def _cleanup_old_worker(self, w):
        if w in self._old_workers:
            if w.isRunning():
                QTimer.singleShot(600, lambda ww=w: self._cleanup_old_worker(ww))
                return
            self._old_workers.remove(w)

    def closeEvent(self, event):
        for attr in ("_online_worker", "_yt_worker", "_lrc_worker"):
            w = getattr(self, attr, None)
            if w is not None:
                setattr(self, attr, None)
                w.cancel()
                if w.isRunning():
                    w.wait(250)
                self._retire_worker(w)
        super().closeEvent(event)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Tabs
        self.tabs = QTabWidget()

        # ========================================================
        # TAB 1: Tìm kiếm Trực tuyến (Tên hoặc Link YouTube)
        # ========================================================
        tab_search = QWidget()
        t1_layout = QVBoxLayout(tab_search)
        t1_layout.setSpacing(10)
        t1_layout.setContentsMargins(10, 10, 10, 10)

        info_lbl = QLabel(tr(self.app_lang, "search_online_lbl"))
        info_lbl.setWordWrap(True)
        t1_layout.addWidget(info_lbl)

        search_box = QHBoxLayout()
        self.query_input = QLineEdit(self.clean_query)
        self.query_input.setPlaceholderText("VD: Vết Thương - Fishy / https://youtu.be/...")
        self.query_input.returnPressed.connect(self.do_search)
        search_box.addWidget(self.query_input)

        self.btn_search = QPushButton(tr(self.app_lang, "search_btn"))
        self.btn_search.setIcon(IconFactory.create_icon("search", "#09090b"))
        self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search.clicked.connect(self.do_search)
        search_box.addWidget(self.btn_search)
        t1_layout.addLayout(search_box)

        self.lbl_search_status = QLabel("")
        self.lbl_search_status.setStyleSheet("color: #38bdf8; font-size: 12px; font-style: italic;")
        self.lbl_search_status.setVisible(False)
        t1_layout.addWidget(self.lbl_search_status)

        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self.on_item_selected)
        self.result_list.currentItemChanged.connect(lambda cur, _prev: self._update_preview(cur, self.txt_preview_online))
        t1_layout.addWidget(self.result_list, stretch=3)

        self.txt_preview_online = QTextEdit()
        self.txt_preview_online.setReadOnly(True)
        self.txt_preview_online.setFixedHeight(96)
        self.txt_preview_online.setPlaceholderText(tr(self.app_lang, "search_preview_ph"))
        t1_layout.addWidget(self.txt_preview_online)

        self.btn_apply_online = QPushButton(tr(self.app_lang, "search_apply_btn"))
        self.btn_apply_online.setIcon(IconFactory.create_icon("check", "#09090b"))
        self.btn_apply_online.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_online.clicked.connect(self.on_apply_clicked)
        t1_layout.addWidget(self.btn_apply_online)

        self.tabs.addTab(tab_search, IconFactory.create_icon("search", "#38bdf8"), tr(self.app_lang, "search_tab_online"))

        # ========================================================
        # TAB 2: Tìm theo Link YouTube (URL)
        # ========================================================
        tab_yt = QWidget()
        t_yt_layout = QVBoxLayout(tab_yt)
        t_yt_layout.setSpacing(10)
        t_yt_layout.setContentsMargins(10, 10, 10, 10)

        yt_info_lbl = QLabel(tr(self.app_lang, "search_yt_lbl"))
        yt_info_lbl.setWordWrap(True)
        t_yt_layout.addWidget(yt_info_lbl)

        yt_box = QHBoxLayout()
        self.yt_url_input = QLineEdit()
        self.yt_url_input.setPlaceholderText("https://www.youtube.com/watch?v=... / https://youtu.be/...")
        self.yt_url_input.returnPressed.connect(self.do_search_youtube_url)
        yt_box.addWidget(self.yt_url_input)

        btn_paste_clip = QPushButton(tr(self.app_lang, "search_paste_link"))
        btn_paste_clip.setIcon(IconFactory.create_icon("paste", "#09090b"))
        btn_paste_clip.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_paste_clip.clicked.connect(self.paste_from_clipboard)
        yt_box.addWidget(btn_paste_clip)

        self.btn_yt_search = QPushButton(tr(self.app_lang, "search_yt_btn"))
        self.btn_yt_search.setIcon(IconFactory.create_icon("search", "#09090b"))
        self.btn_yt_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_yt_search.clicked.connect(self.do_search_youtube_url)
        yt_box.addWidget(self.btn_yt_search)
        t_yt_layout.addLayout(yt_box)

        # Video Info Card
        self.card_yt = QFrame()
        self.card_yt.setObjectName("VideoCard")
        card_layout = QVBoxLayout(self.card_yt)
        card_layout.setSpacing(6)
        card_layout.setContentsMargins(10, 8, 10, 8)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        lbl_ic_video = QLabel()
        lbl_ic_video.setPixmap(IconFactory.create_pixmap("video", "#ffffff", 14))
        lbl_ic_video.setFixedSize(16, 16)
        title_row.addWidget(lbl_ic_video)

        self.lbl_yt_title = QLabel("Chưa có video nào được chọn")
        self.lbl_yt_title.setStyleSheet("font-weight: bold; color: #ffffff; font-size: 13px;")
        self.lbl_yt_title.setWordWrap(True)
        title_row.addWidget(self.lbl_yt_title, stretch=1)
        card_layout.addLayout(title_row)

        author_row = QHBoxLayout()
        author_row.setSpacing(6)
        lbl_ic_user = QLabel()
        lbl_ic_user.setPixmap(IconFactory.create_pixmap("user", "#38bdf8", 13))
        lbl_ic_user.setFixedSize(16, 16)
        author_row.addWidget(lbl_ic_user)

        self.lbl_yt_author = QLabel("Kênh / Ca sĩ: --")
        self.lbl_yt_author.setStyleSheet("color: #38bdf8; font-size: 12px;")
        author_row.addWidget(self.lbl_yt_author, stretch=1)
        card_layout.addLayout(author_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        lbl_ic_info = QLabel()
        lbl_ic_info.setPixmap(IconFactory.create_pixmap("info", "#a1a1aa", 12))
        lbl_ic_info.setFixedSize(16, 16)
        status_row.addWidget(lbl_ic_info)

        self.lbl_yt_status = QLabel("Hỗ trợ mọi link: Watch, Shorts, YouTu.be, Music YouTube...")
        self.lbl_yt_status.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        self.lbl_yt_status.setWordWrap(True)
        status_row.addWidget(self.lbl_yt_status, stretch=1)
        card_layout.addLayout(status_row)

        self.btn_quick_apply = QPushButton(" Áp dụng lời bài hát này ngay")
        self.btn_quick_apply.setIcon(IconFactory.create_icon("bolt", "#ffffff"))
        self.btn_quick_apply.setObjectName("QuickApplyBtn")
        self.btn_quick_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quick_apply.setVisible(False)
        self.btn_quick_apply.clicked.connect(self.on_quick_apply_clicked)
        card_layout.addWidget(self.btn_quick_apply)

        t_yt_layout.addWidget(self.card_yt)

        self.yt_result_list = QListWidget()
        self.yt_result_list.itemDoubleClicked.connect(self.on_yt_item_selected)
        self.yt_result_list.currentItemChanged.connect(lambda cur, _prev: self._update_preview(cur, self.txt_preview_yt))
        t_yt_layout.addWidget(self.yt_result_list, stretch=2)

        self.txt_preview_yt = QTextEdit()
        self.txt_preview_yt.setReadOnly(True)
        self.txt_preview_yt.setFixedHeight(80)
        self.txt_preview_yt.setPlaceholderText("Bấm vào một phiên bản ở trên để xem trước lời bài hát...")
        t_yt_layout.addWidget(self.txt_preview_yt)

        self.btn_apply_yt = QPushButton(tr(self.app_lang, "search_yt_apply"))
        self.btn_apply_yt.setIcon(IconFactory.create_icon("check", "#09090b"))
        self.btn_apply_yt.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_yt.clicked.connect(self.on_apply_yt_clicked)
        t_yt_layout.addWidget(self.btn_apply_yt)

        self.tabs.addTab(tab_yt, IconFactory.create_icon("youtube", "#f43f5e"), tr(self.app_lang, "search_tab_yt"))

        # ========================================================
        # TAB 3: Dán Lời Bài Hát Thủ Công
        # ========================================================
        tab_paste = QWidget()
        t2_layout = QVBoxLayout(tab_paste)
        t2_layout.setSpacing(8)
        t2_layout.setContentsMargins(10, 10, 10, 10)

        paste_info = QLabel(tr(self.app_lang, "search_paste_lbl"))
        paste_info.setWordWrap(True)
        t2_layout.addWidget(paste_info)

        self.txt_custom_lyrics = QTextEdit()
        self.txt_custom_lyrics.setPlaceholderText("Paste lyrics here...")
        t2_layout.addWidget(self.txt_custom_lyrics)

        btn_apply_custom = QPushButton(tr(self.app_lang, "search_paste_save"))
        btn_apply_custom.setIcon(IconFactory.create_icon("save", "#09090b"))
        btn_apply_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply_custom.clicked.connect(self.on_apply_custom_lyrics)
        t2_layout.addWidget(btn_apply_custom)

        self.tabs.addTab(tab_paste, IconFactory.create_icon("edit", "#38bdf8"), tr(self.app_lang, "search_tab_paste"))

        layout.addWidget(self.tabs)

        # Bottom Cancel
        btn_cancel = QPushButton(tr(self.app_lang, "btn_close"))
        btn_cancel.setIcon(IconFactory.create_icon("close", "#09090b"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

        # Prevent QDialog autoDefault from hijacking Enter key
        for btn in self.findChildren(QPushButton):
            btn.setAutoDefault(False)
            btn.setDefault(False)

        self.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                color: #e4e4e7;
            }
            QTabWidget::pane {
                border: 1px solid #3f3f46;
                border-radius: 8px;
                background-color: #27272a;
            }
            QTabBar::tab {
                background-color: #3f3f46;
                color: #a1a1aa;
                padding: 9px 18px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #52525b;
                border-bottom: none;
            }
            QTabBar::tab:hover {
                background-color: #52525b;
                color: #ffffff;
            }
            QTabBar::tab:selected {
                background-color: #27272a;
                color: #38bdf8;
                border-top: 3px solid #38bdf8;
                border-left: 1px solid #3f3f46;
                border-right: 1px solid #3f3f46;
            }
            QLabel {
                color: #d4d4d8;
                font-size: 13px;
                font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', 'Leelawadee UI', sans-serif;
            }
            QLineEdit, QTextEdit {
                background-color: #18181b;
                color: #f4f4f5;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #38bdf8;
            }
            QPushButton {
                background-color: #38bdf8;
                color: #09090b;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #7dd3fc;
            }
            QPushButton:disabled {
                background-color: rgba(56, 189, 248, 0.45);
                color: rgba(9, 9, 11, 0.65);
            }
            #QuickApplyBtn {
                background-color: #10b981;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            #QuickApplyBtn:hover {
                background-color: #34d399;
            }
            #VideoCard {
                background-color: #202024;
                border: 1px solid #3f3f46;
                border-radius: 8px;
            }
            QListWidget {
                background-color: #18181b;
                color: #f4f4f5;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 5px;
                font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #27272a;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #27272a;
            }
            QListWidget::item:selected {
                background-color: #3f3f46;
                color: #38bdf8;
            }
        """)

        # Defer auto-search onto background thread AFTER dialog opens so opening Search NEVER lags lyrics or video!
        if self.clean_query and self.provider.extract_youtube_id(self.clean_query):
            self.tabs.setCurrentIndex(1)
            self.yt_url_input.setText(self.clean_query)
            QTimer.singleShot(30, self.do_search_youtube_url)
        elif self.clean_query:
            QTimer.singleShot(30, self.do_search)

    def paste_from_clipboard(self):
        clip = QApplication.clipboard()
        text = clip.text().strip() if clip else ""
        if text:
            self.yt_url_input.setText(text)
            self.do_search_youtube_url()
        else:
            QMessageBox.information(self, "Thông báo", "Clipboard hiện đang trống. Hãy sao chép link video YouTube trước!")

    @staticmethod
    def _format_duration(dur) -> str:
        try:
            sec = int(round(float(dur or 0)))
            if sec > 0:
                return f"{sec // 60:02d}:{sec % 60:02d}"
        except Exception:
            pass
        return "--:--"

    @staticmethod
    def _extract_preview(item_data: dict) -> str:
        raw = item_data.get("syncedLyrics") or item_data.get("plainLyrics") or ""
        if not raw or str(raw).startswith("http"):
            return ""
        preview_lines = []
        for ln in str(raw).splitlines():
            clean = re.sub(r'\[[^\]]*\]|<\d+:\d+(?:[\.:]\d+)?>', '', ln).strip()
            if clean and len(clean) >= 2:
                preview_lines.append(clean)
            if len(preview_lines) >= 2:
                break
        if not preview_lines:
            return ""
        joined = " / ".join(preview_lines)
        return (joined[:78] + "...") if len(joined) > 80 else joined

    def _format_candidate_text(self, r: dict) -> str:
        sync_tag = "Khớp thời gian" if r.get("synced") else "Lời thường"
        title = r.get("trackName") or "Unknown Title"
        artist = r.get("artistName") or "Unknown Artist"
        source = r.get("source") or "Online"
        dur_str = self._format_duration(r.get("duration"))
        preview = self._extract_preview(r)
        header = f"{title} - {artist}  [{dur_str}]  [{sync_tag} | {source}]"
        if preview:
            return f"{header}\n\"{preview}\""
        album = r.get("albumName") or source
        return f"{header}\nNguồn: {source} | Album: {album}"

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.result_list.hasFocus() and self.result_list.currentItem():
                self.on_apply_clicked()
                event.accept()
                return
            if self.yt_result_list.hasFocus() and self.yt_result_list.currentItem():
                self.on_apply_yt_clicked()
                event.accept()
                return
            if self.query_input.hasFocus() or self.yt_url_input.hasFocus():
                event.accept()
                return
        super().keyPressEvent(event)

    def _render_preview_text(self, raw: str, preview_box: QTextEdit):
        clean_lines = []
        for ln in str(raw).splitlines():
            txt = re.sub(r'\[[^\]]*\]|<\d+:\d+(?:[\.:]\d+)?>', '', ln).strip()
            if txt:
                clean_lines.append(txt)
        if clean_lines:
            preview_box.setPlainText("\n".join(clean_lines))
        else:
            preview_box.setPlainText("(Không có nội dung lời đọc được ở phiên bản này)")

    def _start_remote_lrc_fetch(self, url: str, context: dict):
        self._lrc_req_id += 1
        req_id = self._lrc_req_id
        self._lrc_context = context
        if self._lrc_worker is not None:
            old_w = self._lrc_worker
            self._lrc_worker = None
            try:
                old_w.fetched.disconnect()
            except Exception:
                pass
            self._retire_worker(old_w)
        w = _RemoteLrcWorker(req_id, url)
        w.fetched.connect(self._on_remote_lrc_fetched)
        self._lrc_worker = w
        w.start()

    def _on_remote_lrc_fetched(self, req_id: int, url: str, fetched):
        if req_id != self._lrc_req_id or not self._lrc_context:
            return
        ctx = self._lrc_context
        self._lrc_context = None
        item = ctx.get("item")
        list_widget = ctx.get("list_widget")
        preview_box = ctx.get("preview_box")
        apply_after = bool(ctx.get("apply_after", False))
        is_yt_tab = bool(ctx.get("is_yt_tab", False))

        if fetched and item is not None:
            try:
                item_data = item.data(Qt.ItemDataRole.UserRole) or {}
                item_data["_fetched_lrc"] = fetched
                item.setData(Qt.ItemDataRole.UserRole, item_data)
            except RuntimeError:
                return

        if preview_box is not None:
            try:
                if list_widget is None or list_widget.currentItem() is item:
                    if fetched:
                        self._render_preview_text(fetched, preview_box)
                    else:
                        preview_box.setPlainText("Không tải được lời từ liên kết này. Vui lòng chọn phiên bản khác.")
            except RuntimeError:
                return

        if apply_after:
            self.btn_apply_online.setEnabled(True)
            self.btn_apply_yt.setEnabled(True)
            if item is not None:
                self._finalize_apply_item(item, is_yt_tab=is_yt_tab, allow_remote=False)

    def _update_preview(self, item, preview_box: QTextEdit):
        if item is None:
            preview_box.clear()
            return
        list_widget = item.listWidget()
        item_data = item.data(Qt.ItemDataRole.UserRole) or {}
        raw = item_data.get("_fetched_lrc") or item_data.get("syncedLyrics") or item_data.get("plainLyrics") or ""
        if isinstance(raw, str) and raw.startswith("http"):
            preview_box.setPlainText("Đang tải xem trước lời bài hát...")
            self._start_remote_lrc_fetch(raw, {
                "item": item,
                "list_widget": list_widget,
                "preview_box": preview_box,
                "apply_after": False,
                "is_yt_tab": (list_widget is self.yt_result_list),
            })
            return
        self._render_preview_text(raw, preview_box)

    def do_search(self):
        query = self.query_input.text().strip()
        if not query:
            return

        self._online_req_id += 1
        req_id = self._online_req_id
        if self._online_worker is not None:
            old_w = self._online_worker
            self._online_worker = None
            try:
                old_w.status_changed.disconnect()
                old_w.finished_search.disconnect()
            except Exception:
                pass
            self._retire_worker(old_w)

        self.result_list.clear()
        self.txt_preview_online.clear()
        self.btn_search.setEnabled(False)
        self.btn_search.setText(" Đang tìm...")
        self.lbl_search_status.setText(f"Đang tìm lời bài hát cho: '{query}'...")
        self.lbl_search_status.setVisible(True)

        w = _OnlineSearchWorker(req_id, self.provider, query)
        w.status_changed.connect(self._on_online_status)
        w.finished_search.connect(self._on_online_search_finished)
        self._online_worker = w
        w.start()

    def _on_online_status(self, req_id: int, status_text: str):
        if req_id != self._online_req_id:
            return
        self.lbl_search_status.setText(status_text)
        self.lbl_search_status.setVisible(True)

    def _on_online_search_finished(self, req_id: int, resolved_query: str, results: list):
        if req_id != self._online_req_id:
            return
        self.btn_search.setEnabled(True)
        self.btn_search.setText(tr(self.app_lang, "search_btn"))

        if not results:
            self.lbl_search_status.setText(
                f"Không tìm thấy kết quả cho '{resolved_query}'. Hãy thử rút gọn tên bài hát hoặc dán link YouTube / lời thủ công."
            )
            return

        self.lbl_search_status.setText(f"Tìm thấy {len(results)} phiên bản lời — bấm từng dòng để xem trước lời rồi nhấn Áp dụng.")
        for r in results:
            item = QListWidgetItem(self._format_candidate_text(r))
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.result_list.addItem(item)
        if self.result_list.count() > 0:
            self.result_list.setCurrentRow(0)

    def do_search_youtube_url(self):
        url_text = self.yt_url_input.text().strip()
        if not url_text:
            QMessageBox.warning(self, "Chú ý", "Vui lòng nhập hoặc dán đường link video YouTube.")
            return

        yt_id = self.provider.extract_youtube_id(url_text)
        if not yt_id:
            QMessageBox.warning(
                self, "Link không hợp lệ",
                "Đường link không đúng định dạng YouTube.\n\n"
                "Ví dụ định dạng đúng:\n"
                "- https://www.youtube.com/watch?v=...\n"
                "- https://youtu.be/...\n"
                "- https://www.youtube.com/shorts/..."
            )
            return

        self._yt_req_id += 1
        req_id = self._yt_req_id
        if self._yt_worker is not None:
            old_w = self._yt_worker
            self._yt_worker = None
            try:
                old_w.finished_yt.disconnect()
            except Exception:
                pass
            self._retire_worker(old_w)

        self.btn_yt_search.setEnabled(False)
        self.btn_yt_search.setText(" Đang phân tích...")
        self.lbl_yt_status.setText("Đang lấy thông tin video từ YouTube...")
        self.btn_quick_apply.setVisible(False)
        self.yt_result_list.clear()
        self.txt_preview_yt.clear()

        w = _YouTubeSearchWorker(req_id, self.provider, url_text)
        w.finished_yt.connect(self._on_yt_search_finished)
        self._yt_worker = w
        w.start()

    def _on_yt_search_finished(self, req_id: int, res_data):
        if req_id != self._yt_req_id:
            return
        self.btn_yt_search.setEnabled(True)
        self.btn_yt_search.setText(tr(self.app_lang, "search_yt_btn"))

        if not res_data or not res_data.get("video_info"):
            self.lbl_yt_status.setText("Không thể lấy thông tin video. Vui lòng kiểm tra lại kết nối mạng hoặc link video.")
            return

        info = res_data["video_info"]
        self.yt_current_info = info
        self.lbl_yt_title.setText(f"Video: {info['title']}")
        self.lbl_yt_author.setText(f"Kênh / Ca sĩ: {info['author'] or 'Không rõ'}")

        direct_match = res_data.get("direct_match")
        candidates = res_data.get("candidates") or []

        if direct_match and direct_match.get("lines"):
            self.yt_direct_lyric = direct_match
            self.lbl_yt_status.setText(f"Đã tìm thấy lời khớp trực tiếp từ {direct_match.get('source', 'Online')}!")
            self.btn_quick_apply.setText(f" Áp dụng lời bài hát ngay ({direct_match.get('source', 'Chuẩn')})")
            self.btn_quick_apply.setVisible(True)
        else:
            self.yt_direct_lyric = None
            self.btn_quick_apply.setVisible(False)
            self.lbl_yt_status.setText(f"Tìm thấy {len(candidates)} phiên bản lời bài hát liên quan bên dưới:")

        if not candidates and not direct_match:
            self.lbl_yt_status.setText("Không tìm thấy lời bài hát khớp trên cơ sở dữ liệu cho video này.")
            return

        for r in candidates:
            item = QListWidgetItem(self._format_candidate_text(r))
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.yt_result_list.addItem(item)
        if self.yt_result_list.count() > 0:
            self.yt_result_list.setCurrentRow(0)

    def on_quick_apply_clicked(self):
        if not self.yt_direct_lyric or not self.yt_direct_lyric.get("lines"):
            QMessageBox.warning(self, "Chú ý", "Lời bài hát trực tiếp bị trống. Vui lòng chọn một phiên bản khác trong danh sách!")
            return

        data = self.yt_direct_lyric.copy()
        src = str(data.get("source") or "Online")
        if "Manual" not in src and "Custom" not in src:
            data["source"] = f"Manual YouTube ({src})"
        if self.yt_current_info:
            data["video_id"] = self.yt_current_info.get("video_id")
            data["thumbnail_url"] = self.yt_current_info.get("thumbnail")
            clean_t = self.provider.clean_title(self.yt_current_info["title"])
            clean_a = self.yt_current_info.get("author", "")
            if self.provider.cache:
                self.provider.cache.set(clean_t, clean_a, data)
                self.provider.cache.set(self.yt_current_info["title"], clean_a, data)

        self.lyric_selected.emit(data)
        self.accept()

    def on_item_selected(self, item):
        self._apply_from_list(self.result_list, is_yt_tab=False, explicit_item=item)

    def on_yt_item_selected(self, item):
        self._apply_from_list(self.yt_result_list, is_yt_tab=True, explicit_item=item)

    def on_apply_clicked(self):
        self._apply_from_list(self.result_list, is_yt_tab=False)

    def on_apply_yt_clicked(self):
        self._apply_from_list(self.yt_result_list, is_yt_tab=True)

    def _apply_from_list(self, list_widget: QListWidget, is_yt_tab: bool = False, explicit_item=None):
        target_item = explicit_item
        if target_item is None:
            selected_items = list_widget.selectedItems()
            target_item = selected_items[0] if selected_items else list_widget.currentItem()
        if target_item is None:
            QMessageBox.warning(self, "Chú ý", "Vui lòng chọn bài hát trong danh sách.")
            return
        self._finalize_apply_item(target_item, is_yt_tab=is_yt_tab, allow_remote=True)

    def _finalize_apply_item(self, target_item, is_yt_tab: bool = False, allow_remote: bool = True):
        item_data = target_item.data(Qt.ItemDataRole.UserRole) or {}
        synced_text = item_data.get("_fetched_lrc") or item_data.get("syncedLyrics")
        plain_text = item_data.get("plainLyrics")

        if allow_remote and synced_text and isinstance(synced_text, str) and synced_text.startswith("http"):
            self.btn_apply_online.setEnabled(False)
            self.btn_apply_yt.setEnabled(False)
            self._start_remote_lrc_fetch(synced_text, {
                "item": target_item,
                "list_widget": target_item.listWidget(),
                "preview_box": self.txt_preview_yt if is_yt_tab else self.txt_preview_online,
                "apply_after": True,
                "is_yt_tab": is_yt_tab,
            })
            return

        duration = 210.0
        if self.parent() and hasattr(self.parent(), "current_media_state") and self.parent().current_media_state:
            if self.parent().current_media_state.duration > 30.0:
                duration = self.parent().current_media_state.duration

        parsed_lines = []
        if synced_text and not str(synced_text).startswith("http"):
            parsed_lines = self.provider.parse_lrc(synced_text, duration=duration)
        if not parsed_lines and plain_text:
            parsed_lines = self.provider.parse_lrc(plain_text, duration=duration)

        if not parsed_lines:
            QMessageBox.warning(
                self, "Không có lời bài hát",
                "Phiên bản bạn vừa chọn không có nội dung lời hoặc không tải được từ máy chủ.\n"
                "Vui lòng chọn một phiên bản khác trong danh sách!"
            )
            return

        formatted_data = {
            "title": item_data.get("trackName"),
            "artist": item_data.get("artistName"),
            "synced": True,
            "sync_offset": 0.0,
            "lines": parsed_lines,
            "raw_lrc": (synced_text if not str(synced_text or "").startswith("http") else "") or plain_text,
            "source": f"Manual Search ({item_data.get('source', 'Online')})"
        }

        if is_yt_tab and self.yt_current_info:
            formatted_data["video_id"] = self.yt_current_info.get("video_id")
            formatted_data["thumbnail_url"] = self.yt_current_info.get("thumbnail")
            if self.provider.cache:
                clean_t = self.provider.clean_title(self.yt_current_info["title"])
                clean_a = self.yt_current_info.get("author", "")
                self.provider.cache.set(clean_t, clean_a, formatted_data)
                self.provider.cache.set(self.yt_current_info["title"], clean_a, formatted_data)

        self.lyric_selected.emit(formatted_data)
        self.accept()

    def on_apply_custom_lyrics(self):
        text = self.txt_custom_lyrics.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Chú ý", "Vui lòng dán lời bài hát vào ô trống.")
            return

        duration = 210.0
        if self.parent() and hasattr(self.parent(), "current_media_state") and self.parent().current_media_state:
            if self.parent().current_media_state.duration > 30.0:
                duration = self.parent().current_media_state.duration

        parsed_lines = self.provider.parse_lrc(text, duration=duration)
        if not parsed_lines:
            QMessageBox.warning(self, "Chú ý", "Nội dung bạn dán không hợp lệ hoặc không có dòng lời nào.")
            return

        formatted_data = {
            "title": self.clean_query or "Custom Song",
            "artist": "Custom",
            "synced": True,
            "sync_offset": 0.0,
            "lines": parsed_lines,
            "raw_lrc": text,
            "source": "Custom Paste"
        }

        if self.provider.cache and self.clean_query:
            self.provider.cache.set(self.clean_query, "", formatted_data)

        self.lyric_selected.emit(formatted_data)
        self.accept()
