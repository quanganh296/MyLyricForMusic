from modules.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QDoubleSpinBox, QSlider, QPushButton, QGroupBox, QFormLayout,
    Qt, Signal, QTabWidget, QWidget, QColorDialog, QColor,
    QPainter, QPixmap, QRectF
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

        # Match main app's live blurred video/album background & adaptive accent color!
        self._bg_pixmap = QPixmap()
        self._cached_bg = QPixmap()
        self._cached_bg_size = None
        self._accent_hex = "#38bdf8"
        self._backdrop_connected = False

        if parent is not None:
            container = getattr(parent, "container", None)
            if container is not None and hasattr(container, "bg_pixmap") and not container.bg_pixmap.isNull():
                self._bg_pixmap = QPixmap(container.bg_pixmap)
            pal = getattr(parent, "adaptive_palette", None)
            if isinstance(pal, dict) and pal.get("accent_hex"):
                self._accent_hex = pal["accent_hex"]
            if hasattr(parent, "backdrop_updated"):
                try:
                    parent.backdrop_updated.connect(self.update_backdrop)
                    self._backdrop_connected = True
                except Exception:
                    pass

        # Synchronize Settings Dialog opacity with current background opacity
        curr_op = float(self.settings.get("bg_opacity", 0.75))
        self.setWindowOpacity(max(0.15, curr_op))

        self.setup_ui()
        self._apply_adaptive_stylesheet()
        self._apply_dialog_language(self.app_lang)

    def update_backdrop(self, pixmap, palette: dict = None):
        """Live-syncs Settings background & accent color whenever the main app switches song/artwork."""
        self._bg_pixmap = QPixmap(pixmap) if (pixmap is not None and not pixmap.isNull()) else QPixmap()
        self._cached_bg = QPixmap()
        self._cached_bg_size = None
        new_accent = (palette or {}).get("accent_hex") if isinstance(palette, dict) else None
        if new_accent and new_accent != self._accent_hex:
            self._accent_hex = new_accent
            self._apply_adaptive_stylesheet()
        self.update()

    def _disconnect_backdrop(self):
        if self._backdrop_connected and self.parent() is not None and hasattr(self.parent(), "backdrop_updated"):
            try:
                self.parent().backdrop_updated.disconnect(self.update_backdrop)
            except Exception:
                pass
        self._backdrop_connected = False

    def done(self, result: int):
        self._disconnect_backdrop()
        super().done(result)

    def closeEvent(self, event):
        self._disconnect_backdrop()
        super().closeEvent(event)

    def _ensure_cached_bg(self, w: int, h: int):
        if self._cached_bg_size == (w, h) and not self._cached_bg.isNull():
            return
        if self._bg_pixmap.isNull() or w <= 0 or h <= 0:
            self._cached_bg = QPixmap()
            return
        out = QPixmap(w, h)
        out.fill(QColor(15, 23, 42))
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scaled = self._bg_pixmap.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        sx = (scaled.width() - w) // 2
        sy = (scaled.height() - h) // 2
        p.drawPixmap(0, 0, scaled, sx, sy, w, h)
        # Subtle dark glass veil so every control stays razor-sharp over bright album art
        p.fillRect(QRectF(0, 0, w, h), QColor(10, 15, 28, 72))
        p.end()
        self._cached_bg = out
        self._cached_bg_size = (w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        if not self._bg_pixmap.isNull():
            self._ensure_cached_bg(w, h)
            if not self._cached_bg.isNull():
                painter.drawPixmap(0, 0, self._cached_bg)
                painter.end()
                return
        # Same deep slate glass base as main overlay when no track artwork is loaded
        painter.fillRect(0, 0, w, h, QColor(15, 23, 42))
        painter.end()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self.tabs = QTabWidget()

        # =========================================================
        # TAB 1: Giao diện & Độ trong suốt (Visual & Transparency)
        # =========================================================
        tab_visual = QWidget()
        tab_visual.setObjectName("TransparentTab")
        t1_layout = QVBoxLayout(tab_visual)
        t1_layout.setSpacing(12)
        t1_layout.setContentsMargins(12, 14, 12, 14)

        self.group_font = QGroupBox("Phông chữ & Màu sắc Lyric")
        form_font = QFormLayout(self.group_font)
        form_font.setSpacing(10)

        self.combo_font = QComboBox()
        self.combo_font.addItems([
            "Segoe UI", "Arial", "Roboto", "Tahoma", "Verdana",
            "Yu Gothic UI", "Malgun Gothic", "Microsoft YaHei UI", "Impact", "Consolas"
        ])
        self.combo_font.setCurrentText(self.settings.get("font_family", "Segoe UI"))
        self.lbl_font = QLabel("Phông chữ:")
        form_font.addRow(self.lbl_font, self.combo_font)

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

        color_layout = QHBoxLayout()
        self.curr_color_hex = self.settings.get("color_highlight", "#38bdf8")

        self.btn_color_preview = QPushButton()
        self.btn_color_preview.setFixedSize(28, 24)
        self.btn_color_preview.setToolTip("Màu chữ lyric đang chọn")
        self.btn_color_preview.setStyleSheet(f"background-color: {self.curr_color_hex}; border: 2px solid #ffffff; border-radius: 4px;")
        color_layout.addWidget(self.btn_color_preview)

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
            btn_c.setStyleSheet(f"background-color: {hex_code}; border: 1px solid rgba(255,255,255,0.45); border-radius: 11px;")
            btn_c.clicked.connect(lambda checked, h=hex_code: self.set_lyric_color(h))
            color_layout.addWidget(btn_c)

        self.btn_custom_color = QPushButton(" Bảng màu...")
        self.btn_custom_color.setIcon(IconFactory.create_icon("palette", "#ffffff"))
        self.btn_custom_color.setObjectName("PresetBtn")
        self.btn_custom_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_custom_color.clicked.connect(self.choose_custom_color)
        color_layout.addWidget(self.btn_custom_color)

        self.lbl_main_color = QLabel("Màu chữ lyric chính:")
        form_font.addRow(self.lbl_main_color, color_layout)

        self.combo_theme = QComboBox()
        self.combo_theme.addItems(list(self.THEMES.keys()))
        current_theme = self.settings.get("theme_name", "Cyan Blue (Mặc định)")
        if current_theme in self.THEMES:
            self.combo_theme.setCurrentText(current_theme)
        self.combo_theme.currentTextChanged.connect(self.on_theme_combo_changed)
        self.lbl_theme = QLabel("Bộ chủ đề sẵn có:")
        form_font.addRow(self.lbl_theme, self.combo_theme)

        t1_layout.addWidget(self.group_font)

        self.group_opacity = QGroupBox("Độ trong suốt ứng dụng")
        op_v_layout = QVBoxLayout(self.group_opacity)
        op_v_layout.setSpacing(8)

        op_slider_layout = QHBoxLayout()
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(15, 100)
        curr_op_pct = int(self.settings.get("bg_opacity", 0.75) * 100)
        self.slider_opacity.setValue(curr_op_pct)
        self.lbl_opacity_val = QLabel(f"{curr_op_pct}%")
        self.lbl_opacity_val.setObjectName("AccentValueLabel")

        op_slider_layout.addWidget(self.slider_opacity)
        op_slider_layout.addWidget(self.lbl_opacity_val)
        op_v_layout.addLayout(op_slider_layout)

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
        self.lbl_op_desc.setStyleSheet("color: rgba(226, 232, 240, 0.82); font-size: 11px; font-style: italic; background: transparent;")
        op_v_layout.addWidget(self.lbl_op_desc)

        self.slider_opacity.valueChanged.connect(self.on_opacity_slider_changed)
        t1_layout.addWidget(self.group_opacity)

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
        self.tabs.addTab(tab_visual, IconFactory.create_icon("palette", "#ffffff"), tr(self.app_lang, "tab_visual"))

        # =========================================================
        # TAB 2: Đồng bộ thời gian (Time Sync & Offset)
        # =========================================================
        tab_sync = QWidget()
        tab_sync.setObjectName("TransparentTab")
        t2_layout = QVBoxLayout(tab_sync)
        t2_layout.setSpacing(12)
        t2_layout.setContentsMargins(12, 14, 12, 14)

        self.group_sync = QGroupBox("Độ lệch thời gian")
        form_sync = QFormLayout(self.group_sync)
        form_sync.setSpacing(12)

        offset_layout = QHBoxLayout()
        self._offset_user_edited = False
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-120.0, 120.0)
        self.spin_offset.setSingleStep(0.1)
        self.spin_offset.setSuffix(tr(self.app_lang, "sec_suffix"))
        self.spin_offset.setValue(float(self.settings.get("sync_offset") or 0.0))
        self.spin_offset.valueChanged.connect(lambda _v: setattr(self, "_offset_user_edited", True))
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
        self.lbl_sync_info.setStyleSheet("color: rgba(226, 232, 240, 0.88); font-size: 12px; line-height: 1.4; background: transparent;")
        self.lbl_sync_info.setWordWrap(True)
        t2_layout.addWidget(self.lbl_sync_info)
        t2_layout.addStretch()

        self.tabs.addTab(tab_sync, IconFactory.create_icon("clock", "#ffffff"), tr(self.app_lang, "tab_sync"))

        # =========================================================
        # TAB 3: Ngôn ngữ ứng dụng & Dịch lời (App Language & Translation)
        # =========================================================
        tab_lang = QWidget()
        tab_lang.setObjectName("TransparentTab")
        t3_layout = QVBoxLayout(tab_lang)
        t3_layout.setSpacing(12)
        t3_layout.setContentsMargins(12, 14, 12, 14)

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
            "color: rgba(226, 232, 240, 0.88); font-size: 12px; line-height: 1.45; background: transparent; "
            "font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;"
        )
        self.lbl_lang_info.setWordWrap(True)
        t3_layout.addWidget(self.lbl_lang_info)
        t3_layout.addStretch()

        self.tabs.addTab(tab_lang, IconFactory.create_icon("language", "#ffffff"), tr(self.app_lang, "tab_lang"))

        layout.addWidget(self.tabs)

        # Bottom Action Buttons
        btn_box = QHBoxLayout()
        self.btn_save = QPushButton(" Lưu cài đặt")
        self.btn_save.setObjectName("PrimaryBtn")
        self.btn_save.setIcon(IconFactory.create_icon("save", "#09090b"))
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_and_close)
        btn_box.addWidget(self.btn_save)

        self.btn_cancel = QPushButton(" Hủy")
        self.btn_cancel.setObjectName("SecondaryBtn")
        self.btn_cancel.setIcon(IconFactory.create_icon("close", "#f8fafc"))
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        layout.addLayout(btn_box)

    def _apply_adaptive_stylesheet(self):
        accent = self._accent_hex or "#38bdf8"
        ac = QColor(accent)
        if not ac.isValid():
            accent = "#38bdf8"
            ac = QColor(accent)
        accent_hover = ac.lighter(115).name()

        # Refresh tab icons with adaptive accent tint
        if hasattr(self, "tabs"):
            self.tabs.setTabIcon(0, IconFactory.create_icon("palette", accent))
            self.tabs.setTabIcon(1, IconFactory.create_icon("clock", accent))
            self.tabs.setTabIcon(2, IconFactory.create_icon("language", accent))
        if hasattr(self, "btn_custom_color"):
            self.btn_custom_color.setIcon(IconFactory.create_icon("palette", accent))

        self.setStyleSheet(f"""
            QDialog {{
                background: transparent;
                color: #f1f5f9;
            }}
            #TransparentTab {{
                background: transparent;
            }}
            QTabWidget::pane {{
                border: 1px solid rgba(255, 255, 255, 0.20);
                border-radius: 10px;
                background-color: rgba(12, 18, 32, 0.56);
            }}
            QTabBar::tab {{
                background-color: rgba(12, 18, 32, 0.48);
                color: rgba(226, 232, 240, 0.80);
                padding: 9px 18px;
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
                margin-right: 4px;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-bottom: none;
            }}
            QTabBar::tab:hover {{
                background-color: rgba(255, 255, 255, 0.18);
                color: #ffffff;
            }}
            QTabBar::tab:selected {{
                background-color: rgba(12, 18, 32, 0.72);
                color: {accent};
                border-top: 3px solid {accent};
                border-left: 1px solid rgba(255, 255, 255, 0.22);
                border-right: 1px solid rgba(255, 255, 255, 0.22);
            }}
            QGroupBox {{
                background-color: rgba(10, 15, 28, 0.42);
                color: {accent};
                font-weight: bold;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 9px;
                margin-top: 10px;
                padding-top: 14px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                background: transparent;
            }}
            QLabel {{
                color: #f1f5f9;
                font-size: 13px;
                background: transparent;
            }}
            #AccentValueLabel {{
                font-weight: bold;
                color: {accent};
                font-size: 14px;
                background: transparent;
            }}
            QComboBox, QSpinBox, QDoubleSpinBox {{
                background-color: rgba(10, 15, 28, 0.68);
                color: #f8fafc;
                border: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 6px;
                padding: 6px 10px;
                font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;
            }}
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
                border: 1px solid {accent};
            }}
            QComboBox QAbstractItemView {{
                background-color: rgba(15, 23, 42, 0.96);
                color: #f8fafc;
                selection-background-color: {accent};
                selection-color: #09090b;
                border: 1px solid rgba(255, 255, 255, 0.22);
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: rgba(255, 255, 255, 0.22);
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {accent};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: #ffffff;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {accent};
            }}
            #PresetBtn {{
                background-color: rgba(10, 15, 28, 0.62);
                color: {accent};
                border: 1px solid rgba(255, 255, 255, 0.20);
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: bold;
            }}
            #PresetBtn:hover {{
                background-color: rgba(255, 255, 255, 0.20);
                color: #ffffff;
                border: 1px solid {accent};
            }}
            #PrimaryBtn {{
                background-color: {accent};
                color: #09090b;
                font-weight: bold;
                border: none;
                border-radius: 7px;
                padding: 9px 16px;
                font-size: 13px;
            }}
            #PrimaryBtn:hover {{
                background-color: {accent_hover};
            }}
            #SecondaryBtn {{
                background-color: rgba(255, 255, 255, 0.14);
                color: #f8fafc;
                font-weight: bold;
                border: 1px solid rgba(255, 255, 255, 0.24);
                border-radius: 7px;
                padding: 9px 16px;
                font-size: 13px;
            }}
            #SecondaryBtn:hover {{
                background-color: rgba(255, 255, 255, 0.26);
                color: #ffffff;
            }}
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

        self.setWindowOpacity(val_float)
        if self.parent() and hasattr(self.parent(), "apply_settings"):
            self.parent().apply_settings(self.settings)

    def reject(self):
        init_op = float(self.initial_settings.get("bg_opacity", 0.75))
        self.setWindowOpacity(max(0.15, init_op))
        if self.parent() and hasattr(self.parent(), "apply_settings"):
            self.parent().apply_settings(self.initial_settings)
        super().reject()

    def _apply_dialog_language(self, lang: str):
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
        if getattr(self, "_offset_user_edited", False):
            self.settings["sync_offset"] = self.spin_offset.value()
        self.settings["app_lang"] = self.combo_app_lang.currentData() or "vi"
        self.settings["enable_translation"] = (self.combo_translate_enable.currentIndex() == 0)
        self.settings["enable_romanization"] = (self.combo_romaji_enable.currentIndex() == 0)
        self.settings["translate_lang"] = self.combo_translate_lang.currentData() or "vi"

        self.settings_changed.emit(self.settings)
        self.accept()
