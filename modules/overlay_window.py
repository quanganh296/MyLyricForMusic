import os
import sys
import time
import requests
from modules.qt_compat import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsDropShadowEffect, QFrame, Qt, QPoint, QTimer, Signal,
    QColor, QFont, QFontMetrics, QCursor, QSizeGrip, QSlider, QIcon,
    QPainter, QPainterPath, QPen, QPixmap, QRectF, QRect, QSize, QSizePolicy
)
from modules.icon_factory import IconFactory
from modules.volume_manager import VolumeManager
from modules.theme_extractor import ThemeExtractor
from modules.video_player import RoundedVideoDisplay
from modules.lyrics_translator import TranslationWorker, has_non_latin_script
from modules.version import APP_VERSION
from modules.i18n import tr
from modules.karaoke_widgets import ModeDropdownButton, KaraokeLyricWidget, SplitTransitionStage, SongTitleOverlay
from modules.audio_output_popup import ClickableAudioPill, AudioOutputPopup


class ThemedGlassFrame(QFrame):
    """Main overlay container that paints either a cached blurred video backdrop (Mode 1) or dark glass (Mode 2)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bg_pixmap = QPixmap()
        self._cached_bg = QPixmap()
        self._cached_size = None
        self.use_blurred_bg = False
        self.corner_radius = 14.0
        self.border_qcolor = QColor(255, 255, 255, 45)

    def set_blurred_background(self, pixmap: QPixmap, border_hex: str = None):
        self.bg_pixmap = pixmap if pixmap else QPixmap()
        self._cached_bg = QPixmap()
        self._cached_size = None
        if border_hex:
            c = QColor(border_hex)
            if c.isValid():
                c.setAlpha(95)
                self.border_qcolor = c
        self.update()

    def set_blurred_mode(self, enabled: bool):
        self.use_blurred_bg = enabled
        self.update()

    def set_corner_radius(self, radius: float):
        if self.corner_radius != radius:
            self.corner_radius = radius
            self._cached_bg = QPixmap()
            self._cached_size = None
            self.update()

    def _ensure_cached_bg(self, w: int, h: int):
        if self._cached_size == (w, h) and not self._cached_bg.isNull():
            return
        if self.bg_pixmap.isNull() or w <= 0 or h <= 0:
            self._cached_bg = QPixmap()
            return
        # Pre-render scaled, cropped, rounded background ONCE per size/song change!
        out = QPixmap(w, h)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(0, 0, w, h)
        if self.corner_radius > 0:
            clip = QPainterPath()
            clip.addRoundedRect(rect, self.corner_radius, self.corner_radius)
            p.setClipPath(clip)

        scaled = self.bg_pixmap.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        sx = (scaled.width() - w) // 2
        sy = (scaled.height() - h) // 2
        p.drawPixmap(0, 0, scaled, sx, sy, w, h)

        if self.corner_radius > 0:
            p.setClipping(False)
            p.setPen(self.border_qcolor)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.corner_radius, self.corner_radius)
        p.end()

        self._cached_bg = out
        self._cached_size = (w, h)

    def paintEvent(self, event):
        if self.use_blurred_bg and not self.bg_pixmap.isNull():
            w, h = self.width(), self.height()
            self._ensure_cached_bg(w, h)
            if not self._cached_bg.isNull():
                painter = QPainter(self)
                painter.drawPixmap(0, 0, self._cached_bg)
                painter.end()
                return

        super().paintEvent(event)


class RoundVolumeSlider(QSlider):
    """Smooth custom-painted volume slider with a perfectly circular thumb and click-to-seek."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 100)
        self.setFixedHeight(22)
        self.setMinimumWidth(68)
        self.setMaximumWidth(86)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._hovered = False
        self._muted_visual = False
        self._accent_color = QColor("#ffffff")

    def set_visual_state(self, muted: bool = False, accent_hex: str = None):
        changed = (self._muted_visual != bool(muted))
        self._muted_visual = bool(muted)
        if accent_hex:
            c = QColor(accent_hex)
            if c.isValid() and c != self._accent_color:
                self._accent_color = c
                changed = True
        if changed:
            self.update()

    def _pos_to_value(self, x: float) -> int:
        pad = 8.0
        span = max(1.0, self.width() - 2.0 * pad)
        ratio = max(0.0, min(1.0, (x - pad) / span))
        return int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self.setValue(self._pos_to_value(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self._pos_to_value(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        cy = h / 2.0
        pad = 8.0
        track_h = 4.5
        track_w = max(1.0, w - 2.0 * pad)

        rng = max(1, self.maximum() - self.minimum())
        ratio = max(0.0, min(1.0, (self.value() - self.minimum()) / rng))
        knob_x = pad + ratio * track_w

        # Background groove capsule
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 65))
        painter.drawRoundedRect(QRectF(pad, cy - track_h / 2.0, track_w, track_h), track_h / 2.0, track_h / 2.0)

        # Active filled track capsule
        fill_w = max(0.0, knob_x - pad)
        if fill_w > 0.5:
            fill_color = QColor(255, 255, 255, 115) if self._muted_visual else QColor(self._accent_color)
            painter.setBrush(fill_color)
            painter.drawRoundedRect(QRectF(pad, cy - track_h / 2.0, fill_w, track_h), track_h / 2.0, track_h / 2.0)

        # Circular thumb with subtle shadow & hover expansion
        r = 7.2 if (self._hovered or self.isSliderDown()) else 6.2
        painter.setBrush(QColor(0, 0, 0, 75))
        painter.drawEllipse(QRectF(knob_x - r - 1.0, cy - r - 0.5, (r + 1.0) * 2.0, (r + 1.0) * 2.0))

        thumb_color = QColor(226, 232, 240, 210) if self._muted_visual else QColor("#ffffff")
        painter.setBrush(thumb_color)
        painter.drawEllipse(QRectF(knob_x - r, cy - r, r * 2.0, r * 2.0))
        painter.end()


class WindowCaptionButton(QPushButton):
    """
    Minimal Windows 11 style window caption button ('minimize', 'maximize', 'restore', 'close').
    Transparent at rest with clean thin-stroke vector icon; highlights smoothly on hover
    (solid red #e81123 with pure white X for 'close').
    """

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._hovered = False
        self._pressed = False
        self.setFixedSize(34, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")

    def set_kind(self, kind: str):
        if self._kind != kind:
            self._kind = kind
            self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        if self._kind == "close":
            if self._pressed:
                bg = QColor("#c50f1f")
            elif self._hovered:
                bg = QColor("#e81123")
            else:
                bg = None
        else:
            if self._pressed:
                bg = QColor(255, 255, 255, 58)
            elif self._hovered:
                bg = QColor(255, 255, 255, 36)
            else:
                bg = None

        if bg is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 5.0, 5.0)

        stroke_color = QColor("#ffffff") if (self._hovered or self._pressed) else QColor(228, 228, 231, 195)
        pen = QPen(stroke_color, 1.35 if (self._hovered or self._pressed) else 1.25)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        if self._kind == "minimize":
            painter.drawLine(int(cx - 5.0), int(cy), int(cx + 5.0), int(cy))
        elif self._kind == "maximize":
            painter.drawRoundedRect(QRectF(cx - 4.75, cy - 4.75, 9.5, 9.5), 1.2, 1.2)
        elif self._kind == "restore":
            # Front square + overlapping top-right back frame (exact Windows 11 restore icon)
            front = QRectF(cx - 5.2, cy - 3.2, 8.0, 8.0)
            painter.drawRoundedRect(front, 1.1, 1.1)
            back_path = QPainterPath()
            back_path.moveTo(cx - 3.0, cy - 3.2)
            back_path.lineTo(cx - 3.0, cy - 5.2)
            back_path.lineTo(cx + 4.8, cy - 5.2)
            back_path.lineTo(cx + 4.8, cy + 2.6)
            back_path.lineTo(cx + 2.8, cy + 2.6)
            painter.drawPath(back_path)
        elif self._kind == "close":
            d = 4.6
            painter.drawLine(QPoint(int(round(cx - d)), int(round(cy - d))), QPoint(int(round(cx + d)), int(round(cy + d))))
            painter.drawLine(QPoint(int(round(cx + d)), int(round(cy - d))), QPoint(int(round(cx - d)), int(round(cy + d))))

        painter.end()


class ToolbarIconButton(QPushButton):
    """
    Minimal borderless toolbar icon button: transparent at rest with subtle light-gray icon,
    highlights with a soft glass pill and crisp bright icon on hover.
    """

    def __init__(self, icon_name: str, normal_color: str = "#cbd5e1", hover_color: str = "#ffffff", icon_size: int = 13, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._normal_color = normal_color
        self._hover_color = hover_color
        self._icon_size = icon_size
        self._hovered = False
        self._pressed = False
        self.setFixedSize(28, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setObjectName("ToolIconBtn")
        self.setIconSize(QSize(icon_size, icon_size))
        self._refresh_icon()

    def set_icon_state(self, icon_name: str = None, normal_color: str = None, hover_color: str = None):
        if icon_name is not None:
            self._icon_name = icon_name
        if normal_color is not None:
            self._normal_color = normal_color
        if hover_color is not None:
            self._hover_color = hover_color
        self._refresh_icon()

    def _refresh_icon(self):
        col = self._hover_color if (self._hovered or self._pressed) else self._normal_color
        self.setIcon(IconFactory.create_icon(self._icon_name, col, self._icon_size))

    def enterEvent(self, event):
        self._hovered = True
        self._refresh_icon()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self._refresh_icon()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._refresh_icon()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self._refresh_icon()
        super().mouseReleaseEvent(event)


class LyricOverlayWindow(QWidget):
    request_settings = Signal()
    request_search = Signal()
    request_exit = Signal()
    settings_autosave = Signal(dict)

    BORDER_MARGIN = 8  # Pixel margin for edge resize cursor detection

    def __init__(self, settings: dict, media_listener, lyrics_provider):
        super().__init__()
        self.settings = settings
        self.media_listener = media_listener
        self.lyrics_provider = lyrics_provider
        self.volume_manager = VolumeManager()

        # Mode state: 1 = Video (Right) + Lyrics (Left) + Blurred BG + Adaptive Color
        #             2 = Lyric-Only Centered + Zoom In/Out & Resize
        #             3 = Karaoke (Word-by-Word highlight + toggleable Video with smooth slide transition)
        self.display_mode = int(self.settings.get("display_mode", 1))
        if self.display_mode not in (1, 2, 3):
            self.display_mode = 1
        self.karaoke_show_video = bool(self.settings.get("karaoke_show_video", True))
        self._karaoke_align_p = 1.0 if (self.display_mode == 3 and not self.karaoke_show_video) else 0.0

        # State variables
        self.is_locked = False
        self.is_compact = False
        self.is_fullscreen = False
        self._suppress_resize_save = False
        self.normal_mode1_geom = None
        self.drag_position = QPoint()
        self.active_edge = None
        self.press_geom = None
        self.press_global_pos = QPoint()

        self.current_media_state = None
        self.current_bt_state = None
        self.current_lyrics = None
        self.current_line_index = -1
        self.current_video_id = None
        self.current_thumb_bytes = None
        self._track_gen = 0
        self._current_video_req_key = None
        self._artwork_priority = 0  # 0=none, 1=valid GSMTC fallback, 2=YouTube HD artwork / video frame
        self._last_gsmtc_thumb_bytes = None
        self._prev_track_gsmtc_bytes = None
        self._dur_recheck_key = None
        self.adaptive_palette = ThemeExtractor.DEFAULT_PALETTE.copy()
        self.translation_worker = None
        self._old_trans_workers = []
        self.current_trans_req_key = None

        self.setup_window_flags()
        self.setup_ui()
        self.apply_settings(self.settings)
        self._apply_mode_layout(resize_window=False)

        # Sync timer for high-frequency lyric, karaoke wipe & video updating (25ms in Karaoke Mode, 50ms otherwise)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.update_lyric_display)
        self.sync_timer.start(25 if self.display_mode == 3 else 50)

        # Live Windows active audio output device & volume sync timer (450ms interval)
        self._last_vol_state = None
        self.vol_sync_timer = QTimer(self)
        self.vol_sync_timer.timeout.connect(self.sync_system_volume)
        self.vol_sync_timer.start(450)

    def setup_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setWindowTitle(f"LyricNow {APP_VERSION} - Lời Bài Hát Nổi")

        res_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ico_path = os.path.join(res_dir, "assets", "app_icon.ico")
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

    def closeEvent(self, event):
        if hasattr(self, "sync_timer") and self.sync_timer:
            self.sync_timer.stop()
        if hasattr(self, "vol_sync_timer") and self.vol_sync_timer:
            self.vol_sync_timer.stop()
        if self.translation_worker:
            self.translation_worker.cancel()
            self.translation_worker.wait(400)
            self.translation_worker = None
        for w in list(self._old_trans_workers):
            w.cancel()
            w.wait(200)
        self._old_trans_workers.clear()
        if hasattr(self, "video_display") and self.video_display:
            self.video_display.stop_video(clear_artwork=True)
            for r in list(getattr(self.video_display, "_old_resolvers", [])):
                r.cancel()
                r.wait(200)
        self.request_exit.emit()
        super().closeEvent(event)

    def setup_ui(self):
        if self.display_mode == 1:
            init_w = self.settings.get("mode1_w", 940)
            init_h = self.settings.get("mode1_h", 430)
        elif self.display_mode == 3:
            init_w = self.settings.get("mode3_w", self.settings.get("mode1_w", 940))
            init_h = self.settings.get("mode3_h", self.settings.get("mode1_h", 430))
        else:
            init_w = self.settings.get("win_w", 680)
            init_h = self.settings.get("win_h", 195)

        self.resize(init_w, init_h)
        self.move(self.settings.get("win_x", 350), self.settings.get("win_y", 120))

        # Outer Layout
        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(10, 10, 10, 10)

        # Main Glass / Blurred Container Frame (lightweight soft border painted in window paintEvent instead of CPU-heavy QGraphicsDropShadowEffect)
        self.container = ThemedGlassFrame(self)
        self.container.setObjectName("GlassContainer")
        self.container.setMouseTracking(True)
        self.shadow = None

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)

        # ---------------------------------------------------------
        # 1. Sleek Top Control & Mode Switcher Bar (Windows 11 Minimal Hover Style)
        # ---------------------------------------------------------
        self.top_bar = QHBoxLayout()
        self.top_bar.setSpacing(3)
        self.top_bar.addStretch(1)

        # Single Dropdown Mode Switcher (Mode 1: Video | Mode 2: Lyric | Mode 3: Karaoke)
        self.btn_mode_dropdown = ModeDropdownButton(self.container)
        self.btn_mode_dropdown.mode_selected.connect(self.set_display_mode)
        self.top_bar.addWidget(self.btn_mode_dropdown)

        # Mode 2 Zoom Out / Zoom In Controls
        self.btn_zoom_out = ToolbarIconButton("zoom_out", "#cbd5e1", "#ffffff")
        self.btn_zoom_out.setToolTip("Thu nhỏ chữ & cửa sổ (Ctrl + Cuộn chuột xuống)")
        self.btn_zoom_out.clicked.connect(lambda: self.zoom_lyrics(-2))

        self.btn_zoom_in = ToolbarIconButton("zoom_in", "#cbd5e1", "#ffffff")
        self.btn_zoom_in.setToolTip("Phóng to chữ & cửa sổ (Ctrl + Cuộn chuột lên)")
        self.btn_zoom_in.clicked.connect(lambda: self.zoom_lyrics(2))

        # Action Buttons (Borderless at rest, highlight on hover)
        init_tr = bool(self.settings.get("enable_translation", True))
        self.btn_translate = ToolbarIconButton("language", "#38bdf8" if init_tr else "#cbd5e1", "#7dd3fc" if init_tr else "#ffffff")
        self.btn_translate.setToolTip("Bật / Tắt dịch lời bài hát (hiện bản dịch bên dưới lời gốc)")
        self.btn_translate.clicked.connect(self.toggle_translation)

        self.btn_search = ToolbarIconButton("search", "#cbd5e1", "#ffffff")
        self.btn_search.setToolTip("Tìm kiếm lời nhạc thủ công hoặc theo URL YouTube")
        self.btn_search.clicked.connect(self.request_search.emit)

        self.btn_settings = ToolbarIconButton("settings", "#cbd5e1", "#ffffff")
        self.btn_settings.setToolTip("Cài đặt giao diện, chế độ hiển thị, ngôn ngữ dịch & độ lệch thời gian")
        self.btn_settings.clicked.connect(self.request_settings.emit)

        self.btn_lock = ToolbarIconButton("unlock", "#cbd5e1", "#ffffff")
        self.btn_lock.setToolTip("Khóa vị trí cửa sổ (Khóa để không bị kéo nhầm)")
        self.btn_lock.clicked.connect(self.toggle_lock)

        # Subtle vertical divider separating tools from Windows 11 window caption controls
        self.top_divider = QFrame()
        self.top_divider.setFixedSize(1, 14)
        self.top_divider.setStyleSheet("background-color: rgba(255, 255, 255, 0.16); border: none;")

        # Windows 11 Caption Controls: Minimize, Maximize/Restore/Compact, Close
        self.btn_minimize = WindowCaptionButton("minimize")
        self.btn_minimize.setToolTip("Thu nhỏ xuống thanh tác vụ")
        self.btn_minimize.clicked.connect(self.showMinimized)

        self.btn_fullscreen = WindowCaptionButton("maximize")
        self.btn_fullscreen.setToolTip("Phóng to toàn màn hình (F11) - Tắt độ mờ khi toàn màn hình")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)

        self.btn_compact = WindowCaptionButton("restore")
        self.btn_compact.setToolTip("Thu gọn / Mở rộng cửa sổ")
        self.btn_compact.clicked.connect(self.toggle_compact)

        self.btn_close = WindowCaptionButton("close")
        self.btn_close.setToolTip("Thoát ứng dụng (Exit App)")
        self.btn_close.clicked.connect(self.request_exit.emit)

        self.top_bar.addWidget(self.btn_zoom_out)
        self.top_bar.addWidget(self.btn_zoom_in)
        self.top_bar.addWidget(self.btn_translate)
        self.top_bar.addWidget(self.btn_search)
        self.top_bar.addWidget(self.btn_settings)
        self.top_bar.addWidget(self.btn_lock)
        self.top_bar.addSpacing(3)
        self.top_bar.addWidget(self.top_divider)
        self.top_bar.addSpacing(3)
        self.top_bar.addWidget(self.btn_minimize)
        self.top_bar.addWidget(self.btn_fullscreen)
        self.top_bar.addWidget(self.btn_compact)
        self.top_bar.addWidget(self.btn_close)

        layout.addLayout(self.top_bar)

        # ---------------------------------------------------------
        # 2. Main Animated Split Stage (Left/Center: Lyrics | Right: Video)
        # ---------------------------------------------------------
        self.lyrics_widget = QWidget()
        self.lyrics_widget.setMouseTracking(True)
        self.lyrics_box = QVBoxLayout(self.lyrics_widget)
        self.lyrics_box.setSpacing(3)
        self.lyrics_box.setContentsMargins(4, 2, 4, 2)

        self.lyrics_box.addStretch(1)

        self.lbl_prev2 = QLabel("")
        self.lbl_prev2.setObjectName("FarLyric")
        self.lbl_prev2.setWordWrap(True)

        self.lbl_prev = QLabel("")
        self.lbl_prev.setObjectName("PrevLyric")
        self.lbl_prev.setWordWrap(True)

        self.lbl_active = QLabel("Chờ bài hát từ YouTube, Spotify, Chrome, Edge...")
        self.lbl_active.setObjectName("ActiveLyric")
        self.lbl_active.setWordWrap(True)

        self.karaoke_widget = KaraokeLyricWidget(self.lyrics_widget)
        self.karaoke_widget.set_static_text("Chờ bài hát từ YouTube, Spotify, Chrome, Edge...")
        self.karaoke_widget.setVisible(False)

        self.lbl_active_romaji = QLabel("")
        self.lbl_active_romaji.setObjectName("ActiveRomaji")
        self.lbl_active_romaji.setWordWrap(True)
        self.lbl_active_romaji.setVisible(False)

        self.lbl_active_trans = QLabel("")
        self.lbl_active_trans.setObjectName("ActiveTransLyric")
        self.lbl_active_trans.setWordWrap(True)
        self.lbl_active_trans.setVisible(False)

        self.lbl_next = QLabel("")
        self.lbl_next.setObjectName("NextLyric")
        self.lbl_next.setWordWrap(True)

        self.lbl_next2 = QLabel("")
        self.lbl_next2.setObjectName("FarLyric")
        self.lbl_next2.setWordWrap(True)

        for lbl in (
            self.lbl_prev2, self.lbl_prev, self.lbl_active,
            self.lbl_active_romaji, self.lbl_active_trans,
            self.lbl_next, self.lbl_next2
        ):
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            lbl.setMinimumHeight(0)

        self.lyrics_box.addWidget(self.lbl_prev2)
        self.lyrics_box.addWidget(self.lbl_prev)
        self.lyrics_box.addWidget(self.lbl_active)
        self.lyrics_box.addWidget(self.karaoke_widget)
        self.lyrics_box.addWidget(self.lbl_active_romaji)
        self.lyrics_box.addWidget(self.lbl_active_trans)
        self.lyrics_box.addWidget(self.lbl_next)
        self.lyrics_box.addWidget(self.lbl_next2)
        self.lyrics_box.addStretch(1)

        # Right Video Pane (Mode 1 & Mode 3 Karaoke when Video is ON)
        self.video_display = RoundedVideoDisplay(self.container)
        self.video_display.clicked.connect(lambda: self.media_listener.send_control("play_pause") if self.media_listener else None)
        self.video_display.video_id_resolved.connect(self._on_video_id_resolved)
        self.video_display.artwork_ready.connect(self._on_hd_artwork_ready)
        self.video_display.video_frame_artwork_ready.connect(self._on_video_frame_artwork_ready)

        self.split_stage = SplitTransitionStage(self.lyrics_widget, self.video_display, self.container)
        self.split_stage.set_callbacks(
            on_progress=self._on_split_anim_progress,
            on_finish=self._on_split_anim_finished,
        )
        layout.addWidget(self.split_stage, stretch=1)

        # Floating "Video" toggle pill directly below the Mode dropdown (visible only in Mode 3 Karaoke)
        self.btn_karaoke_video = QPushButton(" Video", self.container)
        self.btn_karaoke_video.setObjectName("KaraokeVideoBtnActive")
        self.btn_karaoke_video.setIcon(IconFactory.create_icon("film", "#09090b", 12))
        self.btn_karaoke_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_karaoke_video.setToolTip("Bật / Tắt khung Video trong chế độ Karaoke")
        self.btn_karaoke_video.clicked.connect(self.toggle_karaoke_video)
        self.btn_karaoke_video.setVisible(False)
        self.btn_karaoke_video.raise_()

        # Floating animated Song Title (underneath Video when Video is visible; Top-Center above lyrics otherwise)
        self.lbl_song_info = SongTitleOverlay(self.container)
        self.lbl_song_info.setText("Đang chờ phát nhạc...")
        self.lbl_song_info.raise_()

        # ---------------------------------------------------------
        # 3. Media Controls Bar & Volume Control & Resizable Grip
        # ---------------------------------------------------------
        self.bottom_bar = QHBoxLayout()
        self.bottom_bar.setSpacing(10)

        self.btn_prev = QPushButton(" Câu Trước")
        self.btn_prev.setIcon(IconFactory.create_icon("prev", "#ffffff"))
        self.btn_prev.setToolTip("Chuyển về câu trước đó & tự động đồng bộ thời gian chuẩn vào YouTube")
        self.btn_prev.clicked.connect(self.jump_to_prev_line)

        self.btn_play = QPushButton(" Phát/Dừng")
        self.btn_play.setIcon(IconFactory.create_icon("play_pause", "#ffffff"))
        self.btn_play.setToolTip("Phát hoặc Tạm dừng nhạc YouTube / Windows")
        self.btn_play.clicked.connect(lambda: self.media_listener.send_control("play_pause") if self.media_listener else None)

        self.btn_next = QPushButton(" Câu Tiếp")
        self.btn_next.setIcon(IconFactory.create_icon("next", "#ffffff"))
        self.btn_next.setToolTip("Chuyển tới câu tiếp theo & tự động đồng bộ thời gian chuẩn vào YouTube")
        self.btn_next.clicked.connect(self.jump_to_next_line)

        for mbtn in [self.btn_prev, self.btn_play, self.btn_next]:
            mbtn.setCursor(Qt.CursorShape.PointingHandCursor)
            mbtn.setObjectName("MediaBtn")

        # Volume Controls (wrapped in a clean container so % label never overlaps slider in narrow Mode 2)
        self.vol_widget = QWidget()
        self.vol_widget.setObjectName("VolWidget")
        self.vol_container = QHBoxLayout(self.vol_widget)
        self.vol_container.setContentsMargins(0, 0, 0, 0)
        self.vol_container.setSpacing(6)

        self.btn_vol = QPushButton()
        self.btn_vol.setFixedSize(26, 24)
        self.btn_vol.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vol.setObjectName("IconBtn")
        self.btn_vol.setToolTip("Bật / Tắt tiếng âm lượng (Mute)")
        self.btn_vol.clicked.connect(self.toggle_volume_mute)

        self.slider_vol = RoundVolumeSlider(self.vol_widget)
        self.slider_vol.setObjectName("VolSlider")
        self.slider_vol.setToolTip("Kéo để tăng / giảm âm lượng thiết bị phát đang dùng")

        init_vol, init_muted, init_dev = self.volume_manager.get_state()
        self.slider_vol.setValue(init_vol)
        self.slider_vol.set_visual_state(muted=init_muted)

        self.lbl_vol_val = QLabel("Mute" if init_muted else f"{init_vol}%")
        self.lbl_vol_val.setStyleSheet("font-size: 11px; color: #ffffff; font-weight: bold; font-family: 'Segoe UI';")
        self.lbl_vol_val.setFixedWidth(36)
        self.lbl_vol_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.update_volume_icon(init_vol, init_muted)
        if init_dev:
            self.slider_vol.setToolTip(f"Thiết bị phát: {init_dev} ({init_vol}%)")
            self.btn_vol.setToolTip(f"Bật / Tắt tiếng — {init_dev}")
        self.slider_vol.valueChanged.connect(self.on_volume_slider_changed)

        self.vol_container.addWidget(self.btn_vol)
        self.vol_container.addWidget(self.slider_vol)
        self.vol_container.addWidget(self.lbl_vol_val)

        # Bluetooth Headphone Battery & Quick Audio Output Switcher Pill (click to slide up speaker/BT selector!)
        self._audio_popup = None
        self.bt_pill = ClickableAudioPill()
        self.bt_pill.setObjectName("BtPill")
        self.bt_pill.clicked.connect(self.toggle_audio_output_popup)
        bt_pill_layout = QHBoxLayout(self.bt_pill)
        bt_pill_layout.setContentsMargins(8, 3, 7, 3)
        bt_pill_layout.setSpacing(5)

        self.lbl_bt_icon = QLabel()
        self.lbl_bt_icon.setPixmap(IconFactory.create_pixmap("headphones", "#ffffff", 13))
        self.lbl_bt_icon.setFixedSize(14, 14)

        self.lbl_bt_batt_icon = QLabel()
        self.lbl_bt_batt_icon.setPixmap(IconFactory.create_pixmap("battery_full", "#4ade80", 14))
        self.lbl_bt_batt_icon.setFixedSize(16, 14)

        self.lbl_bt_text = QLabel("")
        self.lbl_bt_text.setObjectName("BtPillText")
        self.lbl_bt_text.setStyleSheet("font-size: 11px; color: #ffffff; font-weight: bold; font-family: 'Segoe UI';")

        self.lbl_bt_chevron = QLabel()
        self.lbl_bt_chevron.setPixmap(IconFactory.create_pixmap("chevron_up", "#cbd5e1", 9))
        self.lbl_bt_chevron.setFixedSize(10, 12)

        bt_pill_layout.addWidget(self.lbl_bt_icon)
        bt_pill_layout.addWidget(self.lbl_bt_batt_icon)
        bt_pill_layout.addWidget(self.lbl_bt_text)
        bt_pill_layout.addWidget(self.lbl_bt_chevron)
        self.bt_pill.setVisible(False)

        # App Version Label (Bottom-Left corner)
        self.lbl_version = QLabel(APP_VERSION)
        self.lbl_version.setObjectName("VersionLabel")
        self.lbl_version.setToolTip(f"Phiên bản ứng dụng: LyricNow {APP_VERSION}")
        self.lbl_version.setStyleSheet(
            "font-size: 10px; color: rgba(255, 255, 255, 0.58); "
            "font-weight: 600; font-family: 'Segoe UI', sans-serif; padding: 0 2px 1px 0;"
        )

        self.bottom_bar.addWidget(
            self.lbl_version,
            alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft
        )
        self.bottom_bar.addWidget(self.bt_pill)
        self.bottom_bar.addStretch()
        self.bottom_bar.addWidget(self.btn_prev)
        self.bottom_bar.addWidget(self.btn_play)
        self.bottom_bar.addWidget(self.btn_next)
        self.bottom_bar.addStretch()
        self.bottom_bar.addWidget(self.vol_widget)

        # Resizable handle (Bottom-Right Size Grip)
        self.size_grip = QSizeGrip(self.container)
        self.size_grip.setFixedSize(16, 16)
        self.bottom_bar.addWidget(self.size_grip, alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        layout.addLayout(self.bottom_bar)
        self.outer_layout.addWidget(self.container)

    # ---------------------------------------------------------
    # Mode 1, Mode 2 & Mode 3 (Karaoke) Switching + Animated Video Toggle
    # ---------------------------------------------------------
    def _position_karaoke_video_btn(self):
        if not hasattr(self, "btn_karaoke_video") or not hasattr(self, "btn_mode_dropdown"):
            return
        if self.display_mode != 3:
            self.btn_karaoke_video.setVisible(False)
            return
        g = self.btn_mode_dropdown.geometry()
        if g.width() <= 10:
            return
        btn_w = max(84, g.width())
        self.btn_karaoke_video.setGeometry(g.x(), g.y() + g.height() + 5, btn_w, 24)
        self.btn_karaoke_video.setVisible(True)
        self.btn_karaoke_video.raise_()

    def _apply_lyrics_top_margin(self):
        """Reserves exact vertical top margin for floating [Video] pill & top-centered song title."""
        if not hasattr(self, "lyrics_box"):
            return
        if self.is_compact:
            top_m = 2
        elif self.display_mode == 1:
            top_m = 2
        elif self.display_mode == 2:
            top_m = 28
        else:
            # Mode 3: Video ON reserves room for [Video] pill; Video OFF reserves [Video] pill + centered title
            top_m = 26 if self.karaoke_show_video else 58
        self.lyrics_box.setContentsMargins(4, top_m, 4, 2)

    def _compute_song_title_rect(self) -> QRect:
        """
        Computes exact destination geometry of the song title in container coordinates:
        - Video visible (Mode 1 or Mode 3 Video ON): centered directly underneath the 16:9 Video box.
        - Video hidden (Mode 2 or Mode 3 Video OFF): centered at the top above the lyrics.
        """
        cw = self.container.width()
        ch = self.container.height()
        if cw <= 40 or ch <= 40:
            return QRect()

        stage_g = self.split_stage.geometry()
        if stage_g.width() <= 40 or stage_g.height() <= 30:
            stage_g = QRect(16, 44, max(120, cw - 32), max(60, ch - 92))

        has_video = (self.display_mode == 1) or (self.display_mode == 3 and self.karaoke_show_video)
        if has_video:
            _, right_r, _ = self.split_stage._split_rects()
            vr = self.video_display.get_video_rect(right_r.width(), right_r.height())
            th = 28
            tx = stage_g.x() + right_r.x() + int(round(vr.x()))
            ty = stage_g.y() + right_r.y() + int(round(vr.y() + vr.height())) + 6
            tw = max(140, int(round(vr.width())))
            max_y = stage_g.y() + stage_g.height() - th
            if ty > max_y:
                ty = max(stage_g.y(), max_y)
            return QRect(tx, ty, tw, th)

        # No video -> Top-Center cleanly above the lyrics!
        th = 26
        tx = stage_g.x() + 12
        tw = max(160, stage_g.width() - 24)
        if self.display_mode == 3:
            kv_bottom = self.btn_karaoke_video.geometry().bottom() if self.btn_karaoke_video.isVisible() else (stage_g.y() + 21)
            ty = max(stage_g.y() + 25, kv_bottom + 6)
        else:
            ty = max(stage_g.y() - 2, 36)
        return QRect(tx, ty, tw, th)

    def _update_song_title_position(self, animate: bool = False):
        if not hasattr(self, "lbl_song_info"):
            return
        if self.is_compact:
            self.lbl_song_info.setVisible(False)
            return
        self.lbl_song_info.setVisible(True)
        target = self._compute_song_title_rect()
        if target.isValid() and target.width() > 4:
            self.lbl_song_info.move_to_rect(target, animate=animate)
            self.lbl_song_info.raise_()
            if self.btn_karaoke_video.isVisible():
                self.btn_karaoke_video.raise_()

    def _update_karaoke_video_btn_style(self, accent_hex: str = None):
        if not hasattr(self, "btn_karaoke_video"):
            return
        on = bool(self.karaoke_show_video)
        lang = self._lang()
        self.btn_karaoke_video.setObjectName("KaraokeVideoBtnActive" if on else "KaraokeVideoBtn")
        self.btn_karaoke_video.setIcon(IconFactory.create_icon("film", "#09090b" if on else "#f1f5f9", 12))
        self.btn_karaoke_video.setText(tr(lang, "btn_video"))
        self.btn_karaoke_video.setToolTip(
            tr(lang, "tip_karaoke_video_on" if on else "tip_karaoke_video_off")
        )
        self.btn_karaoke_video.style().unpolish(self.btn_karaoke_video)
        self.btn_karaoke_video.style().polish(self.btn_karaoke_video)

    def toggle_karaoke_video(self):
        if self.display_mode != 3:
            return
        self.karaoke_show_video = not self.karaoke_show_video
        self.settings["karaoke_show_video"] = self.karaoke_show_video
        self._update_karaoke_video_btn_style(self.adaptive_palette.get("accent_hex", "#38bdf8"))
        self._apply_lyrics_top_margin()
        if self.karaoke_show_video:
            self._trigger_track_media_load()
        # Animate video/lyrics AND glide song title simultaneously (under video <-> top center)!
        self.split_stage.set_video_visible(self.karaoke_show_video, animate=True)
        self._update_song_title_position(animate=True)
        self.settings_autosave.emit(self.settings)

    def _on_split_anim_progress(self, progress: float):
        self._karaoke_align_p = float(progress)
        if hasattr(self, "karaoke_widget"):
            self.karaoke_widget.set_align_progress(progress)
        if self.display_mode == 3:
            align_flags = (
                Qt.AlignmentFlag.AlignCenter
                if progress >= 0.72
                else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            )
            for lbl in (
                self.lbl_prev2, self.lbl_prev, self.lbl_active,
                self.lbl_active_romaji, self.lbl_active_trans,
                self.lbl_next, self.lbl_next2,
            ):
                if lbl.alignment() != align_flags:
                    lbl.setAlignment(align_flags)

    def _on_split_anim_finished(self, video_shown: bool):
        if not video_shown and self.display_mode != 1:
            # Stop MP4 video decoding AFTER fade-out animation completes to free CPU while preserving blurred backdrop
            self.video_display.stop_video(clear_artwork=False)
        self._position_karaoke_video_btn()
        if not getattr(self.lbl_song_info, "_animating", False):
            self._update_song_title_position(animate=False)
        self._fit_active_lyric_fonts()

    def set_display_mode(self, mode: int):
        mode = mode if mode in (1, 2, 3) else 1
        if mode == self.display_mode:
            return

        # Remember previous song-title geometry so it visibly glides to its new home (under video <-> top center)!
        prev_title_rect = QRect(self.lbl_song_info.geometry()) if hasattr(self, "lbl_song_info") else QRect()
        prev_has_video = (self.display_mode == 1) or (self.display_mode == 3 and self.karaoke_show_video)

        # Exit fullscreen before switching to Mode 2 (Modes 1 & 3 both support fullscreen)
        if self.is_fullscreen and mode == 2:
            self.toggle_fullscreen(force_exit=True)

        # Persist outgoing mode dimensions
        if self.display_mode == 1:
            if not self.is_fullscreen:
                self.settings["mode1_w"] = self.width()
                self.settings["mode1_h"] = self.height()
        elif self.display_mode == 3:
            if not self.is_fullscreen:
                self.settings["mode3_w"] = self.width()
                self.settings["mode3_h"] = self.height()
        else:
            if not self.is_compact:
                self.settings["win_w"] = self.width()
                self.settings["win_h"] = self.height()

        self.display_mode = mode
        self.settings["display_mode"] = mode
        next_has_video = (mode == 1) or (mode == 3 and self.karaoke_show_video)

        if self.display_mode in (1, 3) and self.is_compact:
            self.toggle_compact()

        if hasattr(self, "sync_timer") and self.sync_timer:
            self.sync_timer.setInterval(25 if self.display_mode == 3 else 50)

        self._apply_mode_layout(resize_window=True)
        self.apply_settings(self.settings)
        self.settings_autosave.emit(self.settings)

        # Smoothly glide song title between Under-Video and Top-Center when switching modes!
        if prev_has_video != next_has_video and prev_title_rect.width() > 20:
            def _kick_title_glide(old_r=prev_title_rect):
                self._position_karaoke_video_btn()
                cw = max(160, self.container.width())
                ch = max(100, self.container.height())
                start_w = min(old_r.width(), cw - 24)
                start_x = max(8, min(old_r.x(), cw - start_w - 8))
                start_y = max(36, min(old_r.y(), ch - 46))
                self.lbl_song_info.setGeometry(start_x, start_y, start_w, old_r.height())
                self._update_song_title_position(animate=True)
            QTimer.singleShot(0, _kick_title_glide)

    def paintEvent(self, event):
        # Clear transparent backing store cleanly and draw lightweight soft outer shadow when windowed
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)

        if not self.is_fullscreen:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            # Lightweight 4-layer soft drop shadow (~0.1ms vs 35ms for QGraphicsDropShadowEffect!)
            base = QRectF(self.container.geometry())
            for i, alpha in enumerate((18, 28, 40, 52)):
                spread = (4 - i) * 2.2
                r = base.adjusted(-spread, -spread + 2.0, spread, spread + 2.5)
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(r, 14.0 + spread * 0.6, 14.0 + spread * 0.6)
        painter.end()

    def toggle_fullscreen(self, force_exit: bool = False):
        """Toggle fullscreen in Mode 1 & Mode 3 using exact screen geometry (prevents Windows DWM/Qt6 ghosting)."""
        if self.display_mode not in (1, 3) and not force_exit:
            return

        target_fs = False if force_exit else (not self.is_fullscreen)
        if target_fs == self.is_fullscreen:
            return

        self.is_fullscreen = target_fs

        if self.is_fullscreen:
            self.normal_mode1_geom = self.geometry()
            self.outer_layout.setContentsMargins(0, 0, 0, 0)
            self.container.set_corner_radius(0.0)
            self.size_grip.setVisible(False)
            self.btn_fullscreen.set_kind("restore")
            self.btn_fullscreen.setToolTip("Thu nhỏ về cửa sổ (Esc / F11) - Tự động bật lại độ mờ")

            screen = self.screen() or QApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.geometry())
        else:
            self.outer_layout.setContentsMargins(10, 10, 10, 10)
            self.container.set_corner_radius(14.0)
            self.size_grip.setVisible(not self.is_locked)
            self.btn_fullscreen.set_kind("maximize")
            self.btn_fullscreen.setToolTip("Phóng to toàn màn hình (F11) - Tắt độ mờ khi toàn màn hình")

            if self.normal_mode1_geom:
                self.setGeometry(self.normal_mode1_geom)

        # Re-apply settings to switch opacity (1.0 in fullscreen vs bg_opacity when restored) and font scale
        self.apply_settings(self.settings)

        # Force immediate clean layout & backing store flush
        self.outer_layout.activate()
        self.container.updateGeometry()
        self.container.update()
        self.update()
        QTimer.singleShot(0, self._position_karaoke_video_btn)
        QTimer.singleShot(0, lambda: self._update_song_title_position(animate=False))
        QTimer.singleShot(20, self.repaint)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.is_fullscreen:
            self.toggle_fullscreen(force_exit=True)
            event.accept()
            return
        if event.key() == Qt.Key.Key_F11 and self.display_mode in (1, 3):
            self.toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def _apply_mode_layout(self, resize_window: bool = True):
        is_m1 = (self.display_mode == 1)
        is_m2 = (self.display_mode == 2)
        is_m3 = (self.display_mode == 3)
        show_video_now = is_m1 or (is_m3 and self.karaoke_show_video)

        accent_hex = self.adaptive_palette.get("accent_hex", "#38bdf8")
        self.btn_mode_dropdown.set_mode_state(self.display_mode, accent_hex)
        self._update_karaoke_video_btn_style(accent_hex)

        # Active line renderer: standard QLabel in Mode 1/2, word-by-word KaraokeLyricWidget in Mode 3
        self.lbl_active.setVisible(not is_m3)
        self.karaoke_widget.setVisible(is_m3)

        # Show/hide mode-specific toolbar controls
        self.btn_fullscreen.setVisible(is_m1 or is_m3)
        self.btn_zoom_out.setVisible(is_m2)
        self.btn_zoom_in.setVisible(is_m2)
        self.btn_compact.setVisible(is_m2)
        self.btn_karaoke_video.setVisible(is_m3)
        self.container.set_blurred_mode(True)

        if hasattr(self, "sync_timer") and self.sync_timer:
            self.sync_timer.setInterval(25 if is_m3 else 50)

        # Reserve top breathing room for floating [Video] pill & top-centered song title
        self._apply_lyrics_top_margin()

        # Apply instant stage layout on mode change (smooth animation is for Mode 3 Video toggle!)
        self.split_stage.set_video_visible(show_video_now, animate=False)

        self._suppress_resize_save = True
        try:
            if is_m1:
                target_w = max(720, int(self.settings.get("mode1_w", 940)))
                target_h = max(340, int(self.settings.get("mode1_h", 430)))
                self.setMinimumSize(620, 300)
                if resize_window and not self.is_fullscreen:
                    self.resize(target_w, target_h)
            elif is_m3:
                target_w = max(680, int(self.settings.get("mode3_w", self.settings.get("mode1_w", 940))))
                target_h = max(320, int(self.settings.get("mode3_h", self.settings.get("mode1_h", 430))))
                self.setMinimumSize(540, 280)
                if not show_video_now:
                    self.video_display.stop_video(clear_artwork=False)
                if resize_window and not self.is_fullscreen:
                    self.resize(target_w, target_h)
            else:
                target_w = max(360, int(self.settings.get("win_w", 680)))
                target_h = max(140, int(self.settings.get("win_h", 220)))
                self.setMinimumSize(280, 68)
                self.video_display.stop_video(clear_artwork=False)
                if resize_window:
                    self.resize(target_w, target_h)
        finally:
            self._suppress_resize_save = False

        self._trigger_track_media_load()

        # Refresh lyric line visibility, text & floating overlay positions
        self._refresh_visible_lines()
        QTimer.singleShot(0, self._position_karaoke_video_btn)
        QTimer.singleShot(0, lambda: self._update_song_title_position(animate=False))

    def _reset_track_artwork(self, clear_display: bool = True):
        """Clears previous track's blurred background & adaptive palette cleanly on song change."""
        self._artwork_priority = 0
        self.current_thumb_bytes = None
        self._current_video_req_key = None
        self.adaptive_palette = ThemeExtractor.DEFAULT_PALETTE.copy()
        self.container.set_blurred_background(QPixmap())
        self.video_display.set_border_color(QColor(255, 255, 255, 65))
        if clear_display:
            self.video_display.stop_video(clear_artwork=True)
        self.apply_settings(self.settings)

    def _maybe_apply_gsmtc_thumbnail(self, thumb_bytes: bytes):
        """
        Uses GSMTC thumbnail ONLY as a low-priority temporary fallback when no YouTube video artwork
        is loaded yet, and NEVER allows Chrome/Google placeholder logos or stale previous-song artwork
        to overwrite the real video background.
        """
        if not thumb_bytes:
            return
        if thumb_bytes == self._last_gsmtc_thumb_bytes:
            return
        self._last_gsmtc_thumb_bytes = thumb_bytes

        # Never let GSMTC overwrite real YouTube HD artwork or decoded video frames
        if self._artwork_priority >= 2:
            return
        # Never re-apply stale thumbnail carried over from the previous track
        if self._prev_track_gsmtc_bytes and thumb_bytes == self._prev_track_gsmtc_bytes:
            return
        # Never apply Google Chrome logo / Google G / tiny browser favicon / blank frame
        if ThemeExtractor.is_browser_placeholder_icon(thumb_bytes):
            return

        self.current_thumb_bytes = thumb_bytes
        self._artwork_priority = 1
        self._update_adaptive_theme_from_source(thumb_bytes)
        if self.video_display.fallback_pixmap.isNull():
            self.video_display.set_fallback_artwork(thumb_bytes)

    def _trigger_track_media_load(self):
        """
        Loads real YouTube HD video artwork (artwork_only=True when video pane is hidden, zero decoding)
        or full synchronized video stream + HD artwork (Mode 1, and Mode 3 Karaoke when Video is ON).
        """
        wants_video = (self.display_mode == 1) or (self.display_mode == 3 and self.karaoke_show_video)
        artwork_only = not wants_video
        if self.current_thumb_bytes and self._artwork_priority >= 1 and self.container.bg_pixmap.isNull():
            self._update_adaptive_theme_from_source(self.current_thumb_bytes)

        # In Mode 2, if we already have high-priority HD artwork for this track, no need to re-fetch
        if artwork_only and self._artwork_priority >= 2:
            return

        req_token = str(self._track_gen)
        if self.current_media_state and self.current_media_state.title:
            track_dur = float(getattr(self.current_media_state, "duration", 0.0) or 0.0)
            self._current_video_req_key = self.video_display.load_track(
                title=self.current_media_state.title,
                artist=self.current_media_state.artist,
                thumb_bytes=self.current_thumb_bytes,
                video_id=self.current_video_id,
                position_sec=self.current_media_state.get_current_position(),
                is_playing=self.current_media_state.is_playing,
                req_token=req_token,
                artwork_only=artwork_only,
                duration=track_dur,
            )
        elif self.current_lyrics and self.current_lyrics.get("title"):
            self._current_video_req_key = self.video_display.load_track(
                title=self.current_lyrics.get("title", ""),
                artist=self.current_lyrics.get("artist", ""),
                thumb_bytes=self.current_thumb_bytes,
                video_id=self.current_video_id,
                position_sec=0.0,
                is_playing=False,
                req_token=req_token,
                artwork_only=artwork_only,
            )

    def _trigger_mode1_media_load(self):
        self._trigger_track_media_load()

    def _on_video_id_resolved(self, req_key: str, vid: str):
        """Locks the resolved YouTube video_id for the current song so Karaoke Video toggle NEVER switches videos."""
        if not vid:
            return
        if req_key and self._current_video_req_key and req_key != self._current_video_req_key:
            return
        if not self.current_video_id:
            self.current_video_id = vid

    def _on_hd_artwork_ready(self, req_key: str, img_bytes: bytes):
        if not img_bytes:
            return
        if req_key and self._current_video_req_key and req_key != self._current_video_req_key:
            return
        self.current_thumb_bytes = img_bytes
        self._artwork_priority = 2
        self._update_adaptive_theme_from_source(img_bytes)

    def _on_video_frame_artwork_ready(self, req_key: str, qimg):
        if qimg is None or qimg.isNull():
            return
        if req_key and self._current_video_req_key and req_key != self._current_video_req_key:
            return
        if self._artwork_priority >= 2:
            return
        self._artwork_priority = 2
        self._update_adaptive_theme_from_source(qimg)

    def _update_adaptive_theme_from_source(self, source):
        if source is None:
            return
        palette = ThemeExtractor.extract_adaptive_palette(source)
        self.adaptive_palette = palette
        blurred = ThemeExtractor.create_blurred_background(
            source,
            target_w=max(480, self.width()),
            target_h=max(270, self.height()),
            blur_radius=28,
            scrim_rgb=palette.get("scrim_rgb")
        )
        self.container.set_blurred_background(blurred, palette.get("accent_hex"))
        c = QColor(palette.get("accent_hex", "#ffffff"))
        c.setAlpha(110)
        self.video_display.set_border_color(c)
        self.apply_settings(self.settings)

    def _update_adaptive_theme_from_bytes(self, img_bytes: bytes):
        self._update_adaptive_theme_from_source(img_bytes)

    def zoom_lyrics(self, delta_px: int):
        """Mode 2 Zoom In / Zoom Out: scales font size and proportionally adjusts window dimensions."""
        curr_size = int(self.settings.get("font_size", 22))
        new_size = max(12, min(54, curr_size + delta_px))
        if new_size == curr_size:
            return

        self.settings["font_size"] = new_size

        # Proportionally scale window when in Mode 2 (and not locked/compact)
        if self.display_mode == 2 and not self.is_locked and not self.is_compact:
            scale_w = self.width() + (delta_px * 18)
            scale_h = self.height() + (delta_px * 8)
            new_w = max(320, min(1400, scale_w))
            new_h = max(110, min(600, scale_h))
            self.resize(new_w, new_h)
            self.settings["win_w"] = new_w
            self.settings["win_h"] = new_h

        self.apply_settings(self.settings)
        self.settings_autosave.emit(self.settings)

    def wheelEvent(self, event):
        # Support Ctrl + Mouse Wheel to zoom in/out smoothly in Mode 2 (or anywhere)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 2 if event.angleDelta().y() > 0 else -2
            self.zoom_lyrics(delta)
            event.accept()
            return
        super().wheelEvent(event)

    # ---------------------------------------------------------
    # Volume Controls (Live Sync with Active Windows Audio Device)
    # ---------------------------------------------------------
    def sync_system_volume(self):
        """Syncs slider & icon in real time with the active Windows output device (speakers or headphones)."""
        if not hasattr(self, "slider_vol") or self.slider_vol.isSliderDown():
            return
        try:
            vol, muted, dev_name = self.volume_manager.get_state()
        except Exception:
            return

        state = (vol, muted, dev_name)
        if state == getattr(self, "_last_vol_state", None):
            return
        self._last_vol_state = state

        self.slider_vol.blockSignals(True)
        self.slider_vol.setValue(vol)
        self.slider_vol.blockSignals(False)
        self.slider_vol.set_visual_state(muted=muted)

        self.lbl_vol_val.setText("Mute" if muted else f"{vol}%")
        self.update_volume_icon(vol, muted)

        if dev_name:
            status_txt = tr(self._lang(), "mute") if muted else f"{vol}%"
            self.slider_vol.setToolTip(tr(self._lang(), "tip_vol_dev", dev=dev_name, status=status_txt))
            self.btn_vol.setToolTip(tr(self._lang(), "tip_vol_mute", dev=dev_name))
            self._update_bt_pill_output_icon(dev_name)

    def _update_bt_pill_output_icon(self, active_dev_name: str = ""):
        """Reflects whether active playback is routed to Bluetooth/Headphones or PC System Speakers."""
        if not hasattr(self, "lbl_bt_icon"):
            return
        low = (active_dev_name or "").lower()
        bt_name = (self.current_bt_state.device_name or "").lower() if (self.current_bt_state and self.current_bt_state.connected) else ""
        is_hp = any(k in low for k in ("headphone", "headset", "earphone", "bluetooth", "airpods", "buds", "tws", "tai nghe"))
        if not is_hp and bt_name and len(bt_name) >= 3:
            is_hp = (bt_name in low) or any(w in low for w in bt_name.split() if len(w) >= 4)
        accent_hex = self.adaptive_palette.get("accent_hex", "#38bdf8")
        if is_hp or not low:
            self.lbl_bt_icon.setPixmap(IconFactory.create_pixmap("headphones", "#ffffff", 13))
        else:
            # Bluetooth is connected, but user routed audio to PC system speakers
            self.lbl_bt_icon.setPixmap(IconFactory.create_pixmap("volume", accent_hex, 13))

    def toggle_audio_output_popup(self):
        """Slides up the Audio Output Device Selector directly above the bottom-left pill."""
        if self._audio_popup and self._audio_popup.isVisible():
            self._audio_popup.close()
            self._audio_popup = None
            return

        bt_name = (self.current_bt_state.device_name or "") if (self.current_bt_state and self.current_bt_state.connected) else ""
        devices = self.volume_manager.list_output_devices(bt_device_name=bt_name)
        accent_hex = self.adaptive_palette.get("accent_hex", "#38bdf8")

        popup = AudioOutputPopup(devices, accent_hex=accent_hex, app_lang=self._lang(), parent=self)
        popup.device_selected.connect(self._on_audio_device_selected)
        self._audio_popup = popup
        anchor = self.bt_pill.mapToGlobal(QPoint(0, 0))
        popup.show_slide_up(anchor, animate=True)

    def _on_audio_device_selected(self, dev_id: str):
        """Switches active Windows playback output immediately without toggling Bluetooth."""
        if not dev_id:
            return
        ok = self.volume_manager.set_default_output_device(dev_id)
        if ok:
            self._last_vol_state = None
            self.sync_system_volume()
            QTimer.singleShot(120, self.sync_system_volume)

    def on_volume_slider_changed(self, value: int):
        self.volume_manager.set_volume(value)
        is_mute = (value == 0) or self.volume_manager.is_muted()
        self.lbl_vol_val.setText("Mute" if (is_mute and value > 0) else f"{value}%")
        self.slider_vol.set_visual_state(muted=is_mute)
        self.update_volume_icon(value, is_mute)
        self._last_vol_state = (value, is_mute, self.volume_manager.get_device_name())

    def toggle_volume_mute(self):
        new_mute = self.volume_manager.toggle_mute()
        curr_vol, _, dev_name = self.volume_manager.get_state()
        self.slider_vol.blockSignals(True)
        self.slider_vol.setValue(curr_vol)
        self.slider_vol.blockSignals(False)
        self.slider_vol.set_visual_state(muted=new_mute)
        self.update_volume_icon(curr_vol, new_mute)
        self.lbl_vol_val.setText("Mute" if new_mute else f"{curr_vol}%")
        self._last_vol_state = (curr_vol, new_mute, dev_name)

    def update_volume_icon(self, vol_percent: int, is_muted: bool):
        if is_muted or vol_percent == 0:
            self.btn_vol.setIcon(IconFactory.create_icon("mute", "#f43f5e"))
        else:
            self.btn_vol.setIcon(IconFactory.create_icon("volume", "#ffffff"))

    def _lang(self) -> str:
        return (self.settings.get("app_lang") or "vi") if isinstance(self.settings, dict) else "vi"

    def _apply_ui_language(self, lang: str):
        """Applies the selected App UI Language live to all buttons, tooltips, dropdowns & idle text."""
        lang = lang or "vi"
        self.setWindowTitle(tr(lang, "app_title", ver=APP_VERSION))
        if hasattr(self, "btn_mode_dropdown"):
            self.btn_mode_dropdown.set_language(lang)
        if hasattr(self, "video_display"):
            self.video_display.set_language(lang)
        if hasattr(self, "btn_karaoke_video"):
            self.btn_karaoke_video.setText(tr(lang, "btn_video"))
            self.btn_karaoke_video.setToolTip(
                tr(lang, "tip_karaoke_video_on" if self.karaoke_show_video else "tip_karaoke_video_off")
            )
        if hasattr(self, "btn_prev"):
            self.btn_prev.setText(tr(lang, "prev_line"))
            self.btn_prev.setToolTip(tr(lang, "tip_prev"))
        if hasattr(self, "btn_play"):
            self.btn_play.setText(tr(lang, "play_pause"))
            self.btn_play.setToolTip(tr(lang, "tip_play"))
        if hasattr(self, "btn_next"):
            self.btn_next.setText(tr(lang, "next_line"))
            self.btn_next.setToolTip(tr(lang, "tip_next"))
        if hasattr(self, "btn_zoom_out"):
            self.btn_zoom_out.setToolTip(tr(lang, "tip_zoom_out"))
            self.btn_zoom_in.setToolTip(tr(lang, "tip_zoom_in"))
        if hasattr(self, "btn_search"):
            self.btn_search.setToolTip(tr(lang, "tip_search"))
            self.btn_settings.setToolTip(tr(lang, "tip_settings"))
            self.btn_lock.setToolTip(tr(lang, "tip_locked" if self.is_locked else "tip_lock"))
            self.btn_minimize.setToolTip(tr(lang, "tip_minimize"))
            self.btn_fullscreen.setToolTip(tr(lang, "tip_exit_fullscreen" if self.is_fullscreen else "tip_fullscreen"))
            self.btn_compact.setToolTip(tr(lang, "tip_compact"))
            self.btn_close.setToolTip(tr(lang, "tip_close"))
        if hasattr(self, "btn_translate"):
            trans_enabled = bool(self.settings.get("enable_translation", True))
            self.btn_translate.setToolTip(
                tr(lang, "tip_trans_on", lang=self.settings.get("translate_lang", "vi"))
                if trans_enabled else tr(lang, "tip_trans_off")
            )
        # Update idle placeholders if no track is playing yet
        if not self.current_media_state and not self.current_lyrics:
            if hasattr(self, "lbl_song_info"):
                self.lbl_song_info.setText(tr(lang, "waiting_music"))
            if hasattr(self, "lbl_active"):
                self.lbl_active.setText(tr(lang, "waiting_sources"))
            if hasattr(self, "karaoke_widget"):
                self.karaoke_widget.set_static_text(tr(lang, "waiting_sources"))
        QTimer.singleShot(0, self._position_karaoke_video_btn)

    # ---------------------------------------------------------
    # Styling & Settings
    # ---------------------------------------------------------
    def apply_settings(self, settings: dict):
        self.settings = settings
        new_mode = int(settings.get("display_mode", self.display_mode))
        if new_mode in (1, 2, 3) and new_mode != self.display_mode:
            self.display_mode = new_mode
            self._apply_mode_layout(resize_window=True)

        self._apply_ui_language(self._lang())

        font_family = settings.get("font_family", "Segoe UI")
        font_size = int(settings.get("font_size", 22))
        bg_opacity = float(settings.get("bg_opacity", 0.75))
        align_mode = int(settings.get("align_mode", 0))
        line_mode = int(settings.get("line_mode", 1))

        # Set Window Opacity: 100% solid (1.0) in Mode 1/3 Fullscreen, automatic bg_opacity when windowed!
        if self.display_mode in (1, 3) and self.is_fullscreen:
            self.setWindowOpacity(1.0)
        else:
            self.setWindowOpacity(max(0.15, bg_opacity))

        is_stage_mode = (self.display_mode in (1, 3))

        if is_stage_mode:
            # Mode 1 & Mode 3 (Karaoke): Left-aligned when Video is ON, Centered when Mode 3 Video is OFF
            if self.display_mode == 3 and not self.karaoke_show_video:
                align_flags = Qt.AlignmentFlag.AlignCenter
            else:
                align_flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            color_hi = self.adaptive_palette.get("active_color", "#7dd3fc")
            color_sub = self.adaptive_palette.get("sub_color", "rgba(255, 255, 255, 0.78)")
            color_far = self.adaptive_palette.get("far_color", "rgba(255, 255, 255, 0.42)")
            accent_hex = self.adaptive_palette.get("accent_hex", "#38bdf8")

            self.lbl_prev2.setVisible(True)
            self.lbl_prev.setVisible(True)
            self.lbl_next.setVisible(True)
            self.lbl_next2.setVisible(True)

            has_blur = not self.container.bg_pixmap.isNull()
            bg_alpha = 1.0 if self.is_fullscreen else bg_opacity
            container_bg = "transparent" if has_blur else f"rgba(15, 23, 42, {bg_alpha:.2f})"
            container_border = "none" if (has_blur or self.is_fullscreen) else "1px solid rgba(255, 255, 255, 0.15)"
            container_radius = "0px" if self.is_fullscreen else "14px"
            active_font_size = max(24, font_size + 10) if self.is_fullscreen else max(18, font_size + 2)
        else:
            # Mode 2: Centered lyric-only tab with the SAME blurred video backdrop & adaptive color as Mode 1!
            align_flags = Qt.AlignmentFlag.AlignCenter
            if align_mode == 1:
                align_flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            elif align_mode == 2:
                align_flags = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

            has_blur = not self.container.bg_pixmap.isNull()
            if has_blur or self._artwork_priority >= 1:
                color_hi = self.adaptive_palette.get("active_color", "#7dd3fc")
                color_sub = self.adaptive_palette.get("sub_color", "rgba(255, 255, 255, 0.78)")
                color_far = self.adaptive_palette.get("far_color", "rgba(255, 255, 255, 0.42)")
                accent_hex = self.adaptive_palette.get("accent_hex", "#38bdf8")
            else:
                color_hi = settings.get("color_highlight", "#38bdf8")
                color_sub = "#ffffff"
                color_far = "rgba(255, 255, 255, 0.5)"
                accent_hex = "#38bdf8"

            self.lbl_prev2.setVisible(False)
            self.lbl_prev.setVisible(line_mode == 2)
            self.lbl_next.setVisible(line_mode >= 1)
            self.lbl_next2.setVisible(False)

            container_bg = "transparent" if has_blur else f"rgba(15, 23, 42, {bg_opacity:.2f})"
            container_border = "none" if has_blur else "1px solid rgba(255, 255, 255, 0.15)"
            container_radius = "14px"
            active_font_size = font_size

        if not getattr(self.split_stage, "_animating", False):
            for lbl in [
                self.lbl_prev2, self.lbl_prev, self.lbl_active,
                self.lbl_active_romaji, self.lbl_active_trans,
                self.lbl_next, self.lbl_next2
            ]:
                lbl.setAlignment(align_flags)

        # Multi-script font fallback stack for crisp Japanese, Korean, Chinese, Thai, Cyrillic & Vietnamese rendering
        font_stack = f"'{font_family}', 'Yu Gothic UI', 'Meiryo UI', 'Malgun Gothic', 'Microsoft YaHei UI', 'Leelawadee UI', 'Segoe UI', sans-serif"
        families = [font_family, "Yu Gothic UI", "Meiryo UI", "Malgun Gothic", "Microsoft YaHei UI", "Leelawadee UI", "Segoe UI"]
        romaji_font_size = max(12, active_font_size - 3)
        trans_font_size = max(14, active_font_size - 1)
        trans_gap_top = 16 if (is_stage_mode and self.is_fullscreen) else 10

        self._base_active_font_size = active_font_size
        self._active_color_hi = color_hi
        self._active_font_stack = font_stack
        self._active_font_family = font_family

        # Update Mode Dropdown, Karaoke Video toggle pill & floating Song Title theme
        self.btn_mode_dropdown.set_mode_state(self.display_mode, accent_hex)
        self._update_karaoke_video_btn_style(accent_hex)
        if hasattr(self, "lbl_song_info") and hasattr(self.lbl_song_info, "set_theme"):
            self.lbl_song_info.set_theme(accent_hex, 15 if (is_stage_mode and self.is_fullscreen) else 13)
        if hasattr(self, "karaoke_widget"):
            self.karaoke_widget.set_style(families, active_font_size, color_hi)
            if not getattr(self.split_stage, "_animating", False):
                self.karaoke_widget.set_align_progress(
                    1.0 if (self.display_mode == 3 and not self.karaoke_show_video) else 0.0
                )

        # Sync translate toggle icon state
        trans_enabled = bool(self.settings.get("enable_translation", True))
        self.btn_translate.set_icon_state(
            "language",
            normal_color="#38bdf8" if trans_enabled else "#cbd5e1",
            hover_color="#7dd3fc" if trans_enabled else "#ffffff"
        )
        self.btn_translate.setToolTip(
            tr(self._lang(), "tip_trans_on", lang=self.settings.get("translate_lang", "vi"))
            if trans_enabled else tr(self._lang(), "tip_trans_off")
        )

        qss = f"""
            #GlassContainer {{
                background-color: {container_bg};
                border: {container_border};
                border-radius: {container_radius};
            }}
            #ActiveLyric {{
                font-family: {font_stack};
                font-size: {active_font_size}px;
                font-weight: bold;
                color: {color_hi};
                padding: 2px 0 1px 0;
            }}
            #ActiveRomaji {{
                font-family: {font_stack};
                font-size: {romaji_font_size}px;
                font-weight: 600;
                color: rgba(255, 255, 255, 0.92);
                letter-spacing: 0.3px;
                padding: 0 0 2px 0;
            }}
            #ActiveTransLyric {{
                font-family: {font_stack};
                font-size: {trans_font_size}px;
                font-weight: bold;
                color: #ffffff;
                padding: {trans_gap_top}px 0 4px 0;
            }}
            #PrevLyric, #NextLyric {{
                font-family: {font_stack};
                font-size: {max(12, active_font_size - 6)}px;
                color: {color_sub};
                padding: 1px 0;
            }}
            #FarLyric {{
                font-family: {font_stack};
                font-size: {max(11, active_font_size - 9)}px;
                color: {color_far};
                padding: 1px 0;
            }}
            #KaraokeVideoBtn {{
                background-color: rgba(15, 23, 42, 0.68);
                color: #f1f5f9;
                border: 1px solid rgba(255, 255, 255, 0.24);
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: bold;
            }}
            #KaraokeVideoBtn:hover {{
                background-color: rgba(255, 255, 255, 0.20);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.42);
            }}
            #KaraokeVideoBtnActive {{
                background-color: {accent_hex};
                color: #09090b;
                border: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: bold;
            }}
            #KaraokeVideoBtnActive:hover {{
                background-color: {accent_hex};
                border: 1px solid rgba(255, 255, 255, 0.55);
            }}
            #ToolIconBtn {{
                background-color: transparent;
                color: #cbd5e1;
                border: none;
                border-radius: 5px;
            }}
            #ToolIconBtn:hover {{
                background-color: rgba(255, 255, 255, 0.14);
                color: #ffffff;
            }}
            #ToolIconBtn:pressed {{
                background-color: rgba(255, 255, 255, 0.22);
            }}
            #IconBtn {{
                background-color: transparent;
                color: #cbd5e1;
                border: none;
                border-radius: 5px;
                font-size: 11px;
            }}
            #IconBtn:hover {{
                background-color: rgba(255, 255, 255, 0.15);
                color: #ffffff;
            }}
            #IconBtn:pressed {{
                background-color: rgba(255, 255, 255, 0.24);
            }}
            #MediaBtn {{
                background-color: rgba(255, 255, 255, 0.12);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: bold;
            }}
            #MediaBtn:hover {{
                background-color: rgba(255, 255, 255, 0.28);
                color: #ffffff;
            }}
            #BtPill {{
                background-color: rgba(255, 255, 255, 0.11);
                border: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 6px;
            }}
            #BtPill:hover {{
                background-color: rgba(255, 255, 255, 0.22);
                border: 1px solid rgba(255, 255, 255, 0.45);
            }}
            QSizeGrip {{
                width: 14px;
                height: 14px;
                background-color: transparent;
            }}
        """
        self.container.setStyleSheet(qss)
        if hasattr(self, "slider_vol"):
            self.slider_vol.set_visual_state(muted=self.slider_vol._muted_visual, accent_hex=accent_hex)
        self._last_fit_style_key = None
        QTimer.singleShot(0, self._position_karaoke_video_btn)

        # Refresh or start translation when settings change
        if self.current_lyrics:
            if trans_enabled:
                self._trigger_translation_if_needed()
            self._update_active_translation_label(self._effective_display_index())
        else:
            self._fit_active_lyric_fonts()

    # ---------------------------------------------------------
    # Multilingual Translation (Async Background Worker)
    # ---------------------------------------------------------
    def toggle_translation(self):
        new_val = not bool(self.settings.get("enable_translation", True))
        self.settings["enable_translation"] = new_val
        self.apply_settings(self.settings)
        self.settings_autosave.emit(self.settings)

    def _effective_display_index(self) -> int:
        if self.current_line_index >= 0:
            return self.current_line_index
        if self.current_lyrics and self.current_lyrics.get("lines"):
            lines = self.current_lyrics["lines"]
            if not self.current_media_state or lines[0]["time"] <= 2.0:
                return 0
        return -1

    def _sync_surrounding_lines_visibility(self, has_foreign_sub: bool):
        """Keeps the 3-tier foreign subtitle layout uncluttered like an MV/Vietsub card."""
        line_mode = int(self.settings.get("line_mode", 1))
        if self.display_mode in (1, 3):
            show_far = (not has_foreign_sub) or self.is_fullscreen
            self.lbl_prev2.setVisible(show_far)
            self.lbl_prev.setVisible(True)
            self.lbl_next.setVisible(True)
            self.lbl_next2.setVisible(show_far)
        else:
            # In Mode 2 (Lyric Only): focus cleanly on Original -> Romaji -> Translation when window is standard height
            if has_foreign_sub and self.height() < 310:
                self.lbl_prev2.setVisible(False)
                self.lbl_prev.setVisible(False)
                self.lbl_next.setVisible(False)
                self.lbl_next2.setVisible(False)
            else:
                self.lbl_prev2.setVisible(False)
                self.lbl_prev.setVisible(line_mode == 2)
                self.lbl_next.setVisible(line_mode >= 1)
                self.lbl_next2.setVisible(False)

    def _fit_active_lyric_fonts(self):
        """
        Dynamically fits active original, romanization, and translation font sizes to the
        available lyrics box so long lines stay clean and NEVER clip diacritics or bottom lines.
        """
        if not hasattr(self, "lbl_active") or not hasattr(self, "_base_active_font_size"):
            return

        base_sz = int(getattr(self, "_base_active_font_size", 22))
        color_hi = getattr(self, "_active_color_hi", "#38bdf8")
        font_stack = getattr(
            self, "_active_font_stack",
            "'Segoe UI', 'Yu Gothic UI', 'Meiryo UI', 'Malgun Gothic', 'Microsoft YaHei UI', 'Leelawadee UI', sans-serif"
        )
        font_family = getattr(self, "_active_font_family", "Segoe UI")
        families = [font_family, "Yu Gothic UI", "Meiryo UI", "Malgun Gothic", "Microsoft YaHei UI", "Leelawadee UI", "Segoe UI"]

        # Measure true available lyrics area (with safe fallback before first showEvent)
        lw = self.lyrics_widget.width()
        lh = self.lyrics_widget.height()
        if lw <= 120:
            is_full_w = (self.display_mode == 2) or (self.display_mode == 3 and not self.karaoke_show_video)
            lw = (self.width() - 56) if is_full_w else max(260, (self.width() - 72) * 12 // 21)
        if lh <= 60:
            lh = max(84, self.height() - 108)
        m = self.lyrics_box.contentsMargins()
        avail_w = max(200, lw - m.left() - m.right() - 10)
        avail_h = max(62, lh - m.top() - m.bottom() - 4)

        orig_text = self.lbl_active.text() or ""
        rm_vis = (not self.lbl_active_romaji.isHidden()) and bool(self.lbl_active_romaji.text())
        rm_text = self.lbl_active_romaji.text() if rm_vis else ""
        tr_vis = (not self.lbl_active_trans.isHidden()) and bool(self.lbl_active_trans.text())
        tr_text = self.lbl_active_trans.text() if tr_vis else ""

        # Reserve vertical space for visible surrounding lines (prev/next in Mode 1/3 or tall Mode 2)
        reserved_h = 0
        sub_sz = max(12, base_sz - 6)
        f_sub = QFont()
        f_sub.setFamilies(families)
        f_sub.setPixelSize(sub_sz)
        fm_sub = QFontMetrics(f_sub)
        for slbl in (self.lbl_prev2, self.lbl_prev, self.lbl_next, self.lbl_next2):
            if not slbl.isHidden() and slbl.text():
                sh = fm_sub.boundingRect(QRect(0, 0, avail_w, 2000), Qt.TextFlag.TextWordWrap, slbl.text()).height()
                reserved_h += sh + 6

        is_fs_m1 = (self.display_mode in (1, 3) and self.is_fullscreen)
        chosen = None

        for scale in (1.0, 0.92, 0.85, 0.78, 0.72, 0.66, 0.60, 0.54):
            sz_o = max(12, int(round(base_sz * scale)))
            sz_r = max(11, int(round(max(12, base_sz - 3) * scale)))
            sz_t = max(12, int(round(max(14, base_sz - 1) * scale)))
            if is_fs_m1:
                gap_top = 16 if scale >= 0.88 else (10 if scale >= 0.74 else 6)
            else:
                gap_top = 10 if scale >= 0.88 else (6 if scale >= 0.74 else 4)

            f_o = QFont()
            f_o.setFamilies(families)
            f_o.setPixelSize(sz_o)
            f_o.setBold(True)
            fm_o = QFontMetrics(f_o)

            # Avoid awkward 2-char orphan wrap on long original lines when a tiny shrink keeps it 1 clean line
            if scale == 1.0 and orig_text:
                single_w = fm_o.horizontalAdvance(orig_text)
                if avail_w < single_w <= avail_w * 1.24:
                    continue

            h_o = fm_o.boundingRect(QRect(0, 0, avail_w, 4000), Qt.TextFlag.TextWordWrap, orig_text).height() + 8 if orig_text else 0

            h_r = 0
            if rm_vis:
                f_r = QFont()
                f_r.setFamilies(families)
                f_r.setPixelSize(sz_r)
                f_r.setWeight(QFont.Weight.DemiBold)
                fm_r = QFontMetrics(f_r)
                h_r = fm_r.boundingRect(QRect(0, 0, avail_w, 4000), Qt.TextFlag.TextWordWrap, rm_text).height() + 6

            h_t = 0
            if tr_vis:
                f_t = QFont()
                f_t.setFamilies(families)
                f_t.setPixelSize(sz_t)
                f_t.setBold(True)
                fm_t = QFontMetrics(f_t)
                h_t = fm_t.boundingRect(QRect(0, 0, avail_w, 4000), Qt.TextFlag.TextWordWrap, tr_text).height() + gap_top + 10

            total_h = h_o + h_r + h_t + reserved_h + 6
            chosen = (sz_o, sz_r, sz_t, gap_top)
            if total_h <= avail_h:
                break

        if not chosen:
            return
        sz_o, sz_r, sz_t, gap_top = chosen
        style_key = (sz_o, sz_r, sz_t, gap_top, color_hi, font_stack)
        if getattr(self, "_last_fit_style_key", None) == style_key:
            return
        self._last_fit_style_key = style_key

        self.lbl_active.setStyleSheet(
            f"font-family: {font_stack}; font-size: {sz_o}px; font-weight: bold; color: {color_hi}; padding: 2px 0 1px 0;"
        )
        if hasattr(self, "karaoke_widget"):
            self.karaoke_widget.set_style(families, sz_o, color_hi)
        self.lbl_active_romaji.setStyleSheet(
            f"font-family: {font_stack}; font-size: {sz_r}px; font-weight: 600; color: rgba(255, 255, 255, 0.92); letter-spacing: 0.3px; padding: 0 0 2px 0;"
        )
        self.lbl_active_trans.setStyleSheet(
            f"font-family: {font_stack}; font-size: {sz_t}px; font-weight: bold; color: #ffffff; padding: {gap_top}px 0 4px 0;"
        )

    def _update_active_translation_label(self, idx: int):
        if (
            self.is_compact
            or not self.settings.get("enable_translation", True)
            or not self.current_lyrics
            or not self.current_lyrics.get("synced", False)
            or idx < 0
        ):
            self.lbl_active_romaji.setText("")
            self.lbl_active_romaji.setVisible(False)
            self.lbl_active_trans.setText("")
            self.lbl_active_trans.setVisible(False)
            self._sync_surrounding_lines_visibility(has_foreign_sub=False)
            self._fit_active_lyric_fonts()
            return

        target_lang = self.settings.get("translate_lang", "vi")
        trans_list = (self.current_lyrics.get("translations") or {}).get(target_lang)
        romaji_list = self.current_lyrics.get("romanizations")
        show_romaji_opt = bool(self.settings.get("enable_romanization", True))

        tr_text = ""
        if trans_list and idx < len(trans_list):
            tr_text = (trans_list[idx] or "").strip()

        rm_text = ""
        if show_romaji_opt and romaji_list and idx < len(romaji_list):
            rm_text = (romaji_list[idx] or "").strip()

        if rm_text:
            self.lbl_active_romaji.setText(rm_text)
            self.lbl_active_romaji.setVisible(True)
        else:
            self.lbl_active_romaji.setText("")
            self.lbl_active_romaji.setVisible(False)

        if tr_text:
            self.lbl_active_trans.setText(tr_text)
            self.lbl_active_trans.setVisible(True)
        else:
            self.lbl_active_trans.setText("")
            self.lbl_active_trans.setVisible(False)

        self._sync_surrounding_lines_visibility(has_foreign_sub=bool(rm_text or tr_text))
        self._fit_active_lyric_fonts()

    def _cleanup_old_trans_worker(self, worker):
        if worker in self._old_trans_workers:
            self._old_trans_workers.remove(worker)

    def _trigger_translation_if_needed(self):
        if not self.settings.get("enable_translation", True):
            return
        if not self.current_lyrics or not self.current_lyrics.get("synced", False):
            return
        lines = self.current_lyrics.get("lines") or []
        if not lines:
            return

        target_lang = self.settings.get("translate_lang", "vi")
        cached_trans = (self.current_lyrics.get("translations") or {}).get(target_lang)
        cached_rm = self.current_lyrics.get("romanizations")
        needs_rm = any(has_non_latin_script(l.get("text", "")) for l in lines[:20])
        rm_ready = (not needs_rm) or (isinstance(cached_rm, list) and len(cached_rm) == len(lines))

        if isinstance(cached_trans, list) and len(cached_trans) == len(lines) and rm_ready:
            self._update_active_translation_label(self._effective_display_index())
            return

        req_title = self.current_lyrics.get("req_title") or self.current_lyrics.get("title") or ""
        first_txt = (lines[0].get("text") or "")[:24]
        last_txt = (lines[-1].get("text") or "")[:24]
        req_key = f"{req_title}|{len(lines)}|{first_txt}|{last_txt}|{target_lang}|rm"
        if self.translation_worker and self.translation_worker.isRunning() and self.current_trans_req_key == req_key:
            return

        if self.translation_worker:
            old_w = self.translation_worker
            self.translation_worker = None
            old_w.cancel()
            try:
                old_w.translated.disconnect(self._on_translation_ready)
            except Exception:
                pass
            if old_w.isRunning():
                self._old_trans_workers.append(old_w)
                old_w.finished.connect(lambda w=old_w: self._cleanup_old_trans_worker(w))

        self.current_trans_req_key = req_key
        worker = TranslationWorker(req_key, lines, target_lang)
        worker.translated.connect(self._on_translation_ready)
        self.translation_worker = worker
        worker.start()

    def _on_translation_ready(
        self, req_key: str, target_lang: str, trans_list: list, romaji_list: list, detected_lang: str
    ):
        if req_key != self.current_trans_req_key or not self.current_lyrics:
            return
        lines = self.current_lyrics.get("lines") or []
        if len(trans_list) != len(lines):
            return

        self.current_lyrics.setdefault("translations", {})[target_lang] = trans_list
        if isinstance(romaji_list, list) and len(romaji_list) == len(lines):
            self.current_lyrics["romanizations"] = romaji_list
        if detected_lang:
            self.current_lyrics["detected_lang"] = detected_lang

        # Persist translation & romanization in local cache for instant reuse next playback
        try:
            if self.lyrics_provider and self.lyrics_provider.cache:
                title_for_cache = self.current_lyrics.get("req_title") or self.current_lyrics.get("title") or ""
                artist_for_cache = ""
                if self.current_media_state and self.current_media_state.artist:
                    artist_for_cache = self.current_media_state.artist.strip()
                elif self.current_lyrics.get("artist"):
                    artist_for_cache = self.current_lyrics.get("artist", "").strip()
                if title_for_cache:
                    clean_t = self.lyrics_provider.clean_title(title_for_cache)
                    self.lyrics_provider.cache.set(clean_t, artist_for_cache, self.current_lyrics)
        except Exception:
            pass

        self._update_active_translation_label(self._effective_display_index())

    # ---------------------------------------------------------
    # Media & Lyrics Sync
    # ---------------------------------------------------------
    def on_media_updated(self, media_state):
        self.current_media_state = media_state
        if not media_state or not media_state.title:
            lang = self._lang()
            self.lbl_song_info.setText(tr(lang, "waiting_music"))
            self.lbl_active.setText(tr(lang, "no_track_playing"))
            if hasattr(self, "karaoke_widget"):
                self.karaoke_widget.set_static_text(tr(lang, "no_track_playing"))
            self.lbl_active_romaji.setText("")
            self.lbl_active_romaji.setVisible(False)
            self.lbl_active_trans.setText("")
            self.lbl_active_trans.setVisible(False)
            self.lbl_prev2.setText("")
            self.lbl_prev.setText("")
            self.lbl_next.setText("")
            self.lbl_next2.setText("")
            self.current_lyrics = None
            self.current_video_id = None
            self._track_gen += 1
            self._prev_track_gsmtc_bytes = None
            self._last_gsmtc_thumb_bytes = None
            self._reset_track_artwork(clear_display=True)
            self._sync_surrounding_lines_visibility(has_foreign_sub=False)
            return

        new_title = (media_state.title or "").strip()
        new_artist = (media_state.artist or "").strip()

        from modules.media_listener import is_browser_junk_title
        if is_browser_junk_title(new_title, new_artist) and not media_state.is_playing:
            return

        info_text = f"{new_title} - {new_artist}" if new_artist else new_title
        self.lbl_song_info.setText(info_text)

        prev_req_title = self.current_lyrics.get("req_title") if self.current_lyrics else None
        prev_req_artist = self.current_lyrics.get("req_artist", "") if self.current_lyrics else ""
        song_changed = (
            not self.current_lyrics
            or prev_req_title != new_title
            or (bool(prev_req_artist) and bool(new_artist) and prev_req_artist != new_artist)
        )

        if song_changed:
            print(f"[Overlay] Fetching lyrics for: {new_title} - {new_artist}")

            # Reset previous track's artwork immediately so old background or Chrome transition logo never sticks
            self._track_gen += 1
            self._prev_track_gsmtc_bytes = self._last_gsmtc_thumb_bytes
            self._last_gsmtc_thumb_bytes = None
            self.current_video_id = None
            self._reset_track_artwork(clear_display=True)

            # Apply GSMTC thumbnail only if genuinely fresh and not a Chrome/Google logo
            self._maybe_apply_gsmtc_thumbnail(media_state.thumbnail_bytes)

            # Start fetching the real YouTube HD artwork (and video stream in Mode 1) in parallel with lyrics
            self._trigger_track_media_load()

            self.current_line_index = -99
            track_dur = float(getattr(media_state, "duration", 0.0) or 0.0)
            lyrics_data = self.lyrics_provider.fetch_lyrics(new_title, new_artist, duration=track_dur)
            if lyrics_data:
                lyrics_data["req_title"] = new_title
                lyrics_data["req_artist"] = new_artist
                self.current_lyrics = lyrics_data
                self.current_video_id = lyrics_data.get("video_id")
                self.settings["sync_offset"] = lyrics_data.get("sync_offset", 0.0)
            else:
                self.settings["sync_offset"] = 0.0
                self.current_lyrics = {
                    "req_title": new_title,
                    "req_artist": new_artist,
                    "synced": False,
                    "lines": [{"time": 0.0, "text": tr(self._lang(), "no_lyrics_found")}]
                }

            # If cached lyrics carried an explicit YouTube video_id, align artwork/video to that exact video
            if self.current_video_id:
                self._trigger_track_media_load()

            # Trigger async background auto-detection, romanization & translation
            self.lbl_active_romaji.setText("")
            self.lbl_active_romaji.setVisible(False)
            self.lbl_active_trans.setText("")
            self.lbl_active_trans.setVisible(False)
            self._trigger_translation_if_needed()

            # Snap immediately to the exact current playback line (including mid-song launches & auto-offset!)
            self._dur_recheck_key = (new_title, int(round(track_dur / 5.0))) if track_dur > 30.0 else None
            self.update_lyric_display()
        else:
            if self.current_lyrics and not prev_req_artist and new_artist:
                self.current_lyrics["req_artist"] = new_artist

            # Handle Chrome delayed duration update (Tick 0 reported duration=0 or previous video's duration,
            # then 1s later Chrome reports real Official MV duration like 248.2s -> upgrade to exact MV-synced LRC!)
            cur_dur = float(getattr(media_state, "duration", 0.0) or 0.0)
            if self.current_lyrics and cur_dur > 30.0:
                src_str = str(self.current_lyrics.get("source") or "")
                is_manual = ("Manual" in src_str) or ("Custom" in src_str)
                recheck_key = (new_title, int(round(cur_dur / 5.0)))
                if not is_manual and recheck_key != self._dur_recheck_key:
                    fetched_dur = float(self.current_lyrics.get("track_duration") or 0.0)
                    if fetched_dur <= 30.0 or abs(fetched_dur - cur_dur) > 10.0:
                        self._dur_recheck_key = recheck_key
                        print(f"[Overlay] Re-aligning lyrics to real video duration ({cur_dur:.1f}s) for: {new_title}")
                        better = self.lyrics_provider.fetch_lyrics(new_title, new_artist, duration=cur_dur)
                        if better and better.get("lines"):
                            better["req_title"] = new_title
                            better["req_artist"] = new_artist
                            self.current_lyrics = better
                            self.current_line_index = -99
                            self.settings["sync_offset"] = float(better.get("sync_offset", 0.0) or 0.0)
                            self.lbl_active_romaji.setText("")
                            self.lbl_active_romaji.setVisible(False)
                            self.lbl_active_trans.setText("")
                            self.lbl_active_trans.setVisible(False)
                            self.update_lyric_display()
                            self._trigger_translation_if_needed()

            # Only consider GSMTC thumbnail while no higher-priority YouTube video artwork is loaded
            self._maybe_apply_gsmtc_thumbnail(media_state.thumbnail_bytes)

    def set_custom_lyrics(self, lyrics_data: dict):
        if not lyrics_data or not lyrics_data.get("lines"):
            return

        lyrics_data = dict(lyrics_data)
        if self.current_media_state and self.current_media_state.title:
            req_title = (self.current_media_state.title or "").strip()
            req_artist = (self.current_media_state.artist or "").strip()
            lyrics_data["req_title"] = req_title
            lyrics_data["req_artist"] = req_artist
        else:
            title = (lyrics_data.get("title") or "").strip()
            artist = (lyrics_data.get("artist") or "").strip()
            if title:
                info_text = f"{title} - {artist}" if artist else f"{title}"
                self.lbl_song_info.setText(info_text)

        self.current_lyrics = lyrics_data
        self.current_line_index = -99
        self.settings["sync_offset"] = float(lyrics_data.get("sync_offset", 0.0) or 0.0)

        # Persist manually chosen lyric under EXACT raw title so '(Solo Version)' never collides with original!
        try:
            if self.current_media_state and self.current_media_state.title and self.lyrics_provider and self.lyrics_provider.cache:
                raw_t = self.current_media_state.title.strip()
                clean_t = self.lyrics_provider.clean_title(raw_t)
                clean_a = (self.current_media_state.artist or "").strip()
                if raw_t:
                    self.lyrics_provider.cache.set(raw_t, clean_a, self.current_lyrics)
                has_ver = hasattr(self.lyrics_provider, "_extract_version_tags") and bool(self.lyrics_provider._extract_version_tags(raw_t))
                if clean_t and clean_t != raw_t and not has_ver:
                    self.lyrics_provider.cache.set(clean_t, clean_a, self.current_lyrics)
        except Exception:
            pass

        # If search came from a YouTube URL, load that exact video & thumbnail in Mode 1!
        custom_vid = lyrics_data.get("video_id")
        thumb_url = lyrics_data.get("thumbnail_url")
        if custom_vid or thumb_url:
            self._track_gen += 1
            self._reset_track_artwork(clear_display=True)
        if custom_vid:
            self.current_video_id = custom_vid
        if thumb_url:
            try:
                resp = requests.get(thumb_url, timeout=4)
                if resp.status_code == 200 and len(resp.content) > 1500:
                    self.current_thumb_bytes = resp.content
                    self._artwork_priority = 2
                    self._update_adaptive_theme_from_source(self.current_thumb_bytes)
            except Exception:
                pass

        if custom_vid or thumb_url or not self.current_media_state:
            self._trigger_track_media_load()

        # Clear old translation/romaji first, snap visible lyrics immediately, then trigger fresh translation!
        self.lbl_active_romaji.setText("")
        self.lbl_active_romaji.setVisible(False)
        self.lbl_active_trans.setText("")
        self.lbl_active_trans.setVisible(False)

        lines = self.current_lyrics.get("lines", [])
        if self.current_media_state:
            self.update_lyric_display()
        elif lines:
            self.lbl_prev2.setText("")
            self.lbl_prev.setText("")
            self.lbl_active.setText(lines[0]["text"])
            if hasattr(self, "karaoke_widget"):
                self.karaoke_widget.set_lyric_line(lines, 0)
            self._update_active_translation_label(0)
            self.lbl_next.setText(lines[1]["text"] if len(lines) > 1 else "")
            self.lbl_next2.setText(lines[2]["text"] if len(lines) > 2 else "")

        self._trigger_translation_if_needed()
        self.container.update()
        self.update()

    def _refresh_visible_lines(self):
        if not self.current_lyrics or not self.current_lyrics.get("lines"):
            self._update_active_translation_label(-1)
            return
        lines = self.current_lyrics["lines"]
        idx = self.current_line_index
        intro_txt = tr(self._lang(), "intro_music")
        if idx < 0:
            self.lbl_prev2.setText("")
            self.lbl_prev.setText("")
            is_intro = bool(lines and lines[0]["time"] > 2.0 and self.current_media_state)
            self.lbl_active.setText(intro_txt if is_intro else lines[0]["text"])
            if hasattr(self, "karaoke_widget"):
                if is_intro:
                    self.karaoke_widget.set_lyric_line([], -1, intro_txt)
                else:
                    self.karaoke_widget.set_lyric_line(lines, 0)
            self._update_active_translation_label(-1 if is_intro else 0)
            self.lbl_next.setText(lines[0]["text"] if is_intro else (lines[1]["text"] if len(lines) > 1 else ""))
            self.lbl_next2.setText(lines[1]["text"] if (is_intro and len(lines) > 1) else (lines[2]["text"] if len(lines) > 2 else ""))
        else:
            self.lbl_prev2.setText(lines[idx - 2]["text"] if idx >= 2 else "")
            self.lbl_prev.setText(lines[idx - 1]["text"] if idx > 0 else intro_txt)
            self.lbl_active.setText(lines[idx]["text"] if idx < len(lines) else "")
            if hasattr(self, "karaoke_widget"):
                self.karaoke_widget.set_lyric_line(lines, idx)
            self._update_active_translation_label(idx)
            self.lbl_next.setText(lines[idx + 1]["text"] if idx + 1 < len(lines) else "")
            self.lbl_next2.setText(lines[idx + 2]["text"] if idx + 2 < len(lines) else "")

    def update_lyric_display(self):
        if not self.current_media_state:
            return

        # Keep video smoothly synced in Mode 1 and Mode 3 (Karaoke when Video is ON)
        if self.display_mode == 1 or (self.display_mode == 3 and self.karaoke_show_video):
            raw_pos = self.current_media_state.get_current_position()
            self.video_display.sync_to_media(raw_pos, self.current_media_state.is_playing)

        if not self.current_lyrics:
            return

        lines = self.current_lyrics.get("lines", [])
        if not lines:
            return

        synced = self.current_lyrics.get("synced", False)
        if not synced:
            self.lbl_prev2.setText("")
            self.lbl_prev.setText("")
            first_txt = lines[0]["text"] if lines else ""
            self.lbl_active.setText(first_txt)
            if hasattr(self, "karaoke_widget"):
                self.karaoke_widget.set_static_text(first_txt)
            self._update_active_translation_label(-1)
            self.lbl_next.setText("")
            self.lbl_next2.setText("")
            return

        current_time = self.current_media_state.get_current_position() + self.settings.get("sync_offset", 0.0)

        active_idx = -1
        for i, line in enumerate(lines):
            if current_time >= line["time"]:
                active_idx = i
            else:
                break

        if active_idx != self.current_line_index:
            self.current_line_index = active_idx
            intro_txt = tr(self._lang(), "intro_music")

            if active_idx == -1:
                prev2_text = ""
                prev_text = ""
                active_text = intro_txt
                next_text = lines[0]["text"] if lines else ""
                next2_text = lines[1]["text"] if len(lines) > 1 else ""
            else:
                prev2_text = lines[active_idx - 2]["text"] if active_idx >= 2 else ""
                prev_text = lines[active_idx - 1]["text"] if active_idx > 0 else intro_txt
                active_text = lines[active_idx]["text"]
                next_text = lines[active_idx + 1]["text"] if active_idx + 1 < len(lines) else ""
                next2_text = lines[active_idx + 2]["text"] if active_idx + 2 < len(lines) else ""

            self.lbl_prev2.setText(prev2_text)
            self.lbl_prev.setText(prev_text)
            self.lbl_active.setText(active_text)
            if hasattr(self, "karaoke_widget"):
                if active_idx == -1:
                    self.karaoke_widget.set_lyric_line([], -1, intro_txt)
                else:
                    self.karaoke_widget.set_lyric_line(lines, active_idx)
            self._update_active_translation_label(active_idx)
            self.lbl_next.setText(next_text)
            self.lbl_next2.setText(next2_text)

        # Feed real-time song position on every tick so Mode 3 Karaoke lights up word-by-word at exact tempo
        if self.display_mode == 3 and hasattr(self, "karaoke_widget"):
            self.karaoke_widget.set_playback_time(current_time)

    def jump_to_prev_line(self):
        if not self.current_lyrics or not self.current_lyrics.get("lines"):
            return
        target_idx = 0 if self.current_line_index <= 0 else self.current_line_index - 1
        self._sync_to_line_index(target_idx)

    def jump_to_next_line(self):
        if not self.current_lyrics or not self.current_lyrics.get("lines"):
            return
        lines = self.current_lyrics["lines"]
        if self.current_line_index < 0:
            target_idx = 0
        elif self.current_line_index >= len(lines) - 1:
            target_idx = len(lines) - 1
        else:
            target_idx = self.current_line_index + 1
        self._sync_to_line_index(target_idx)

    def _sync_to_line_index(self, target_idx: int):
        if not self.current_lyrics or not self.current_lyrics.get("lines"):
            return
        lines = self.current_lyrics["lines"]
        if target_idx < 0 or target_idx >= len(lines):
            return

        target_time = lines[target_idx]["time"]
        if self.current_media_state:
            raw_pos = self.current_media_state.get_current_position()
            needed_offset = target_time - raw_pos
            self.settings["sync_offset"] = round(needed_offset, 2)

            if self.current_lyrics:
                self.current_lyrics["sync_offset"] = round(needed_offset, 2)
                clean_t = self.lyrics_provider.clean_title(self.current_media_state.title)
                clean_a = self.current_media_state.artist.strip()
                if self.lyrics_provider.cache:
                    self.lyrics_provider.cache.set(clean_t, clean_a, self.current_lyrics)

            info_prefix = f"{self.current_media_state.title} - {self.current_media_state.artist}"
            self.lbl_song_info.setText(
                f"{info_prefix}  (Đã lưu đồng bộ câu {target_idx + 1}: {needed_offset:+.1f}s)"
            )

        self.current_line_index = target_idx
        self.lbl_prev2.setText(lines[target_idx - 2]["text"] if target_idx >= 2 else "")
        self.lbl_prev.setText(lines[target_idx - 1]["text"] if target_idx > 0 else "")
        self.lbl_active.setText(lines[target_idx]["text"])
        if hasattr(self, "karaoke_widget"):
            self.karaoke_widget.set_lyric_line(lines, target_idx)
            self.karaoke_widget.set_playback_time(target_time)
        self._update_active_translation_label(target_idx)
        self.lbl_next.setText(lines[target_idx + 1]["text"] if target_idx + 1 < len(lines) else "")
        self.lbl_next2.setText(lines[target_idx + 2]["text"] if target_idx + 2 < len(lines) else "")

    def toggle_lock(self):
        self.is_locked = not self.is_locked
        if self.is_locked:
            self.btn_lock.set_icon_state("lock", normal_color="#f59e0b", hover_color="#fbbf24")
            self.btn_lock.setToolTip("Cửa sổ đang bị khóa. Nhấn để mở khóa di chuyển.")
            self.lbl_song_info.setText("(Đã khóa vị trí) " + self.lbl_song_info.text().replace("(Đã khóa vị trí) ", ""))
            self.size_grip.setVisible(False)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.btn_lock.set_icon_state("unlock", normal_color="#cbd5e1", hover_color="#ffffff")
            self.btn_lock.setToolTip("Vị trí đang mở khóa. Bạn có thể kéo thả cửa sổ.")
            self.lbl_song_info.setText(self.lbl_song_info.text().replace("(Đã khóa vị trí) ", ""))
            self.size_grip.setVisible(True)

    def on_bt_battery_updated(self, state):
        """Updates Bluetooth headphone battery pill & Left/Right connection indicator."""
        self.current_bt_state = state
        if not state or not state.connected:
            self.bt_pill.setVisible(False)
            return

        # Choose battery icon & color based on minimum active battery %
        min_pct = state.effective_min_battery()
        if min_pct is not None:
            if min_pct >= 85:
                batt_key = "battery_full"
            elif min_pct >= 60:
                batt_key = "battery_3"
            elif min_pct >= 35:
                batt_key = "battery_2"
            elif min_pct >= 15:
                batt_key = "battery_1"
            else:
                batt_key = "battery_0"

            if min_pct >= 50:
                batt_color = "#4ade80"  # Green
            elif min_pct >= 20:
                batt_color = "#fbbf24"  # Amber
            else:
                batt_color = "#f43f5e"  # Red

            self.lbl_bt_batt_icon.setPixmap(IconFactory.create_pixmap(batt_key, batt_color, 14))
            self.lbl_bt_batt_icon.setVisible(True)
        else:
            self.lbl_bt_batt_icon.setVisible(False)

        dev_name = state.device_name or "Bluetooth"
        if state.has_lr_split:
            l_on = state.left_connected and state.left_battery is not None
            r_on = state.right_connected and state.right_battery is not None

            if l_on and r_on:
                l_chg = "+" if state.left_charging else ""
                r_chg = "+" if state.right_charging else ""
                self.lbl_bt_text.setText(f"L {state.left_battery}%{l_chg} | R {state.right_battery}%{r_chg}")
                tip = (
                    f"{dev_name}\n"
                    f"Đang kết nối: Cả 2 bên (Trái & Phải)\n"
                    f"- Tai trái (L): {state.left_battery}%\n"
                    f"- Tai phải (R): {state.right_battery}%"
                )
            elif l_on:
                l_chg = "+" if state.left_charging else ""
                self.lbl_bt_text.setText(f"Trái {state.left_battery}%{l_chg}")
                tip = (
                    f"{dev_name}\n"
                    f"Đang kết nối: Chỉ tai nghe bên TRÁI\n"
                    f"- Pin tai trái (L): {state.left_battery}%"
                )
            elif r_on:
                r_chg = "+" if state.right_charging else ""
                self.lbl_bt_text.setText(f"Phải {state.right_battery}%{r_chg}")
                tip = (
                    f"{dev_name}\n"
                    f"Đang kết nối: Chỉ tai nghe bên PHẢI\n"
                    f"- Pin tai phải (R): {state.right_battery}%"
                )
            else:
                # Fallback if split reported neither active
                if state.overall_battery is not None:
                    self.lbl_bt_text.setText(f"{state.overall_battery}%")
                    tip = f"{dev_name}\nPin tai nghe: {state.overall_battery}%"
                else:
                    self.lbl_bt_text.setText(dev_name[:12])
                    tip = f"{dev_name} (Đã kết nối)"

            if state.case_battery is not None:
                tip += f"\n- Hộp sạc: {state.case_battery}%"
            self.bt_pill.setToolTip(tip)
        else:
            if state.overall_battery is not None:
                self.lbl_bt_text.setText(f"{state.overall_battery}%")
                self.bt_pill.setToolTip(
                    f"{dev_name}\n"
                    f"Pin tai nghe: {state.overall_battery}%\n"
                    f"(Kết nối Bluetooth chuẩn - thiết bị chỉ báo pin tổng)"
                )
            else:
                short_name = dev_name if len(dev_name) <= 14 else dev_name[:13] + "..."
                self.lbl_bt_text.setText(short_name)
                self.bt_pill.setToolTip(f"{dev_name} (Đã kết nối - không báo phần trăm pin)")

        if not self.is_compact:
            cur_tip = self.bt_pill.toolTip() or ""
            hint = tr(self._lang(), "audio_out_click_tip")
            if hint not in cur_tip:
                self.bt_pill.setToolTip(f"{cur_tip}\n{hint}" if cur_tip else hint)
            self._update_bt_pill_output_icon(self.volume_manager.get_device_name())
            self.bt_pill.setVisible(True)

    def toggle_compact(self):
        if self.display_mode != 2:
            return
        self.is_compact = not self.is_compact
        if self.is_compact:
            self.lbl_version.setVisible(False)
            self.bt_pill.setVisible(False)
            self.btn_zoom_out.setVisible(False)
            self.btn_zoom_in.setVisible(False)
            self.btn_translate.setVisible(False)
            self.btn_search.setVisible(False)
            self.btn_settings.setVisible(False)
            self.btn_prev.setVisible(False)
            self.btn_play.setVisible(False)
            self.btn_next.setVisible(False)
            self.vol_widget.setVisible(False)
            self.btn_compact.set_kind("maximize")
            self.lbl_active_romaji.setVisible(False)
            self.lbl_active_trans.setVisible(False)
            self._apply_lyrics_top_margin()
            self._update_song_title_position(animate=False)
            self.resize(self.width(), 90)
        else:
            self.lbl_version.setVisible(True)
            if self.current_bt_state and self.current_bt_state.connected:
                self.bt_pill.setVisible(True)
            self.btn_zoom_out.setVisible(True)
            self.btn_zoom_in.setVisible(True)
            self.btn_translate.setVisible(True)
            self.btn_search.setVisible(True)
            self.btn_settings.setVisible(True)
            self.btn_prev.setVisible(True)
            self.btn_play.setVisible(True)
            self.btn_next.setVisible(True)
            self.vol_widget.setVisible(True)
            self.btn_compact.set_kind("restore")
            self._apply_lyrics_top_margin()
            self._update_active_translation_label(self._effective_display_index())
            self.resize(self.width(), max(180, int(self.settings.get("win_h", 220))))
            QTimer.singleShot(0, lambda: self._update_song_title_position(animate=False))

    # ---------------------------------------------------------
    # Mouse Edge Resize & Dragging System
    # ---------------------------------------------------------
    def _get_edge_at(self, pos: QPoint):
        w, h = self.width(), self.height()
        m = self.BORDER_MARGIN
        x, y = pos.x(), pos.y()

        left = x <= m
        right = x >= w - m
        top = y <= m
        bottom = y >= h - m

        if top and left: return "top_left"
        if top and right: return "top_right"
        if bottom and left: return "bottom_left"
        if bottom and right: return "bottom_right"
        if left: return "left"
        if right: return "right"
        if top: return "top"
        if bottom: return "bottom"
        return None

    def mouseMoveEvent(self, event):
        if self.is_locked or self.is_fullscreen:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        pos = event.position().toPoint()
        edge = self._get_edge_at(pos)

        if event.buttons() == Qt.MouseButton.LeftButton and self.active_edge:
            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self.press_global_pos
            geom = self.press_geom

            if self.display_mode == 1:
                min_w, min_h = 620, 300
            elif self.display_mode == 3:
                min_w, min_h = 540, 280
            else:
                min_w, min_h = 280, 68
            new_x, new_y, new_w, new_h = geom.x(), geom.y(), geom.width(), geom.height()

            if "right" in self.active_edge:
                new_w = max(min_w, geom.width() + delta.x())
            if "bottom" in self.active_edge:
                new_h = max(min_h, geom.height() + delta.y())
            if "left" in self.active_edge:
                w_candidate = geom.width() - delta.x()
                if w_candidate >= min_w:
                    new_w = w_candidate
                    new_x = geom.x() + delta.x()
            if "top" in self.active_edge:
                h_candidate = geom.height() - delta.y()
                if h_candidate >= min_h:
                    new_h = h_candidate
                    new_y = geom.y() + delta.y()

            self.setGeometry(new_x, new_y, new_w, new_h)
            event.accept()
            return

        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_position.isNull():
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
            return

        if edge in ["top_left", "bottom_right"]:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ["top_right", "bottom_left"]:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edge in ["left", "right"]:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ["top", "bottom"]:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _edge_to_qt_edges(self, edge: str):
        mapping = {
            "left": Qt.Edge.LeftEdge,
            "right": Qt.Edge.RightEdge,
            "top": Qt.Edge.TopEdge,
            "bottom": Qt.Edge.BottomEdge,
            "top_left": Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            "top_right": Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            "bottom_left": Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
            "bottom_right": Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        }
        return mapping.get(edge)

    def mousePressEvent(self, event):
        if self.is_locked or self.is_fullscreen:
            return

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            edge = self._get_edge_at(pos)
            win_handle = self.windowHandle()

            if edge:
                qt_edges = self._edge_to_qt_edges(edge)
                if win_handle and qt_edges is not None and win_handle.startSystemResize(qt_edges):
                    event.accept()
                    return
                self.active_edge = edge
                self.press_geom = self.geometry()
                self.press_global_pos = event.globalPosition().toPoint()
            else:
                # Hand drag directly to Windows DWM (native 60-144 FPS, zero jitter/lag!)
                if win_handle and win_handle.startSystemMove():
                    event.accept()
                    return
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self.is_fullscreen:
            self.settings["win_x"] = self.x()
            self.settings["win_y"] = self.y()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_active_lyric_fonts)
        QTimer.singleShot(0, self._position_karaoke_video_btn)
        QTimer.singleShot(0, lambda: self._update_song_title_position(animate=False))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.is_fullscreen and not getattr(self, "_suppress_resize_save", False):
            if self.display_mode == 1:
                self.settings["mode1_w"] = self.width()
                self.settings["mode1_h"] = self.height()
            elif self.display_mode == 3:
                self.settings["mode3_w"] = self.width()
                self.settings["mode3_h"] = self.height()
            elif not self.is_compact:
                self.settings["win_w"] = self.width()
                self.settings["win_h"] = self.height()
        self._position_karaoke_video_btn()
        if hasattr(self, "lbl_song_info") and not getattr(self.lbl_song_info, "_animating", False):
            self._update_song_title_position(animate=False)
        if hasattr(self, "lbl_active_trans") and hasattr(self, "lbl_active_romaji"):
            has_sub = bool(self.lbl_active_trans.text() or self.lbl_active_romaji.text()) and not self.is_compact and bool(self.settings.get("enable_translation", True))
            self._sync_surrounding_lines_visibility(has_foreign_sub=has_sub)
            self._fit_active_lyric_fonts()

    def mouseReleaseEvent(self, event):
        self.active_edge = None
        self.drag_position = QPoint()
        self.setCursor(Qt.CursorShape.ArrowCursor)

        if self.is_fullscreen:
            return

        self.settings["win_x"] = self.x()
        self.settings["win_y"] = self.y()
        if self.display_mode == 1:
            self.settings["mode1_w"] = self.width()
            self.settings["mode1_h"] = self.height()
        elif self.display_mode == 3:
            self.settings["mode3_w"] = self.width()
            self.settings["mode3_h"] = self.height()
        elif not self.is_compact:
            self.settings["win_w"] = self.width()
            self.settings["win_h"] = self.height()
