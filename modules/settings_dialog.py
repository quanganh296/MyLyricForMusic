from modules.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QDoubleSpinBox, QSlider, QPushButton, QGroupBox, QFormLayout,
    Qt, Signal, QTabWidget, QWidget, QColorDialog, QColor
)
from modules.icon_factory import IconFactory
from modules.i18n import APP_LANGUAGES, TRANSLATE_TARGET_LANGUAGES, tr

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

    TRANSLATE_LANGUAGES = TRANSLATE_TARGET_LANGUAGES

    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.initial_settings = current_settings.copy()
        self.settings = current_settings.copy()
        self.app_lang = self.settings.get("app_lang", "vi")
        self.setWindowTitle(tr(self.app_lang, "settings_title"))
        self.setFixedSize(600, 650)
        
        # Synchronize Settings Dialog opacity with current background opacity
        curr_op = float(self.settings.get("bg_opacity", 0.75))
        self.setWindowOpacity(max(0.15, curr_op))

        self.setup_ui()
        self._apply_dialog_language(self.app_lang)

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
        self.group_font = QGroupBox("Phông chữ & Màu sắc Lyric")
        form_font = QFormLayout(self.group_font)
        form_font.setSpacing(10)

        # Font Family
        self.combo_font = QComboBox()
        self.combo_font.addItems([
            "Segoe UI", "Arial", "Roboto", "Tahoma", "Verdana",
            "Yu Gothic UI", "Malgun Gothic", "Microsoft YaHei UI", "Impact", "Consolas"
        ])
        self.combo_font.setCurrentText(self.settings.get("font_family", "Segoe UI"))
        self.lbl_font = QLabel("Phông chữ:")
        form_font.addRow(self.lbl_font, self.combo_font)

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

        self.lbl_font_size = QLabel("Kích thước chữ:")
        form_font.addRow(self.lbl_font_size, size_layout)

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
            ("Rose", "#f43f5e"),
            ("Emerald", "#10b981"),
            ("Amber", "#f59e0b"),
            ("Yellow", "#fde047"),
            ("Purple", "#c084fc"),
            ("Orange", "#ff7849"),
            ("White", "#ffffff")
        ]

        for name, hex_code in color_pills:
            btn_c = QPushButton()
            btn_c.setFixedSize(22, 22)
            btn_c.setToolTip(name)
            btn_c.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_c.setStyleSheet(f"background-color: {hex_code}; border: 1px solid #52525b; border-radius: 11px;")
            btn_c.clicked.connect(lambda checked, h=hex_code: self.set_lyric_color(h))
            color_layout.addWidget(btn_c)

        self.btn_custom_color = QPushButton(" Bảng màu...")
        self.btn_custom_color.setIcon(IconFactory.create_icon("palette", "#38bdf8"))
        self.btn_custom_color.setObjectName("PresetBtn")
        self.btn_custom_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_custom_color.clicked.connect(self.choose_custom_color)
        color_layout.addWidget(self.btn_custom_color)

        self.lbl_main_color = QLabel("Màu chữ lyric chính:")
        form_font.addRow(self.lbl_main_color, color_layout)

        # Color Theme Presets
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(list(self.THEMES.keys()))
        current_theme = self.settings.get("theme_name", "Cyan Blue (Mặc định)")
        if current_theme in self.THEMES:
            self.combo_theme.setCurrentText(current_theme)
        self.combo_theme.currentTextChanged.connect(self.on_theme_combo_changed)
        self.lbl_theme = QLabel("Bộ chủ đề sẵn có:")
        form_font.addRow(self.lbl_theme, self.combo_theme)

        t1_layout.addWidget(self.group_font)

        # Window Transparency / Opacity Group
        self.group_opacity = QGroupBox("Độ trong suốt ứng dụng")
        op_v_layout = QVBoxLayout(self.group_opacity)
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
        self.op_preset_btns = []
        for key, val in [("op_25", 25), ("op_50", 50), ("op_75", 75), ("op_100", 100)]:
            btn_op = QPushButton(tr(self.app_lang, key))
            btn_op.setObjectName("PresetBtn")
            btn_op.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_op.clicked.connect(lambda checked, v=val: self.slider_opacity.setValue(v))
            op_presets_layout.addWidget(btn_op)
            self.op_preset_btns.append((key, btn_op))

        op_v_layout.addLayout(op_presets_layout)

        self.lbl_op_desc = QLabel("")
        self.lbl_op_desc.setStyleSheet("color: #94a3b8; font-size: 11px; font-style: italic;")
        op_v_layout.addWidget(self.lbl_op_desc)

        self.slider_opacity.valueChanged.connect(self.on_opacity_slider_changed)
        t1_layout.addWidget(self.group_opacity)

        # Display Lines & Alignment Group
        self.group_lines = QGroupBox("Chế độ hiển thị & Căn lề")
        form_lines = QFormLayout(self.group_lines)
        form_lines.setSpacing(10)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["", "", ""])
        curr_mode = int(self.settings.get("display_mode", 1))
        self.combo_mode.setCurrentIndex(curr_mode - 1 if curr_mode in (1, 2, 3) else 0)
        self.lbl_display_mode = QLabel("Chế độ giao diện:")
        form_lines.addRow(self.lbl_display_mode, self.combo_mode)

        self.combo_lines = QComboBox()
        self.combo_lines.addItems(["", "", ""])
        self.combo_lines.setCurrentIndex(self.settings.get("line_mode", 1))
        self.lbl_line_mode = QLabel("Chế độ dòng (Mode 2):")
        form_lines.addRow(self.lbl_line_mode, self.combo_lines)

        self.combo_align = QComboBox()
        self.combo_align.addItems(["", "", ""])
        self.combo_align.setCurrentIndex(self.settings.get("align_mode", 0))
        self.lbl_align_mode = QLabel("Căn lề (Mode 2):")
        form_lines.addRow(self.lbl_align_mode, self.combo_align)

        t1_layout.addWidget(self.group_lines)
        self.tabs.addTab(tab_visual, IconFactory.create_icon("palette", "#38bdf8"), tr(self.app_lang, "tab_visual"))

        # =========================================================
        # TAB 2: Đồng bộ thời gian (Time Sync & Offset)
        # =========================================================
        tab_sync = QWidget()
        t2_layout = QVBoxLayout(tab_sync)
        t2_layout.setSpacing(12)
        t2_layout.setContentsMargins(12, 14, 12, 14)

        self.group_sync = QGroupBox("Độ lệch thời gian")
        form_sync = QFormLayout(self.group_sync)
        form_sync.setSpacing(12)

        offset_layout = QHBoxLayout()
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-10.0, 10.0)
        self.spin_offset.setSingleStep(0.1)
        self.spin_offset.setSuffix(tr(self.app_lang, "sec_suffix"))
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

        self.lbl_offset = QLabel("Độ lệch lời:")
        form_sync.addRow(self.lbl_offset, offset_layout)
        t2_layout.addWidget(self.group_sync)

        self.lbl_sync_info = QLabel("")
        self.lbl_sync_info.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        self.lbl_sync_info.setWordWrap(True)
        t2_layout.addWidget(self.lbl_sync_info)
        t2_layout.addStretch()

        self.tabs.addTab(tab_sync, IconFactory.create_icon("clock", "#38bdf8"), tr(self.app_lang, "tab_sync"))

        # =========================================================
        # TAB 3: Ngôn ngữ ứng dụng & Dịch lời (App Language & Translation)
        # =========================================================
        tab_lang = QWidget()
        t3_layout = QVBoxLayout(tab_lang)
        t3_layout.setSpacing(12)
        t3_layout.setContentsMargins(12, 14, 12, 14)

        # Group A: App Interface Language (Tiếng Việt, English, 日本語, 中文, 한국어, ภาษาไทย, Español, Français)
        self.group_app_lang = QGroupBox("Ngôn ngữ ứng dụng (App Language)")
        form_app_lang = QFormLayout(self.group_app_lang)
        form_app_lang.setSpacing(10)

        self.combo_app_lang = QComboBox()
        selected_app_idx = 0
        for idx_al, (al_label, al_code) in enumerate(APP_LANGUAGES):
            self.combo_app_lang.addItem(al_label, al_code)
            if al_code == self.app_lang:
                selected_app_idx = idx_al
        self.combo_app_lang.setCurrentIndex(selected_app_idx)
        self.combo_app_lang.currentIndexChanged.connect(self.on_app_lang_changed)
        self.lbl_app_lang = QLabel("Ngôn ngữ hiển thị:")
        form_app_lang.addRow(self.lbl_app_lang, self.combo_app_lang)
        t3_layout.addWidget(self.group_app_lang)

        # Group B: Automatic Lyric Translation
        self.group_trans = QGroupBox("Dịch lời bài hát tự động")
        form_trans = QFormLayout(self.group_trans)
        form_trans.setSpacing(12)

        self.combo_translate_enable = QComboBox()
        self.combo_translate_enable.addItems(["", ""])
        trans_enabled = bool(self.settings.get("enable_translation", True))
        self.combo_translate_enable.setCurrentIndex(0 if trans_enabled else 1)
        self.lbl_trans_mode = QLabel("Chế độ dịch lời:")
        form_trans.addRow(self.lbl_trans_mode, self.combo_translate_enable)

        self.combo_romaji_enable = QComboBox()
        self.combo_romaji_enable.addItems(["", ""])
        romaji_enabled = bool(self.settings.get("enable_romanization", True))
        self.combo_romaji_enable.setCurrentIndex(0 if romaji_enabled else 1)
        self.combo_romaji_enable.setEnabled(trans_enabled)
        self.lbl_romaji = QLabel("Hiển thị phiên âm:")
        form_trans.addRow(self.lbl_romaji, self.combo_romaji_enable)

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
        self.lbl_trans_lang = QLabel("Dịch sang ngôn ngữ:")
        form_trans.addRow(self.lbl_trans_lang, self.combo_translate_lang)

        t3_layout.addWidget(self.group_trans)

        self.lbl_lang_info = QLabel("")
        self.lbl_lang_info.setStyleSheet(
            "color: #94a3b8; font-size: 12px; line-height: 1.45; "
            "font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;"
        )
        self.lbl_lang_info.setWordWrap(True)
        t3_layout.addWidget(self.lbl_lang_info)
        t3_layout.addStretch()

        self.tabs.addTab(tab_lang, IconFactory.create_icon("language", "#38bdf8"), tr(self.app_lang, "tab_lang"))

        layout.addWidget(self.tabs)

        # Bottom Action Buttons
        btn_box = QHBoxLayout()
        self.btn_save = QPushButton(" Lưu cài đặt")
        self.btn_save.setIcon(IconFactory.create_icon("save", "#09090b"))
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_and_close)
        btn_box.addWidget(self.btn_save)

        self.btn_cancel = QPushButton(" Hủy")
        self.btn_cancel.setIcon(IconFactory.create_icon("close", "#09090b"))
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

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

    def _apply_dialog_language(self, lang: str):
        """Re-translates all SettingsDialog tabs, group titles, labels, combos and buttons live."""
        self.app_lang = lang or "vi"
        self.setWindowTitle(tr(self.app_lang, "settings_title"))
        self.tabs.setTabText(0, tr(self.app_lang, "tab_visual"))
        self.tabs.setTabText(1, tr(self.app_lang, "tab_sync"))
        self.tabs.setTabText(2, tr(self.app_lang, "tab_lang"))

        self.group_font.setTitle(tr(self.app_lang, "grp_font"))
        self.lbl_font.setText(tr(self.app_lang, "lbl_font"))
        self.lbl_font_size.setText(tr(self.app_lang, "lbl_font_size"))
        self.lbl_main_color.setText(tr(self.app_lang, "lbl_main_color"))
        self.btn_custom_color.setText(tr(self.app_lang, "btn_palette"))
        self.lbl_theme.setText(tr(self.app_lang, "lbl_theme"))

        self.group_opacity.setTitle(tr(self.app_lang, "grp_opacity"))
        for key, btn in self.op_preset_btns:
            btn.setText(tr(self.app_lang, key))
        self.lbl_op_desc.setText(tr(self.app_lang, "op_tip"))

        self.group_lines.setTitle(tr(self.app_lang, "grp_mode"))
        self.lbl_display_mode.setText(tr(self.app_lang, "lbl_display_mode"))
        for idx, k in enumerate(("mode_opt_1", "mode_opt_2", "mode_opt_3")):
            self.combo_mode.setItemText(idx, tr(self.app_lang, k))
        self.lbl_line_mode.setText(tr(self.app_lang, "lbl_line_mode"))
        for idx, k in enumerate(("line_opt_1", "line_opt_2", "line_opt_3")):
            self.combo_lines.setItemText(idx, tr(self.app_lang, k))
        self.lbl_align_mode.setText(tr(self.app_lang, "lbl_align_mode"))
        for idx, k in enumerate(("align_opt_0", "align_opt_1", "align_opt_2")):
            self.combo_align.setItemText(idx, tr(self.app_lang, k))

        self.group_sync.setTitle(tr(self.app_lang, "grp_sync"))
        self.lbl_offset.setText(tr(self.app_lang, "lbl_offset"))
        self.spin_offset.setSuffix(tr(self.app_lang, "sec_suffix"))
        self.lbl_sync_info.setText(tr(self.app_lang, "sync_note"))

        self.group_app_lang.setTitle(tr(self.app_lang, "grp_app_lang"))
        self.lbl_app_lang.setText(tr(self.app_lang, "lbl_app_lang"))
        self.group_trans.setTitle(tr(self.app_lang, "grp_trans"))
        self.lbl_trans_mode.setText(tr(self.app_lang, "lbl_trans_mode"))
        self.combo_translate_enable.setItemText(0, tr(self.app_lang, "trans_opt_on"))
        self.combo_translate_enable.setItemText(1, tr(self.app_lang, "trans_opt_off"))
        self.lbl_romaji.setText(tr(self.app_lang, "lbl_romaji"))
        self.combo_romaji_enable.setItemText(0, tr(self.app_lang, "romaji_opt_on"))
        self.combo_romaji_enable.setItemText(1, tr(self.app_lang, "romaji_opt_off"))
        self.lbl_trans_lang.setText(tr(self.app_lang, "lbl_trans_lang"))
        self.lbl_lang_info.setText(tr(self.app_lang, "lang_note"))

        self.btn_save.setText(tr(self.app_lang, "btn_save"))
        self.btn_cancel.setText(tr(self.app_lang, "btn_cancel"))

    def on_app_lang_changed(self, _index: int):
        new_lang = self.combo_app_lang.currentData() or "vi"
        self.settings["app_lang"] = new_lang
        self._apply_dialog_language(new_lang)
        if self.parent() and hasattr(self.parent(), "apply_settings"):
            self.parent().apply_settings(self.settings)

    def save_and_close(self):
        theme_name = self.combo_theme.currentText()
        self.settings["font_family"] = self.combo_font.currentText()
        self.settings["font_size"] = self.spin_size.value()
        self.settings["theme_name"] = theme_name
        self.settings["color_highlight"] = self.curr_color_hex
        self.settings["color_sub"] = "#ffffff"
        self.settings["bg_opacity"] = max(0.15, self.slider_opacity.value() / 100.0)
        self.settings["display_mode"] = self.combo_mode.currentIndex() + 1
        self.settings["line_mode"] = self.combo_lines.currentIndex()
        self.settings["align_mode"] = self.combo_align.currentIndex()
        self.settings["sync_offset"] = self.spin_offset.value()
        self.settings["app_lang"] = self.combo_app_lang.currentData() or "vi"
        self.settings["enable_translation"] = (self.combo_translate_enable.currentIndex() == 0)
        self.settings["enable_romanization"] = (self.combo_romaji_enable.currentIndex() == 0)
        self.settings["translate_lang"] = self.combo_translate_lang.currentData() or "vi"

        self.settings_changed.emit(self.settings)
        self.accept()
