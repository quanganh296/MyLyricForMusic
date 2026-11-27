import re
from modules.qt_compat import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    Qt, Signal, QPoint, QRect, QRectF, QTimer, QPainter, QColor, QPen, QApplication
)
try:
    from PyQt6.QtCore import QEvent
except ImportError:
    from PySide6.QtCore import QEvent
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
    """
    Clickable bottom-left Bluetooth / Audio Output pill that opens the slide-up output selector.
    Emits clicked strictly on mouseReleaseEvent (matching QPushButton semantics) so opening the
    selector NEVER interrupts an in-progress mouse press/capture on Windows!
    """
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            was_pressed = self._pressed
            self._pressed = False
            if was_pressed and self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._pressed = False
        super().leaveEvent(event)


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
    Sleek dark-glass slide-up selector anchored above the bottom-left audio/BT pill.
    Uses Qt.WindowType.Tool (NO Qt.WindowType.Popup OS mouse-grab!) and internal painter alpha
    (NO Win32 setWindowOpacity animation on layered translucent windows!) so dismissing by
    clicking anywhere outside NEVER freezes hover cursors or breaks overlay clicks!
    """
    device_selected = Signal(str)
    closed = Signal()

    def __init__(self, devices: list, accent_hex: str = "#38bdf8", app_lang: str = "vi", parent=None):
        super().__init__(parent)
        self.accent_hex = accent_hex or "#38bdf8"
        self.app_lang = app_lang or "vi"
        self._dismissed = False
        self._filter_installed = False
        self._render_opacity = 1.0

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._anim_step = 0
        self._anim_total = 10  # ~160ms smooth 60 FPS slide-up
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

    def _install_dismiss_filter(self):
        app = QApplication.instance()
        if app and not self._filter_installed:
            app.installEventFilter(self)
            self._filter_installed = True

    def _remove_dismiss_filter(self):
        app = QApplication.instance()
        if app and self._filter_installed:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
            self._filter_installed = False

    def dismiss(self):
        """Cleanly closes the popup without grabbing mouse or breaking parent hover/cursor state."""
        if self._dismissed:
            return
        self._dismissed = True
        if hasattr(self, "_anim_timer") and self._anim_timer:
            self._anim_timer.stop()
        self._remove_dismiss_filter()
        self.closed.emit()
        self.close()

    def _on_row_chosen(self, dev_id: str):
        self.device_selected.emit(dev_id)
        self.dismiss()

    def eventFilter(self, watched, event):
        if self._dismissed or not self.isVisible():
            return False
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress:
            try:
                gpos = event.globalPosition().toPoint()
            except Exception:
                return False
            if not self.frameGeometry().contains(gpos):
                # Consume this single outside dismiss click inside our app so clicking the video
                # pane to close the popup never accidentally pauses playback or drags the window!
                self.dismiss()
                return True
        elif etype == QEvent.Type.ApplicationDeactivate:
            self.dismiss()
        elif etype == QEvent.Type.KeyPress:
            try:
                if event.key() == Qt.Key.Key_Escape:
                    self.dismiss()
                    return True
            except Exception:
                pass
        return False

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            # Delay 40ms so clicking a child row inside this popup finishes cleanly before auto-dismiss
            QTimer.singleShot(40, self._check_deactivate_dismiss)

    def _check_deactivate_dismiss(self):
        if self._dismissed or not self.isVisible():
            return
        if not self.isActiveWindow():
            self.dismiss()

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
        self._dismissed = False
        self._install_dismiss_filter()

        if not animate:
            self._render_opacity = 1.0
            self.move(target_x, target_y)
            self.show()
            self.raise_()
            self.activateWindow()
            return

        self._start_y = target_y + 18
        self._anim_step = 0
        self._render_opacity = 0.25
        self.move(target_x, self._start_y)
        self.show()
        self.raise_()
        self.activateWindow()
        self._anim_timer.start()

    def _tick_slide_up(self):
        self._anim_step += 1
        raw_t = min(1.0, self._anim_step / float(self._anim_total))
        ease = 1.0 - (1.0 - raw_t) ** 3
        cur_y = int(round(self._start_y + (self._target_y - self._start_y) * ease))
        self.move(self._target_x, cur_y)
        self._render_opacity = min(1.0, 0.25 + 0.75 * ease)
        self.update()
        if raw_t >= 1.0:
            self._anim_timer.stop()
            self.move(self._target_x, self._target_y)
            self._render_opacity = 1.0
            self.update()

    def hideEvent(self, event):
        if hasattr(self, "_anim_timer") and self._anim_timer:
            self._anim_timer.stop()
        self._remove_dismiss_filter()
        super().hideEvent(event)

    def closeEvent(self, event):
        if hasattr(self, "_anim_timer") and self._anim_timer:
            self._anim_timer.stop()
        self._remove_dismiss_filter()
        if not self._dismissed:
            self._dismissed = True
            self.closed.emit()
        super().closeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._render_opacity < 0.995:
            painter.setOpacity(self._render_opacity)

        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        painter.setBrush(QColor(15, 20, 34, 245))
        border_c = QColor(self.accent_hex)
        if not border_c.isValid():
            border_c = QColor("#38bdf8")
        border_c.setAlpha(115)
        painter.setPen(QPen(border_c, 1.2))
        painter.drawRoundedRect(rect, 12.0, 12.0)
        painter.end()
