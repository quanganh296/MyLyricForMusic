from modules.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QDoubleSpinBox, QSlider, QPushButton, QGroupBox, QFormLayout,
    Qt, Signal, QTabWidget, QWidget, QColorDialog, QColor
)
from modules.icon_factory import IconFactory

class SettingsDialog(QDialog):
    settings_changed = Signal(dict)

    THEMES = {
        "Cyan Blue (Mặc định)": {"highlight": "#38bdf8", "sub": "#ffffff"},
        "Rose Pink (Hồng neon)": {"highlight": "#f43f5e", "sub": "#ffffff"},
        "Emerald Green (Xanh lục)": {"highlight": "#10b981", "sub": "#ffffff"},
        "Neon Amber (Vàng kim)": {"highlight": "#f59e0b", "sub": "#ffffff"},
        "Purple Gold (Tím mộng mơ)": {"highlight": "#c084fc", "sub": "#ffffff"},
        "Crisp White (Trắng tinh)": {"highlight": "#ffffff", "sub": "#ffffff"}
    }

    TRANSLATE_LANGUAGES = [
        ("Tiếng Việt (Mặc định)", "vi"),
        ("English (Tiếng Anh)", "en"),
        ("日本語 (Tiếng Nhật)", "ja"),
        ("한국어 (Tiếng Hàn)", "ko"),
        ("中文 (Tiếng Trung)", "zh-CN"),
    ]

    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.initial_settings = current_settings.copy()
        self.settings = current_settings.copy()
        self.setWindowTitle("Cài đặt Lời bài hát Nổi - LyricNow")
        self.setFixedSize(590, 630)
        
        # Synchronize Settings Dialog opacity with current background opacity
        curr_op = float(self.settings.get("bg_opacity", 0.75))
        self.setWindowOpacity(max(0.15, curr_op))

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Tab Widget with Gray Interface
        self.tabs = QTabWidget()

        # =========================================================
        # TAB 1: Giao diện & Độ trong suốt (Visual & Transparency)
        # =========================================================
        tab_visual = QWidget()
        t1_layout = QVBoxLayout(tab_visual)
        t1_layout.setSpacing(12)
        t1_layout.setContentsMargins(12, 14, 12, 14)

        # Font & Style Group
        group_font = QGroupBox("Phông chữ & Màu sắc Lyric")
        form_font = QFormLayout(group_font)
        form_font.setSpacing(10)

        # Font Family
        self.combo_font = QComboBox()
        self.combo_font.addItems([
            "Segoe UI", "Arial", "Roboto", "Tahoma", "Verdana",
            "Yu Gothic UI", "Malgun Gothic", "Microsoft YaHei UI", "Impact", "Consolas"
        ])
        self.combo_font.setCurrentText(self.settings.get("font_family", "Segoe UI"))
        form_font.addRow("Phông chữ:", self.combo_font)

        # Font Size with quick presets
        size_layout = QHBoxLayout()
        self.spin_size = QSpinBox()
        self.spin_size.setRange(14, 54)
        self.spin_size.setSuffix(" px")
        self.spin_size.setValue(self.settings.get("font_size", 22))
        size_layout.addWidget(self.spin_size)

        for sz in [18, 22, 28, 36]:
            btn_sz = QPushButton(f"{sz}px")
            btn_sz.setObjectName("PresetBtn")
            btn_sz.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_sz.clicked.connect(lambda checked, s=sz: self.spin_size.setValue(s))
            size_layout.addWidget(btn_sz)

        form_font.addRow("Kích thước chữ:", size_layout)

        # Main Lyric Highlight Color Selection
        color_layout = QHBoxLayout()
        self.curr_color_hex = self.settings.get("color_highlight", "#38bdf8")
        
        self.btn_color_preview = QPushButton()
        self.btn_color_preview.setFixedSize(28, 24)
        self.btn_color_preview.setToolTip("Màu chữ lyric đang chọn")
        self.btn_color_preview.setStyleSheet(f"background-color: {self.curr_color_hex}; border: 2px solid #ffffff; border-radius: 4px;")
        
        color_layout.addWidget(self.btn_color_preview)

        # Preset Color Pills
        color_pills = [
            ("Cyan", "#38bdf8"),
            ("Hồng", "#f43f5e"),
            ("Xanh lá", "#10b981"),
            ("Vàng kim", "#f59e0b"),
            ("Vàng tươi", "#fde047"),
            ("Tím", "#c084fc"),
            ("Cam", "#ff7849"),
            ("Trắng", "#ffffff")
        ]

        for name, hex_code in color_pills:
            btn_c = QPushButton()
            btn_c.setFixedSize(22, 22)
            btn_c.setToolTip(f"Chọn màu {name}")
            btn_c.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_c.setStyleSheet(f"background-color: {hex_code}; border: 1px solid #52525b; border-radius: 11px;")
            btn_c.clicked.connect(lambda checked, h=hex_code: self.set_lyric_color(h))
            color_layout.addWidget(btn_c)

        btn_custom_color = QPushButton(" Bảng màu...")
        btn_custom_color.setIcon(IconFactory.create_icon("palette", "#38bdf8"))
        btn_custom_color.setObjectName("PresetBtn")
        btn_custom_color.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_custom_color.clicked.connect(self.choose_custom_color)
        color_layout.addWidget(btn_custom_color)

        form_font.addRow("Màu chữ lyric chính:", color_layout)

        # Color Theme Presets
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(list(self.THEMES.keys()))
        current_theme = self.settings.get("theme_name", "Cyan Blue (Mặc định)")
        if current_theme in self.THEMES:
            self.combo_theme.setCurrentText(current_theme)
        self.combo_theme.currentTextChanged.connect(self.on_theme_combo_changed)
        form_font.addRow("Bộ chủ đề sẵn có:", self.combo_theme)

        t1_layout.addWidget(group_font)

        # Window Transparency / Opacity Group
        group_opacity = QGroupBox("Độ trong suốt ứng dụng (Synchronized Opacity)")
        op_v_layout = QVBoxLayout(group_opacity)
        op_v_layout.setSpacing(8)

        op_slider_layout = QHBoxLayout()
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(15, 100)
        curr_op_pct = int(self.settings.get("bg_opacity", 0.75) * 100)
        self.slider_opacity.setValue(curr_op_pct)
        self.lbl_opacity_val = QLabel(f"{curr_op_pct}%")
        self.lbl_opacity_val.setStyleSheet("font-weight: bold; color: #38bdf8; font-size: 14px;")
        
        op_slider_layout.addWidget(self.slider_opacity)
        op_slider_layout.addWidget(self.lbl_opacity_val)
        op_v_layout.addLayout(op_slider_layout)

        # Quick Opacity Preset Buttons
        op_presets_layout = QHBoxLayout()
        presets = [
            ("25% (Rất mờ)", 25),
            ("50% (Mờ vừa)", 50),
            ("75% (Mặc định)", 75),
            ("100% (Đặc)", 100)
        ]
        for label, val in presets:
            btn_op = QPushButton(label)
            btn_op.setObjectName("PresetBtn")
            btn_op.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_op.clicked.connect(lambda checked, v=val: self.slider_opacity.setValue(v))
            op_presets_layout.addWidget(btn_op)

        op_v_layout.addLayout(op_presets_layout)

        lbl_op_desc = QLabel("Mẹo: Độ trong suốt sẽ được đồng bộ đồng thời cho cả Cửa sổ Lyric và Bảng Cài Đặt.")
        lbl_op_desc.setStyleSheet("color: #94a3b8; font-size: 11px; font-style: italic;")
        op_v_layout.addWidget(lbl_op_desc)

        self.slider_opacity.valueChanged.connect(self.on_opacity_slider_changed)
        t1_layout.addWidget(group_opacity)

        # Display Lines & Alignment Group
        group_lines = QGroupBox("Chế độ hiển thị & Căn lề")
        form_lines = QFormLayout(group_lines)
        form_lines.setSpacing(10)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems([
            "Mode 1: Video bên phải + Lyric bên trái (Nền mờ & Màu tự động)",
            "Mode 2: Chỉ hiện Lyric ở giữa (Nền mờ & Màu tự động theo video)"
        ])
        curr_mode = int(self.settings.get("display_mode", 1))
        self.combo_mode.setCurrentIndex(0 if curr_mode == 1 else 1)
        form_lines.addRow("Chế độ giao diện:", self.combo_mode)

        self.combo_lines = QComboBox()
        self.combo_lines.addItems(["1 Dòng (Gọn nhẹ)", "2 Dòng (Hiện tại & Tiếp theo)", "3 Dòng (Karaoke tiêu chuẩn)"])
        self.combo_lines.setCurrentIndex(self.settings.get("line_mode", 1))
        form_lines.addRow("Chế độ dòng (Mode 2):", self.combo_lines)

        self.combo_align = QComboBox()
        self.combo_align.addItems(["Căn giữa (Center)", "Căn trái (Left)", "Căn phải (Right)"])
        self.combo_align.setCurrentIndex(self.settings.get("align_mode", 0))
        form_lines.addRow("Căn lề (Mode 2):", self.combo_align)

        t1_layout.addWidget(group_lines)
        self.tabs.addTab(tab_visual, IconFactory.create_icon("palette", "#38bdf8"), "Giao diện & Mờ nền")

        # =========================================================
        # TAB 2: Đồng bộ thời gian (Time Sync & Offset)
        # =========================================================
        tab_sync = QWidget()
        t2_layout = QVBoxLayout(tab_sync)
        t2_layout.setSpacing(12)
        t2_layout.setContentsMargins(12, 14, 12, 14)

        group_sync = QGroupBox("Độ lệch thời gian (Time Sync Offset)")
        form_sync = QFormLayout(group_sync)
        form_sync.setSpacing(12)

        offset_layout = QHBoxLayout()
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-10.0, 10.0)
        self.spin_offset.setSingleStep(0.1)
        self.spin_offset.setSuffix(" giây")
        self.spin_offset.setValue(self.settings.get("sync_offset", 0.0))
        offset_layout.addWidget(self.spin_offset)

        for off_val, off_lbl in [(-1.0, "-1.0s"), (-0.5, "-0.5s"), (0.0, "0.0s"), (0.5, "+0.5s"), (1.0, "+1.0s")]:
            btn_off = QPushButton(off_lbl)
            btn_off.setObjectName("PresetBtn")
            btn_off.setCursor(Qt.CursorShape.PointingHandCursor)
            if off_val == 0.0:
                btn_off.clicked.connect(lambda: self.spin_offset.setValue(0.0))
            else:
                btn_off.clicked.connect(lambda checked, v=off_val: self.spin_offset.setValue(round(self.spin_offset.value() + v, 2)))
            offset_layout.addWidget(btn_off)

        form_sync.addRow("Độ lệch lời:", offset_layout)
        t2_layout.addWidget(group_sync)

        lbl_sync_info = QLabel(
            "Ghi chú Đồng bộ:\n"
            "- Bạn cũng có thể căn chỉnh trực tiếp bằng 2 nút Câu Trước / Câu Tiếp ngay trên cửa sổ nổi.\n"
            "- Độ lệch thời gian căn chỉnh sẽ tự động được lưu riêng cho từng bài hát."
        )
        lbl_sync_info.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        lbl_sync_info.setWordWrap(True)
        t2_layout.addWidget(lbl_sync_info)
        t2_layout.addStretch()

        self.tabs.addTab(tab_sync, IconFactory.create_icon("clock", "#38bdf8"), "Đồng bộ thời gian")

        # =========================================================
        # TAB 3: Ngôn ngữ & Dịch lời (Multilingual & Translation)
        # =========================================================
        tab_lang = QWidget()
        t3_layout = QVBoxLayout(tab_lang)
        t3_layout.setSpacing(12)
        t3_layout.setContentsMargins(12, 14, 12, 14)

        group_trans = QGroupBox("Dịch lời bài hát tự động (Dưới lời ngôn ngữ gốc)")
        form_trans = QFormLayout(group_trans)
        form_trans.setSpacing(12)

        self.combo_translate_enable = QComboBox()
        self.combo_translate_enable.addItems([
            "Bật — Tự nhận diện & dịch lời bài hát nước ngoài",
            "Tắt — Chỉ hiện lời ngôn ngữ gốc"
        ])
        trans_enabled = bool(self.settings.get("enable_translation", True))
        self.combo_translate_enable.setCurrentIndex(0 if trans_enabled else 1)
        form_trans.addRow("Chế độ dịch lời:", self.combo_translate_enable)

        self.combo_romaji_enable = QComboBox()
        self.combo_romaji_enable.addItems([
            "Bật — Hiện phiên âm (Romaji / Pinyin / Latin) ngay dưới lời gốc",
            "Tắt — Chỉ hiện lời gốc và lời đã dịch"
        ])
        romaji_enabled = bool(self.settings.get("enable_romanization", True))
        self.combo_romaji_enable.setCurrentIndex(0 if romaji_enabled else 1)
        self.combo_romaji_enable.setEnabled(trans_enabled)
        form_trans.addRow("Hiển thị phiên âm:", self.combo_romaji_enable)

        self.combo_translate_lang = QComboBox()
        curr_target = self.settings.get("translate_lang", "vi")
        selected_lang_idx = 0
        for idx_l, (lang_label, lang_code) in enumerate(self.TRANSLATE_LANGUAGES):
            self.combo_translate_lang.addItem(lang_label, lang_code)
            if lang_code == curr_target:
                selected_lang_idx = idx_l
        self.combo_translate_lang.setCurrentIndex(selected_lang_idx)
        self.combo_translate_lang.setEnabled(trans_enabled)
        self.combo_translate_enable.currentIndexChanged.connect(
            lambda idx: (
                self.combo_translate_lang.setEnabled(idx == 0),
                self.combo_romaji_enable.setEnabled(idx == 0),
            )
        )
        form_trans.addRow("Dịch sang ngôn ngữ:", self.combo_translate_lang)

        t3_layout.addWidget(group_trans)

        lbl_lang_info = QLabel(
            "Tự động nhận diện & hiển thị lời bài hát nước ngoài (Nhật, Hàn, Trung, Anh, Thái, Nga...):\n"
            "- Khi phát hiện bài hát nước ngoài có hệ chữ tượng hình (Nhật, Hàn, Trung, Thái, Nga...), "
            "app sẽ hiển thị chuẩn 3 tầng: Lời gốc -> Phiên âm (Romaji / Pinyin / Latin) -> Khoảng tách -> Bản dịch in đậm.\n"
            "- Với bài hát chữ Latin (Tiếng Anh, Pháp...), app tự ẩn dòng phiên âm và hiển thị Lời gốc + Bản dịch.\n"
            "- Nếu bài hát đã cùng ngôn ngữ dịch (VD: nhạc Việt khi dịch sang Tiếng Việt), app tự ẩn dòng dịch để tránh lặp chữ.\n"
            "- Mọi bản dịch & phiên âm được tải ngầm không gây lag và lưu vào bộ nhớ đệm cho các lần nghe sau."
        )
        lbl_lang_info.setStyleSheet(
            "color: #94a3b8; font-size: 12px; line-height: 1.45; "
            "font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;"
        )
        lbl_lang_info.setWordWrap(True)
        t3_layout.addWidget(lbl_lang_info)
        t3_layout.addStretch()

        self.tabs.addTab(tab_lang, IconFactory.create_icon("language", "#38bdf8"), "Ngôn ngữ & Dịch lời")

        layout.addWidget(self.tabs)

        # Bottom Action Buttons
        btn_box = QHBoxLayout()
        btn_save = QPushButton(" Lưu cài đặt")
        btn_save.setIcon(IconFactory.create_icon("save", "#09090b"))
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self.save_and_close)
        btn_box.addWidget(btn_save)

        btn_cancel = QPushButton(" Hủy")
        btn_cancel.setIcon(IconFactory.create_icon("close", "#09090b"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        layout.addLayout(btn_box)

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
            QGroupBox {
                color: #38bdf8;
                font-weight: bold;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLabel {
                color: #d4d4d8;
                font-size: 13px;
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #18181b;
                color: #f4f4f5;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 6px 10px;
                font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #3f3f46;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #38bdf8;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #38bdf8;
            }
            #PresetBtn {
                background-color: #18181b;
                color: #38bdf8;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            #PresetBtn:hover {
                background-color: #3f3f46;
                color: #ffffff;
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
        """)

    def set_lyric_color(self, hex_code: str):
        self.curr_color_hex = hex_code
        self.settings["color_highlight"] = hex_code
        self.btn_color_preview.setStyleSheet(f"background-color: {hex_code}; border: 2px solid #ffffff; border-radius: 4px;")
        if self.parent() and hasattr(self.parent(), "apply_settings"):
            self.parent().apply_settings(self.settings)

    def choose_custom_color(self):
        color = QColorDialog.getColor(QColor(self.curr_color_hex), self, "Chọn màu chữ lyric chính")
        if color.isValid():
            self.set_lyric_color(color.name())

    def on_theme_combo_changed(self, theme_name: str):
        if theme_name in self.THEMES:
            t = self.THEMES[theme_name]
            self.set_lyric_color(t["highlight"])

    def on_opacity_slider_changed(self, value: int):
        val_float = max(0.15, value / 100.0)
        self.lbl_opacity_val.setText(f"{value}%")
        self.settings["bg_opacity"] = val_float
        
        # Live window opacity synchronization for Settings Dialog itself
        self.setWindowOpacity(val_float)
        
        # Live window opacity synchronization for main Lyrics Overlay Window
        if self.parent() and hasattr(self.parent(), "apply_settings"):
            self.parent().apply_settings(self.settings)

    def reject(self):
        # Revert window opacity on both Settings Dialog and Overlay if canceled
        init_op = float(self.initial_settings.get("bg_opacity", 0.75))
        self.setWindowOpacity(max(0.15, init_op))
        if self.parent() and hasattr(self.parent(), "apply_settings"):
            self.parent().apply_settings(self.initial_settings)
        super().reject()

    def save_and_close(self):
        theme_name = self.combo_theme.currentText()
        self.settings["font_family"] = self.combo_font.currentText()
        self.settings["font_size"] = self.spin_size.value()
        self.settings["theme_name"] = theme_name
        self.settings["color_highlight"] = self.curr_color_hex
        self.settings["color_sub"] = "#ffffff"
        self.settings["bg_opacity"] = max(0.15, self.slider_opacity.value() / 100.0)
        self.settings["display_mode"] = 1 if self.combo_mode.currentIndex() == 0 else 2
        self.settings["line_mode"] = self.combo_lines.currentIndex()
        self.settings["align_mode"] = self.combo_align.currentIndex()
        self.settings["sync_offset"] = self.spin_offset.value()
        self.settings["enable_translation"] = (self.combo_translate_enable.currentIndex() == 0)
        self.settings["enable_romanization"] = (self.combo_romaji_enable.currentIndex() == 0)
        self.settings["translate_lang"] = self.combo_translate_lang.currentData() or "vi"

        self.settings_changed.emit(self.settings)
        self.accept()
