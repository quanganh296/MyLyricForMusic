import re
import urllib.parse
import requests
from modules.qt_compat import (
    QWidget, QThread, Signal, Qt, QPainter, QPainterPath, QColor,
    QPixmap, QImage, QUrl, QRectF, QFont,
    QMediaPlayer, QAudioOutput, QVideoSink, MULTIMEDIA_AVAILABLE
)


class VideoStreamResolver(QThread):
    """Background worker that resolves a YouTube video ID and direct playable MP4 stream URL."""
    resolved = Signal(str, str, str, bytes)  # req_key, video_id, stream_url, thumb_bytes
    failed = Signal(str, str)                # req_key, reason

    def __init__(self, req_key: str, title: str, artist: str = "", video_id: str = None, need_audio: bool = False):
        super().__init__()
        self.req_key = req_key
        self.title = title
        self.artist = artist
        self.video_id = video_id
        self.need_audio = need_audio
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _find_youtube_video_id(self) -> str:
        if self.video_id:
            return self.video_id
        query = f"{self.title} {self.artist}".strip() if self.artist and self.artist.lower() not in self.title.lower() else self.title
        try:
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "vi,en;q=0.9"
            }
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
                if vids:
                    return vids[0]
        except Exception as e:
            print(f"[VideoResolver Search Error] {e}")
        return None

    def _fetch_thumbnail_bytes(self, vid: str) -> bytes:
        for quality in ("hqdefault.jpg", "mqdefault.jpg"):
            try:
                r = requests.get(f"https://i.ytimg.com/vi/{vid}/{quality}", timeout=5)
                if r.status_code == 200 and len(r.content) > 2000:
                    return r.content
            except Exception:
                continue
        return b""

    def run(self):
        if self._cancelled:
            return

        vid = self._find_youtube_video_id()
        if self._cancelled:
            return
        if not vid:
            self.failed.emit(self.req_key, "Không tìm thấy video YouTube phù hợp")
            return

        thumb_bytes = self._fetch_thumbnail_bytes(vid)
        if self._cancelled:
            return

        try:
            import yt_dlp
            fmt = (
                "18/best[ext=mp4][acodec!=none][vcodec!=none]/best[ext=mp4]"
                if self.need_audio
                else "bestvideo[ext=mp4][vcodec^=avc1][height<=480]/18/best[ext=mp4]/best"
            )
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "format": fmt,
                "skip_download": True,
                "socket_timeout": 8,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
                stream_url = info.get("url") if info else None

            if self._cancelled:
                return

            if stream_url:
                self.resolved.emit(self.req_key, vid, stream_url, thumb_bytes)
            else:
                self.failed.emit(self.req_key, "Không thể lấy luồng video")
        except Exception as e:
            print(f"[VideoResolver yt-dlp Error] {e}")
            if not self._cancelled:
                # Still pass thumbnail bytes via failed/fallback handling if needed
                self.failed.emit(self.req_key, str(e))


class RoundedVideoDisplay(QWidget):
    """
    Renders a live synchronized YouTube video (via QMediaPlayer + QVideoSink)
    or crisp cover artwork inside a rounded 16:9 frame that works natively
    inside WA_TranslucentBackground frameless windows.
    """
    clicked = Signal()
    artwork_ready = Signal(bytes)  # Emitted when YouTube HD thumbnail is fetched

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 130)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Nhấn vào video để Phát / Tạm dừng")

        self.current_frame_img = QImage()
        self.fallback_pixmap = QPixmap()
        self.status_text = ""
        self.border_color = QColor(255, 255, 255, 65)

        self.current_req_key = None
        self.resolver = None
        self.is_stream_loaded = False
        self.pending_seek_sec = 0.0
        self.pending_playing = False

        self.player = None
        self.audio_output = None
        self.video_sink = None

        if MULTIMEDIA_AVAILABLE:
            self.player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.audio_output.setMuted(True)  # Muted by default to avoid double audio with Chrome
            self.player.setAudioOutput(self.audio_output)

            self.video_sink = QVideoSink(self)
            self.player.setVideoOutput(self.video_sink)
            self.video_sink.videoFrameChanged.connect(self._on_video_frame)
            self.player.mediaStatusChanged.connect(self._on_media_status_changed)
            self.player.errorOccurred.connect(self._on_player_error)

    def set_border_color(self, rgba_str_or_qcolor):
        if isinstance(rgba_str_or_qcolor, QColor):
            self.border_color = rgba_str_or_qcolor
        self.update()

    def set_fallback_artwork(self, img_bytes: bytes):
        if img_bytes:
            pix = QPixmap()
            if pix.loadFromData(img_bytes):
                self.fallback_pixmap = pix
                self.update()

    def load_track(self, title: str, artist: str = "", thumb_bytes: bytes = None,
                   video_id: str = None, position_sec: float = 0.0, is_playing: bool = False):
        req_key = f"{video_id or ''}|{title}|{artist}"
        if req_key == self.current_req_key and (self.is_stream_loaded or (self.resolver and self.resolver.isRunning())):
            return

        self.stop_video(clear_artwork=False)
        self.current_req_key = req_key
        self.pending_seek_sec = max(0.0, position_sec)
        self.pending_playing = is_playing
        self.is_stream_loaded = False
        self.current_frame_img = QImage()

        if thumb_bytes:
            self.set_fallback_artwork(thumb_bytes)

        if not MULTIMEDIA_AVAILABLE or not title:
            self.status_text = ""
            self.update()
            return

        self.status_text = "Đang tải video..."
        self.update()

        self.resolver = VideoStreamResolver(req_key, title, artist, video_id=video_id, need_audio=False)
        self.resolver.resolved.connect(self._on_stream_resolved)
        self.resolver.failed.connect(self._on_stream_failed)
        self.resolver.start()

    def _on_stream_resolved(self, req_key: str, video_id: str, stream_url: str, thumb_bytes: bytes):
        if req_key != self.current_req_key:
            return
        if thumb_bytes:
            self.set_fallback_artwork(thumb_bytes)
            self.artwork_ready.emit(thumb_bytes)

        if self.player and stream_url:
            self.status_text = "Đang đệm video..."
            self.player.setSource(QUrl(stream_url))
            if self.pending_playing:
                self.player.play()
            else:
                self.player.play()
                # Will pause right after first frame / LoadedMedia so a crisp frame is visible
            self.update()

    def _on_stream_failed(self, req_key: str, reason: str):
        if req_key != self.current_req_key:
            return
        self.status_text = ""
        self.is_stream_loaded = False
        self.update()

    def _on_media_status_changed(self, status):
        if not self.player:
            return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if not self.is_stream_loaded:
                self.is_stream_loaded = True
                self.status_text = ""
                if self.pending_seek_sec > 1.0:
                    self.player.setPosition(int(self.pending_seek_sec * 1000))
                if self.pending_playing:
                    self.player.play()
                else:
                    self.player.pause()
                self.update()

    def _on_player_error(self, err, err_str):
        print(f"[VideoPlayer Error] {err}: {err_str}")
        self.status_text = ""
        self.is_stream_loaded = False
        self.update()

    def _on_video_frame(self, frame):
        if frame.isValid():
            img = frame.toImage()
            if not img.isNull():
                self.current_frame_img = img
                if self.status_text:
                    self.status_text = ""
                self.update()

    def sync_to_media(self, position_sec: float, is_playing: bool):
        self.pending_seek_sec = max(0.0, position_sec)
        self.pending_playing = is_playing

        if not self.player or not self.is_stream_loaded:
            return

        # Sync play/pause state
        p_state = self.player.playbackState()
        if is_playing and p_state != QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()
        elif not is_playing and p_state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()

        # Sync timestamp if drift exceeds 1.5 seconds
        dur_ms = self.player.duration()
        if dur_ms > 0:
            target_ms = min(int(position_sec * 1000), max(0, dur_ms - 500))
            curr_ms = self.player.position()
            if abs(curr_ms - target_ms) > 1500:
                self.player.setPosition(target_ms)

    def stop_video(self, clear_artwork: bool = False):
        if self.resolver:
            self.resolver.cancel()
            try:
                self.resolver.resolved.disconnect()
                self.resolver.failed.disconnect()
            except Exception:
                pass
            self.resolver = None

        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())

        self.is_stream_loaded = False
        self.current_frame_img = QImage()
        self.status_text = ""
        self.current_req_key = None
        if clear_artwork:
            self.fallback_pixmap = QPixmap()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        # Fit a clean 16:9 box inside available rect
        target_ratio = 16.0 / 9.0
        if w / max(1, h) > target_ratio:
            box_h = h - 4
            box_w = int(box_h * target_ratio)
        else:
            box_w = w - 4
            box_h = int(box_w / target_ratio)

        x = (w - box_w) // 2
        y = (h - box_h) // 2
        rect = QRectF(x, y, box_w, box_h)

        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, 12.0, 12.0)
        painter.setClipPath(clip_path)

        # Dark backdrop inside video frame
        painter.fillRect(rect, QColor(10, 12, 18, 220))

        # Draw live video frame directly (zero-copy drawImage with aspect-ratio crop, no per-frame QImage allocation!)
        if not self.current_frame_img.isNull():
            img = self.current_frame_img
            iw, ih = img.width(), img.height()
            if iw > 0 and ih > 0:
                img_ratio = iw / ih
                box_ratio = box_w / max(1, box_h)
                if img_ratio > box_ratio:
                    crop_w = ih * box_ratio
                    src = QRectF((iw - crop_w) / 2.0, 0.0, crop_w, ih)
                else:
                    crop_h = iw / box_ratio
                    src = QRectF(0.0, (ih - crop_h) / 2.0, iw, crop_h)
                painter.drawImage(rect, img, src)
        elif not self.fallback_pixmap.isNull():
            pix = self.fallback_pixmap
            pw, ph = pix.width(), pix.height()
            if pw > 0 and ph > 0:
                p_ratio = pw / ph
                box_ratio = box_w / max(1, box_h)
                if p_ratio > box_ratio:
                    crop_w = ph * box_ratio
                    src = QRectF((pw - crop_w) / 2.0, 0.0, crop_w, ph)
                else:
                    crop_h = pw / box_ratio
                    src = QRectF(0.0, (ph - crop_h) / 2.0, pw, crop_h)
                painter.drawPixmap(rect, pix, src)
        else:
            painter.setPen(QColor(255, 255, 255, 130))
            font = QFont("Segoe UI", 10)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Chờ video phát nhạc...")

        # Optional subtle status pill in bottom-right corner while buffering
        if self.status_text:
            badge_w, badge_h = 128, 22
            bx = x + box_w - badge_w - 8
            by = y + box_h - badge_h - 8
            badge_rect = QRectF(bx, by, badge_w, badge_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 165))
            painter.drawRoundedRect(badge_rect, 6.0, 6.0)
            painter.setPen(QColor(255, 255, 255, 230))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, self.status_text)

        # Crisp subtle rounded border
        painter.setClipping(False)
        painter.setPen(self.border_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 12.0, 12.0)
        painter.end()

