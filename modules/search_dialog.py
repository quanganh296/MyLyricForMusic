import requests
from modules.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, Qt, Signal,
    QTabWidget, QTextEdit, QWidget, QLabel, QFrame, QApplication
)
from modules.icon_factory import IconFactory

class SearchDialog(QDialog):
    lyric_selected = Signal(dict) # Emits selected lyric data dict

    def __init__(self, lyrics_provider, initial_query="", parent=None):
        super().__init__(parent)
        self.provider = lyrics_provider
        self.setWindowTitle("Tìm kiếm & Dán Lời Bài Hát - LyricNow")
        self.resize(620, 520)
        self.setMinimumSize(520, 420)

        # Synchronize window opacity with main overlay window
        if parent and hasattr(parent, "settings"):
            op = float(parent.settings.get("bg_opacity", 0.75))
            self.setWindowOpacity(max(0.15, op))
        
        # Clean initial query automatically
        self.clean_query = self.provider.clean_title(initial_query) if initial_query else ""
        if not self.clean_query:
            self.clean_query = initial_query

        self.yt_direct_lyric = None
        self.yt_current_info = None

        self.setup_ui()

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

        info_lbl = QLabel("Nhập tên bài hát, ca sĩ hoặc dán trực tiếp link video YouTube:")
        info_lbl.setWordWrap(True)
        t1_layout.addWidget(info_lbl)

        search_box = QHBoxLayout()
        self.query_input = QLineEdit(self.clean_query)
        self.query_input.setPlaceholderText("VD: Vết Thương - Fishy hoặc https://youtu.be/...")
        self.query_input.returnPressed.connect(self.do_search)
        search_box.addWidget(self.query_input)

        self.btn_search = QPushButton(" Tìm trực tuyến")
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
        t1_layout.addWidget(self.result_list)

        btn_apply_online = QPushButton(" Áp dụng lời bài hát đã chọn")
        btn_apply_online.setIcon(IconFactory.create_icon("check", "#09090b"))
        btn_apply_online.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply_online.clicked.connect(self.on_apply_clicked)
        t1_layout.addWidget(btn_apply_online)

        self.tabs.addTab(tab_search, IconFactory.create_icon("search", "#38bdf8"), "Tìm kiếm Trực tuyến")

        # ========================================================
        # TAB 2: Tìm theo Link YouTube (URL)
        # ========================================================
        tab_yt = QWidget()
        t_yt_layout = QVBoxLayout(tab_yt)
        t_yt_layout.setSpacing(10)
        t_yt_layout.setContentsMargins(10, 10, 10, 10)

        yt_info_lbl = QLabel("Dán đường link (URL) video YouTube để tự động lấy tên bài hát & tìm lời chuẩn:")
        yt_info_lbl.setWordWrap(True)
        t_yt_layout.addWidget(yt_info_lbl)

        yt_box = QHBoxLayout()
        self.yt_url_input = QLineEdit()
        self.yt_url_input.setPlaceholderText("https://www.youtube.com/watch?v=... hoặc https://youtu.be/...")
        self.yt_url_input.returnPressed.connect(self.do_search_youtube_url)
        yt_box.addWidget(self.yt_url_input)

        btn_paste_clip = QPushButton(" Dán Link")
        btn_paste_clip.setIcon(IconFactory.create_icon("paste", "#09090b"))
        btn_paste_clip.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_paste_clip.clicked.connect(self.paste_from_clipboard)
        yt_box.addWidget(btn_paste_clip)

        self.btn_yt_search = QPushButton(" Tìm Lời Video")
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

        # Video title row with Font Awesome video icon
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

        # Author row with Font Awesome user icon
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

        # Status row with Font Awesome info icon
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
        t_yt_layout.addWidget(self.yt_result_list)

        self.btn_apply_yt = QPushButton(" Áp dụng phiên bản đã chọn")
        self.btn_apply_yt.setIcon(IconFactory.create_icon("check", "#09090b"))
        self.btn_apply_yt.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_yt.clicked.connect(self.on_apply_yt_clicked)
        t_yt_layout.addWidget(self.btn_apply_yt)

        self.tabs.addTab(tab_yt, IconFactory.create_icon("youtube", "#f43f5e"), "Tìm theo Link YouTube")

        # ========================================================
        # TAB 3: Dán Lời Bài Hát Thủ Công
        # ========================================================
        tab_paste = QWidget()
        t2_layout = QVBoxLayout(tab_paste)
        t2_layout.setSpacing(8)
        t2_layout.setContentsMargins(10, 10, 10, 10)

        paste_info = QLabel("Dán lời bài hát (tự động phân bổ thời gian trôi lời mượt mà cho cả văn bản thường):")
        paste_info.setWordWrap(True)
        t2_layout.addWidget(paste_info)

        self.txt_custom_lyrics = QTextEdit()
        self.txt_custom_lyrics.setPlaceholderText(
            "Dán lời bài hát từ Google / Genius vào đây...\n\n"
            "Ví dụ:\n"
            "Ngồi ngẩn ngơ, anh hát vu vơ những bản tình ca năm ấy...\n"
            "Có đôi lần khẽ cười vì anh chợt nhớ người làm anh say..."
        )
        t2_layout.addWidget(self.txt_custom_lyrics)

        btn_apply_custom = QPushButton(" Lưu & Áp dụng lời vừa dán")
        btn_apply_custom.setIcon(IconFactory.create_icon("save", "#09090b"))
        btn_apply_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply_custom.clicked.connect(self.on_apply_custom_lyrics)
        t2_layout.addWidget(btn_apply_custom)

        self.tabs.addTab(tab_paste, IconFactory.create_icon("edit", "#38bdf8"), "Dán Lời Thủ Công")

        layout.addWidget(self.tabs)

        # Bottom Cancel
        btn_cancel = QPushButton(" Đóng")
        btn_cancel.setIcon(IconFactory.create_icon("close", "#09090b"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

        # QSS Styling with Gray Tab Interface
        self.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                color: #e4e4e7;
            }
            /* Gray Tab Interface Styling */
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

        # If initial query is already a YouTube URL, switch to Tab 2 automatically
        if self.clean_query and self.provider.extract_youtube_id(self.clean_query):
            self.tabs.setCurrentIndex(1)
            self.yt_url_input.setText(self.clean_query)
            self.do_search_youtube_url()
        elif self.clean_query:
            self.do_search()

    def paste_from_clipboard(self):
        clip = QApplication.clipboard()
        text = clip.text().strip() if clip else ""
        if text:
            self.yt_url_input.setText(text)
            self.do_search_youtube_url()
        else:
            QMessageBox.information(self, "Thông báo", "Clipboard hiện đang trống. Hãy sao chép link video YouTube trước!")

    def do_search(self):
        query = self.query_input.text().strip()
        if not query:
            return

        self.result_list.clear()
        self.btn_search.setEnabled(False)
        self.btn_search.setText(" Đang tìm...")

        # If user entered a YouTube URL into Tab 1 search box
        yt_id = self.provider.extract_youtube_id(query)
        if yt_id:
            self.lbl_search_status.setText("Đang nhận diện link YouTube...")
            self.lbl_search_status.setVisible(True)
            QApplication.processEvents()
            
            yt_info = self.provider.fetch_youtube_info(yt_id)
            if yt_info and yt_info.get("title"):
                query = yt_info["title"]
                self.lbl_search_status.setText(f"Video: {query} (Kênh: {yt_info.get('author', '')})")
                self.lbl_search_status.setVisible(True)

        results = self.provider.search_custom(query)
        self.btn_search.setEnabled(True)
        self.btn_search.setText(" Tìm trực tuyến")

        if not results:
            QMessageBox.information(
                self, "Thông báo",
                f"Không tìm thấy lời trên dữ liệu trực tuyến với từ khóa: '{query}'.\n\n"
                "Bạn có thể chuyển sang Tab 'Tìm theo Link YouTube' hoặc 'Dán Lời Thủ Công'!"
            )
            return

        for r in results:
            sync_tag = "[Lời khớp thời gian (Synced)]" if r["synced"] else "[Lời bài hát thường (Plain)]"
            title = r.get("trackName") or "Unknown Title"
            artist = r.get("artistName") or "Unknown Artist"
            album = r.get("albumName") or ""
            
            display_text = f"{title} - {artist} {sync_tag}\nAlbum: {album}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.result_list.addItem(item)

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

        self.btn_yt_search.setEnabled(False)
        self.btn_yt_search.setText(" Đang phân tích...")
        self.lbl_yt_status.setText("Đang lấy thông tin video từ YouTube...")
        self.btn_quick_apply.setVisible(False)
        self.yt_result_list.clear()
        QApplication.processEvents()

        res_data = self.provider.search_by_youtube_url(url_text)
        self.btn_yt_search.setEnabled(True)
        self.btn_yt_search.setText(" Tìm Lời Video")

        if not res_data or not res_data.get("video_info"):
            self.lbl_yt_status.setText("Không thể lấy thông tin video. Vui lòng kiểm tra lại kết nối mạng hoặc link video.")
            QMessageBox.critical(self, "Lỗi", "Không thể lấy thông tin video từ YouTube. Video có thể đã bị xóa hoặc ở chế độ riêng tư.")
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
            QMessageBox.information(
                self, "Thông báo",
                f"Đã nhận diện video: '{info['title']}', nhưng chưa có lời đồng bộ trên hệ thống.\n\n"
                "Bạn có thể chuyển sang Tab 'Dán Lời Thủ Công' để dán lời trực tiếp cho video này!"
            )
            return

        for r in candidates:
            sync_tag = "[Lời khớp thời gian (Synced)]" if r["synced"] else "[Lời bài hát thường (Plain)]"
            title = r.get("trackName") or "Unknown Title"
            artist = r.get("artistName") or "Unknown Artist"
            album = r.get("albumName") or ""
            source = r.get("source") or "Online"
            
            display_text = f"{title} - {artist} {sync_tag}\nNguồn: {source} | Album: {album}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.yt_result_list.addItem(item)

    def on_quick_apply_clicked(self):
        if not self.yt_direct_lyric:
            return

        data = self.yt_direct_lyric.copy()
        if self.yt_current_info:
            data["video_id"] = self.yt_current_info.get("video_id")
            data["thumbnail_url"] = self.yt_current_info.get("thumbnail")
            clean_t = self.provider.clean_title(self.yt_current_info["title"])
            clean_a = self.yt_current_info.get("author", "")
            if self.provider.cache:
                self.provider.cache.set(clean_t, clean_a, data)
                self.provider.cache.set(self.yt_current_info["title"], clean_a, data)

        self.lyric_selected.emit(data)
        QMessageBox.information(self, "Thành công", f"Đã áp dụng lời bài hát thành công cho video:\n'{data.get('title')}'!")
        self.accept()

    def on_item_selected(self, item):
        self.on_apply_clicked()

    def on_yt_item_selected(self, item):
        self.on_apply_yt_clicked()

    def on_apply_clicked(self):
        self._apply_from_list(self.result_list)

    def on_apply_yt_clicked(self):
        self._apply_from_list(self.yt_result_list, is_yt_tab=True)

    def _apply_from_list(self, list_widget: QListWidget, is_yt_tab: bool = False):
        selected_items = list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Chú ý", "Vui lòng chọn bài hát trong danh sách.")
            return

        item_data = selected_items[0].data(Qt.ItemDataRole.UserRole)
        synced_text = item_data.get("syncedLyrics")
        plain_text = item_data.get("plainLyrics")

        if synced_text and synced_text.startswith("http"):
            try:
                resp = requests.get(synced_text, headers=self.provider.headers, timeout=5)
                if resp.status_code == 200:
                    synced_text = resp.content.decode("utf-8", errors="replace").lstrip("\ufeff")
                else:
                    synced_text = None
            except Exception as e:
                print(f"[SearchDialog Fetch LRC Error] {e}")
                synced_text = None

        duration = 210.0
        if self.parent() and hasattr(self.parent(), "current_media_state") and self.parent().current_media_state:
            if self.parent().current_media_state.duration > 30.0:
                duration = self.parent().current_media_state.duration

        parsed_lines = []
        if synced_text:
            parsed_lines = self.provider.parse_lrc(synced_text, duration=duration)
        elif plain_text:
            parsed_lines = self.provider.parse_lrc(plain_text, duration=duration)

        formatted_data = {
            "title": item_data.get("trackName"),
            "artist": item_data.get("artistName"),
            "synced": True,
            "lines": parsed_lines,
            "raw_lrc": synced_text or plain_text,
            "source": f"Manual Search ({item_data.get('source', 'Online')})"
        }

        # Cache with current video title if found via YouTube URL
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

        formatted_data = {
            "title": self.clean_query or "Custom Song",
            "artist": "Custom",
            "synced": True,
            "lines": parsed_lines,
            "raw_lrc": text,
            "source": "Custom Paste"
        }

        # Cache custom lyrics locally so next time it auto loads
        if self.provider.cache and self.clean_query:
            self.provider.cache.set(self.clean_query, "", formatted_data)

        self.lyric_selected.emit(formatted_data)
        QMessageBox.information(self, "Thành công", "Đã phân bổ thời gian & lưu lời bài hát thủ công cho bài hát này!")
        self.accept()
