import re
from modules.qt_compat import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    Qt, Signal, QPoint, QRect, QRectF, QTimer, QPainter, QColor, QPen, QApplication
)
from modules.icon_factory import IconFactory
from modules.i18n import tr


def _split_device_label(friendly_name: str):
    """Splits Windows endpoint name like 'Speakers (Realtek(R) Audio)' into (primary, subtitle)."""
    name = (friendly_name or "").strip()
    m = re.match(r'^([^\(]+?)\s*\((.+)\)\s*$', name)
    if m:
        head = m.group(1).strip()
        tail = m.group(2).strip()
        # For Bluetooth headphones like 'Headphones (AW-CURVE 300)', highlight the device model name!
        head_low = head.lower()
        if any(k in head_low for k in ("headphone", "headset", "earphone", "tai nghe")):
            return tail, head
        return head, tail
    return name, ""


class ClickableAudioPill(QFrame):
    """Clickable bottom-left Bluetooth / Audio Output pill that opens the slide-up output selector."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class AudioDeviceRow(QPushButton):
    """Single clickable row inside the slide-up AudioOutputPopup."""
    device_chosen = Signal(str)

    def __init__(self, dev_info: dict, accent_hex: str, app_lang: str, parent=None):
        super().__init__(parent)
        self.dev_id = dev_info.get("id", "")
        self.is_default = bool(dev_info.get("is_default", False))
        self.kind = dev_info.get("kind", "speaker")
        self.accent_hex = accent_hex or "#38bdf8"

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self.setFlat(True)

        primary, subtitle = _split_device_label(dev_info.get("name", ""))
        if not subtitle:
            if self.kind == "bluetooth":
                subtitle = tr(app_lang, "audio_kind_bt")
            elif self.kind == "headphones":
                subtitle = tr(app_lang, "audio_kind_hp")
            else:
                subtitle = tr(app_lang, "audio_kind_spk")

        row_lay = QHBoxLayout(self)
        row_lay.setContentsMargins(10, 6, 10, 6)
        row_lay.setSpacing(10)

        # Device icon (Bluetooth / Headphones vs System Speaker)
        icon_key = "headphones" if self.kind in ("bluetooth", "headphones") else "volume"
        ic_color = self.accent_hex if self.is_default else "#cbd5e1"
        lbl_ic = QLabel()
        lbl_ic.setPixmap(IconFactory.create_pixmap(icon_key, ic_color, 16))
        lbl_ic.setFixedSize(20, 20)
        lbl_ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row_lay.addWidget(lbl_ic)

        # Title + subtitle
        txt_col = QVBoxLayout()
        txt_col.setContentsMargins(0, 0, 0, 0)
        txt_col.setSpacing(1)

        lbl_main = QLabel(primary)
        lbl_main.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl_main.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {self.accent_hex if self.is_default else '#f8fafc'}; "
            "background: transparent; font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;"
        )
        lbl_sub = QLabel(subtitle)
        lbl_sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl_sub.setStyleSheet(
            "font-size: 10px; color: rgba(203, 213, 225, 0.75); background: transparent; "
            "font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;"
        )
        txt_col.addWidget(lbl_main)
        txt_col.addWidget(lbl_sub)
        row_lay.addLayout(txt_col, stretch=1)

        # Active indicator checkmark
        if self.is_default:
            lbl_chk = QLabel()
            lbl_chk.setPixmap(IconFactory.create_pixmap("check", self.accent_hex, 13))
            lbl_chk.setFixedSize(16, 16)
            lbl_chk.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            row_lay.addWidget(lbl_chk)

        active_bg = "rgba(255, 255, 255, 0.13)" if self.is_default else "transparent"
        active_border = f"1px solid {self.accent_hex}" if self.is_default else "1px solid transparent"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {active_bg};
                border: {active_border};
                border-radius: 8px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.18);
                border: 1px solid rgba(255, 255, 255, 0.28);
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 0.26);
            }}
        """)
        self.clicked.connect(lambda: self.device_chosen.emit(self.dev_id))


class AudioOutputPopup(QWidget):
    """
    Sleek dark-glass slide-up popup anchored above the bottom-left audio/BT pill.
    Lets the user instantly switch between Bluetooth headphones, PC speakers, or
    any active Windows audio render device without toggling Bluetooth!
    """
    device_selected = Signal(str)

    def __init__(self, devices: list, accent_hex: str = "#38bdf8", app_lang: str = "vi", parent=None):
        super().__init__(parent)
        self.accent_hex = accent_hex or "#38bdf8"
        self.app_lang = app_lang or "vi"

        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._anim_step = 0
        self._anim_total = 11  # ~176ms smooth 60 FPS slide-up
        self._start_y = 0
        self._target_y = 0
        self._target_x = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_slide_up)

        self._build_ui(devices)

    def _build_ui(self, devices: list):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(6)

        # Header row
        hdr = QHBoxLayout()
        hdr.setSpacing(6)
        ic_hdr = QLabel()
        ic_hdr.setPixmap(IconFactory.create_pixmap("volume", self.accent_hex, 13))
        ic_hdr.setFixedSize(16, 16)
        lbl_hdr = QLabel(tr(self.app_lang, "audio_out_title"))
        lbl_hdr.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #e2e8f0; background: transparent; "
            "font-family: 'Segoe UI', 'Yu Gothic UI', 'Malgun Gothic', 'Microsoft YaHei UI', sans-serif;"
        )
        hdr.addWidget(ic_hdr)
        hdr.addWidget(lbl_hdr, stretch=1)
        lay.addLayout(hdr)

        # Subtle divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background-color: rgba(255, 255, 255, 0.12); border: none;")
        lay.addWidget(div)

        if not devices:
            lbl_empty = QLabel(tr(self.app_lang, "audio_out_empty"))
            lbl_empty.setStyleSheet("font-size: 11px; color: #94a3b8; padding: 8px 4px; background: transparent;")
            lay.addWidget(lbl_empty)
            row_count = 1
        else:
            for dev in devices:
                row = AudioDeviceRow(dev, self.accent_hex, self.app_lang, self)
                row.device_chosen.connect(self._on_row_chosen)
                lay.addWidget(row)
            row_count = len(devices)

        pop_w = 292
        pop_h = min(380, 44 + row_count * 52 + 10)
        self.setFixedSize(pop_w, pop_h)

    def _on_row_chosen(self, dev_id: str):
        self.device_selected.emit(dev_id)
        self.close()

    def show_slide_up(self, anchor_global_top_left: QPoint, animate: bool = True):
        """Positions popup directly above anchor_global_top_left and slides it upward smoothly."""
        w, h = self.width(), self.height()
        target_x = anchor_global_top_left.x()
        target_y = anchor_global_top_left.y() - h - 8

        # Keep strictly inside the active screen geometry
        screen = QApplication.screenAt(anchor_global_top_left) or QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            target_x = max(sg.left() + 8, min(target_x, sg.right() - w - 8))
            if target_y < sg.top() + 8:
                # Fallback below anchor if window is jammed at the very top of screen
                target_y = min(sg.bottom() - h - 8, anchor_global_top_left.y() + 30)

        self._target_x = target_x
        self._target_y = target_y

        if not animate:
            self.setWindowOpacity(1.0)
            self.move(target_x, target_y)
            self.show()
            return

        self._start_y = target_y + 20
        self._anim_step = 0
        self.setWindowOpacity(0.05)
        self.move(target_x, self._start_y)
        self.show()
        self._anim_timer.start()

    def _tick_slide_up(self):
        self._anim_step += 1
        raw_t = min(1.0, self._anim_step / float(self._anim_total))
        ease = 1.0 - (1.0 - raw_t) ** 3
        cur_y = int(round(self._start_y + (self._target_y - self._start_y) * ease))
        self.move(self._target_x, cur_y)
        self.setWindowOpacity(min(1.0, 0.12 + 0.88 * ease))
        if raw_t >= 1.0:
            self._anim_timer.stop()
            self.move(self._target_x, self._target_y)
            self.setWindowOpacity(1.0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        painter.setBrush(QColor(15, 20, 34, 245))
        border_c = QColor(self.accent_hex)
        if not border_c.isValid():
            border_c = QColor("#38bdf8")
        border_c.setAlpha(115)
        painter.setPen(QPen(border_c, 1.2))
        painter.drawRoundedRect(rect, 12.0, 12.0)
        painter.end()

