import json
import re
import urllib.parse
import requests
from modules.qt_compat import (
    QWidget, QThread, Signal, Qt, QPainter, QPainterPath, QColor,
    QPixmap, QImage, QUrl, QRectF, QFont,
    QMediaPlayer, QAudioOutput, QVideoSink, MULTIMEDIA_AVAILABLE
)
from modules.i18n import tr


def _parse_yt_length_sec(length_str: str) -> float:
    """Parses YouTube duration strings like '3:36' or '1:04:12' into seconds."""
    if not length_str:
        return 0.0
    parts = [p for p in str(length_str).strip().split(":") if p.isdigit()]
    if not parts:
        return 0.0
    sec = 0
    for p in parts:
        sec = sec * 60 + int(p)
    return float(sec)


def _norm_match_tokens(text: str) -> set:
    if not text:
        return set()
    return set(re.findall(r'[a-z0-9\u00c0-\u024f\u1e00-\u1eff]{2,}|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+', text.lower()))


class VideoStreamResolver(QThread):
    """Background worker that resolves the EXACT YouTube video ID and direct playable MP4 stream URL."""
    video_id_found = Signal(str, str)        # req_key, video_id (emitted immediately so video ID locks!)
    intro_offset_found = Signal(str, str, float)  # req_key, video_id, non-music intro duration (sec)
    artwork_fetched = Signal(str, bytes)     # req_key, thumb_bytes (emitted immediately before yt-dlp)
    resolved = Signal(str, str, str, bytes)  # req_key, video_id, stream_url, thumb_bytes
    failed = Signal(str, str)                # req_key, reason

    def __init__(self, req_key: str, title: str, artist: str = "", video_id: str = None,
                 need_audio: bool = False, artwork_only: bool = False, duration: float = 0.0):
        super().__init__()
        self.req_key = req_key
        self.title = title
        self.artist = artist
        self.video_id = video_id
        self.need_audio = need_audio
        self.artwork_only = artwork_only
        self.duration = float(duration or 0.0)
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
                # Score real videoRenderer entries by exact title + channel + duration match
                # so we lock onto the EXACT YouTube video the user is playing instead of a similar lyrics video!
                m = re.search(r"var ytInitialData = (\{.*?\});</script>", resp.text)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        renderers = []

                        def _collect(obj):
                            if len(renderers) >= 12:
                                return
                            if isinstance(obj, dict):
                                if "videoRenderer" in obj and isinstance(obj["videoRenderer"], dict):
                                    renderers.append(obj["videoRenderer"])
                                    return
                                for v in obj.values():
                                    _collect(v)
                            elif isinstance(obj, list):
                                for it in obj:
                                    _collect(it)

                        _collect(data)
                        if renderers:
                            req_t_low = (self.title or "").strip().lower()
                            req_a_low = (self.artist or "").strip().lower()
                            req_t_toks = _norm_match_tokens(self.title)
                            best_vid = None
                            best_score = -1e9

                            for rank_idx, vr in enumerate(renderers):
                                vid = vr.get("videoId")
                                if not vid or len(vid) != 11:
                                    continue
                                cand_t = "".join(r.get("text", "") for r in (vr.get("title", {}).get("runs") or [])).strip()
                                cand_ch = "".join(r.get("text", "") for r in (vr.get("ownerText", {}).get("runs") or [])).strip()
                                cand_dur = _parse_yt_length_sec(vr.get("lengthText", {}).get("simpleText", ""))

                                sc = max(0.0, 24.0 - rank_idx * 3.0)
                                cand_t_low = cand_t.lower()
                                if req_t_low and cand_t_low == req_t_low:
                                    sc += 500.0
                                elif req_t_low and (req_t_low in cand_t_low or cand_t_low in req_t_low):
                                    sc += 280.0
                                else:
                                    ct = _norm_match_tokens(cand_t)
                                    if req_t_toks and ct:
                                        overlap = len(req_t_toks & ct) / max(1, len(req_t_toks))
                                        sc += overlap * 240.0

                                if req_a_low and cand_ch:
                                    ch_low = cand_ch.lower()
                                    if ch_low == req_a_low or req_a_low in ch_low or ch_low in req_a_low:
                                        sc += 320.0

                                if self.duration > 20.0 and cand_dur > 20.0:
                                    diff = abs(cand_dur - self.duration)
                                    if diff <= 3.0:
                                        sc += 220.0
                                    elif diff <= 8.0:
                                        sc += 120.0
                                    elif diff > 35.0:
                                        sc -= 140.0

                                if sc > best_score:
                                    best_score = sc
                                    best_vid = vid

                            if best_vid:
                                return best_vid
                    except Exception:
                        pass

                vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
                if vids:
                    return vids[0]
        except Exception as e:
            print(f"[VideoResolver Search Error] {e}")
        return None

    def _fetch_thumbnail_bytes(self, vid: str) -> bytes:
        for quality in ("maxresdefault.jpg", "hqdefault.jpg", "mqdefault.jpg"):
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
            self.failed.emit(self.req_key, "No matching YouTube video found")
            return

        # Emit resolved video_id immediately so parent locks onto this exact video across Mode 3 Video toggles!
        self.video_id_found.emit(self.req_key, vid)

        thumb_bytes = self._fetch_thumbnail_bytes(vid)
        if self._cancelled:
            return
        if thumb_bytes:
            # Deliver real HD YouTube thumbnail immediately (~0.3s) without waiting for yt-dlp!
            self.artwork_fetched.emit(self.req_key, thumb_bytes)

        # Query non-music cinematic MV intro duration asynchronously (SponsorBlock music_offtopic)
        # so studio-timed lyrics wait cleanly during MV intros instead of starting before vocals!
        try:
            from modules.lyrics_provider import fetch_youtube_intro_offset
            intro_sec = fetch_youtube_intro_offset(vid, timeout=2.5)
            if intro_sec >= 3.0 and not self._cancelled:
                self.intro_offset_found.emit(self.req_key, vid, float(intro_sec))
        except Exception:
            pass
        if self._cancelled:
            return

        # In Mode 2 (or Mode 3 with Video OFF), only fetch HD artwork without decoding MP4 stream!
        if self.artwork_only:
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
                self.failed.emit(self.req_key, "Could not resolve video stream")
        except Exception as e:
            print(f"[VideoResolver yt-dlp Error] {e}")
            if not self._cancelled:
                self.failed.emit(self.req_key, str(e))


class RoundedVideoDisplay(QWidget):
    """
    Renders a live synchronized YouTube video (via QMediaPlayer + QVideoSink)
    or crisp cover artwork inside a rounded 16:9 frame that works natively
    inside WA_TranslucentBackground frameless windows.
    """
    clicked = Signal()
    video_id_resolved = Signal(str, str)            # req_key, locked YouTube video_id
    intro_offset_resolved = Signal(str, str, float) # req_key, video_id, MV intro sec
    artwork_ready = Signal(str, bytes)              # req_key, thumb_bytes (HD YouTube thumbnail)
    video_frame_artwork_ready = Signal(str, QImage) # req_key, decoded video frame fallback

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_lang = "vi"
        self._repaint_suspended = False
        self.setMinimumSize(220, 130)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr(self._app_lang, "video_click_tip"))

        self.current_frame_img = QImage()
        self.fallback_pixmap = QPixmap()
        self.status_text = ""
        self.border_color = QColor(255, 255, 255, 65)
        self._render_opacity = 1.0

        self.current_req_key = None
        self.current_video_id = None
        self._cached_streams = {}  # video_id -> direct stream URL (instant resume on Karaoke Video toggle!)
        self.resolver = None
        self._old_resolvers = []
        self.is_stream_loaded = False
        self._artwork_only_mode = False
        self._has_hd_artwork = False
        self._emitted_frame_artwork = False
        self._frame_check_count = 0
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

    def set_repaint_suspended(self, suspended: bool):
        """Suspends per-frame widget repaints during native Windows DWM drag/resize to prevent layered snap-back."""
        suspended = bool(suspended)
        if self._repaint_suspended != suspended:
            self._repaint_suspended = suspended
            if not suspended:
                if not self._repaint_suspended:
                    self.update()

    def set_language(self, lang: str):
        self._app_lang = lang or "vi"
        self.setToolTip(tr(self._app_lang, "video_click_tip"))
        self.update()

    def _cleanup_old_resolver(self, resolver):
        if resolver in self._old_resolvers:
            if resolver.isRunning():
                from modules.qt_compat import QTimer
                QTimer.singleShot(600, lambda r=resolver: self._cleanup_old_resolver(r))
                return
            self._old_resolvers.remove(resolver)

    def set_border_color(self, rgba_str_or_qcolor):
        if isinstance(rgba_str_or_qcolor, QColor):
            self.border_color = rgba_str_or_qcolor
        self.update()

    def set_render_opacity(self, alpha: float):
        alpha = max(0.0, min(1.0, float(alpha)))
        if abs(alpha - self._render_opacity) > 0.002:
            self._render_opacity = alpha
            self.update()

    def set_fallback_artwork(self, img_bytes: bytes):
        if img_bytes:
            pix = QPixmap()
            if pix.loadFromData(img_bytes):
                self.fallback_pixmap = pix
                if not self._repaint_suspended:
                    self.update()

    def load_track(self, title: str, artist: str = "", thumb_bytes: bytes = None,
                   video_id: str = None, position_sec: float = 0.0, is_playing: bool = False,
                   req_token: str = "", artwork_only: bool = False, duration: float = 0.0):
        # Preserve locked video_id for the exact same playing track so toggling Video in Karaoke Mode
        # NEVER re-searches YouTube or jumps to a different video!
        effective_vid = video_id or (
            self.current_video_id if (self.current_req_key and self.current_req_key.startswith(f"{req_token}|")) else None
        )
        req_key = f"{req_token}|{effective_vid or ''}|{title}|{artist}"
        same_track = bool(
            self.current_req_key
            and (
                req_key == self.current_req_key
                or (req_token and self.current_req_key.startswith(f"{req_token}|") and (not effective_vid or effective_vid == self.current_video_id))
            )
        )
        if same_track:
            if artwork_only and (self._has_hd_artwork or self.is_stream_loaded or (self.resolver and self.resolver.isRunning())):
                return self.current_req_key
            if not artwork_only and (self.is_stream_loaded or (self.resolver and self.resolver.isRunning() and not self._artwork_only_mode)):
                return self.current_req_key

        self.stop_video(clear_artwork=(not same_track))
        self.current_req_key = req_key
        if effective_vid:
            self.current_video_id = effective_vid
        self._artwork_only_mode = artwork_only
        self.pending_seek_sec = max(0.0, position_sec)
        self.pending_playing = is_playing
        self.is_stream_loaded = False
        self._has_hd_artwork = bool(same_track and not self.fallback_pixmap.isNull())
        self._emitted_frame_artwork = False
        self._frame_check_count = 0
        self.current_frame_img = QImage()

        if thumb_bytes:
            self.set_fallback_artwork(thumb_bytes)

        if not title or (not artwork_only and not MULTIMEDIA_AVAILABLE):
            self.status_text = ""
            self.update()
            return req_key

        # Instant resume from cached stream URL if this exact video was already resolved!
        if (not artwork_only) and effective_vid and effective_vid in self._cached_streams and self.player:
            cached_url = self._cached_streams[effective_vid]
            self.status_text = tr(self._app_lang, "video_buffering")
            self.player.setSource(QUrl(cached_url))
            self.player.play()
            self.update()
            return req_key

        self.status_text = "" if artwork_only else tr(self._app_lang, "video_loading")
        self.update()

        self.resolver = VideoStreamResolver(
            req_key, title, artist, video_id=effective_vid,
            need_audio=False, artwork_only=artwork_only, duration=duration
        )
        self.resolver.video_id_found.connect(self._on_video_id_found)
        self.resolver.intro_offset_found.connect(self._on_intro_offset_found)
        self.resolver.artwork_fetched.connect(self._on_artwork_fetched)
        self.resolver.resolved.connect(self._on_stream_resolved)
        self.resolver.failed.connect(self._on_stream_failed)
        self.resolver.start()
        return req_key

    def _on_video_id_found(self, req_key: str, vid: str):
        if req_key != self.current_req_key or not vid:
            return
        self.current_video_id = vid
        self.video_id_resolved.emit(req_key, vid)

    def _on_intro_offset_found(self, req_key: str, vid: str, intro_sec: float):
        if req_key != self.current_req_key or intro_sec < 3.0:
            return
        self.intro_offset_resolved.emit(req_key, vid, float(intro_sec))

    def _on_artwork_fetched(self, req_key: str, thumb_bytes: bytes):
        if req_key != self.current_req_key or not thumb_bytes:
            return
        self._has_hd_artwork = True
        self.set_fallback_artwork(thumb_bytes)
        self.artwork_ready.emit(req_key, thumb_bytes)

    def _on_stream_resolved(self, req_key: str, video_id: str, stream_url: str, thumb_bytes: bytes):
        if req_key != self.current_req_key:
            return
        if video_id:
            self.current_video_id = video_id
            if stream_url:
                self._cached_streams[video_id] = stream_url
                if len(self._cached_streams) > 12:
                    self._cached_streams.pop(next(iter(self._cached_streams)))
        if thumb_bytes and not self._has_hd_artwork:
            self._has_hd_artwork = True
            self.set_fallback_artwork(thumb_bytes)
            self.artwork_ready.emit(req_key, thumb_bytes)

        if self.player and stream_url:
            self.status_text = tr(self._app_lang, "video_buffering")
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
                if not self._repaint_suspended:
                    self.update()

    def _on_player_error(self, err, err_str):
        print(f"[VideoPlayer Error] {err}: {err_str}")
        self.status_text = ""
        self.is_stream_loaded = False
        self.update()

    @staticmethod
    def _is_non_black_frame(img: QImage) -> bool:
        try:
            tiny = img.scaled(16, 16).convertToFormat(QImage.Format.Format_RGB888)
            ptr = tiny.bits()
            ptr.setsize(tiny.sizeInBytes())
            raw = bytes(ptr)
            if not raw:
                return False
            return (sum(raw) / len(raw)) > 18.0
        except Exception:
            return True

    def _on_video_frame(self, frame):
        if frame.isValid():
            img = frame.toImage()
            if not img.isNull():
                self.current_frame_img = img
                if self.status_text:
                    self.status_text = ""
                if not self._has_hd_artwork and not self._emitted_frame_artwork and self.current_req_key:
                    self._frame_check_count += 1
                    if self._frame_check_count % 5 == 1 or self._frame_check_count >= 25:
                        if self._frame_check_count >= 25 or self._is_non_black_frame(img):
                            self._emitted_frame_artwork = True
                            self.video_frame_artwork_ready.emit(self.current_req_key, img.copy())
                if not self._repaint_suspended:
                    self.update()

    def seek_immediate(self, position_sec: float):
        """Immediately jumps embedded video playback to position_sec (for responsive +/-10s seek)."""
        self.pending_seek_sec = max(0.0, float(position_sec))
        if not self.player or not self.is_stream_loaded:
            return
        dur_ms = self.player.duration()
        target_ms = int(round(self.pending_seek_sec * 1000))
        if dur_ms > 0:
            target_ms = min(target_ms, max(0, dur_ms - 400))
        self.player.setPosition(max(0, target_ms))

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
            old_r = self.resolver
            self.resolver = None
            old_r.cancel()
            try:
                old_r.video_id_found.disconnect()
                old_r.intro_offset_found.disconnect()
                old_r.artwork_fetched.disconnect()
                old_r.resolved.disconnect()
                old_r.failed.disconnect()
            except Exception:
                pass
            # Always keep a reference until well after QThread teardown to prevent PyQt6 QThread GC abort!
            self._old_resolvers.append(old_r)
            from modules.qt_compat import QTimer
            if old_r.isRunning():
                old_r.finished.connect(lambda r=old_r: QTimer.singleShot(600, lambda rr=r: self._cleanup_old_resolver(rr)))
            else:
                QTimer.singleShot(600, lambda r=old_r: self._cleanup_old_resolver(r))

        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())

        self.is_stream_loaded = False
        self._artwork_only_mode = False
        self._has_hd_artwork = False
        self._emitted_frame_artwork = False
        self._frame_check_count = 0
        self.current_frame_img = QImage()
        self.status_text = ""
        if clear_artwork:
            self.fallback_pixmap = QPixmap()
            self.current_video_id = None
            self.current_req_key = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isVisible() and self._render_opacity > 0.5:
            # Only trigger play/pause when clicking strictly inside the visible 16:9 video frame
            # (never on empty transparent margins or while dismissing a popup!)
            if self.get_video_rect().contains(event.position()):
                self.clicked.emit()
                event.accept()
                return
        super().mousePressEvent(event)

    def get_video_rect(self, w: int = None, h: int = None) -> QRectF:
        """Returns the exact 16:9 video frame rect, reserving 34px below for the song title."""
        w = self.width() if w is None else w
        h = self.height() if h is None else h
        title_reserve = 34
        avail_h = max(48, h - title_reserve)
        target_ratio = 16.0 / 9.0
        if w / max(1, avail_h) > target_ratio:
            box_h = max(36, avail_h - 4)
            box_w = int(box_h * target_ratio)
        else:
            box_w = max(64, w - 4)
            box_h = int(box_w / target_ratio)

        x = (w - box_w) // 2
        y = max(2, (h - (box_h + title_reserve)) // 2)
        return QRectF(x, y, box_w, box_h)

    def paintEvent(self, event):
        if self._render_opacity <= 0.005:
            return
        painter = QPainter(self)
        if self._render_opacity < 0.995:
            painter.setOpacity(self._render_opacity)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = self.get_video_rect()
        x = int(rect.x())
        y = int(rect.y())
        box_w = int(rect.width())
        box_h = int(rect.height())

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
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr(self._app_lang, "video_waiting"))

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

