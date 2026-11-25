import asyncio
import time
from datetime import datetime, timezone
from modules.qt_compat import QObject, Signal, QThread

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus
    )
    from winsdk.windows.storage.streams import DataReader
    WINSDK_AVAILABLE = True
except Exception as e:
    print(f"[MediaListener Warning] winsdk import failed: {e}")
    WINSDK_AVAILABLE = False


class MediaState:
    def __init__(self, title="", artist="", album="", is_playing=False, position=0.0, duration=0.0, thumbnail_bytes=None):
        self.title = title
        self.artist = artist
        self.album = album
        self.is_playing = is_playing
        self.position = position
        self.duration = duration
        self.thumbnail_bytes = thumbnail_bytes
        self.created_at = time.time()

    def get_current_position(self) -> float:
        if self.is_playing:
            elapsed = time.time() - self.created_at
            return self.position + elapsed
        return self.position


def is_browser_junk_title(title: str, artist: str = "", app_id: str = "") -> bool:
    """Detect whether a title is a browser tab / page name rather than actual music playback."""
    if not title:
        return True
    t_lower = title.strip().lower()
    a_lower = (artist or "").strip().lower()

    # Exact non-music tab names
    junk_exact = {
        "new tab", "tab mới", "about:blank", "google", "chrome",
        "google chrome", "microsoft edge", "edge", "home", "trang chủ",
        "cài đặt", "settings", "history", "downloads", "extensions",
        "tiện ích mở rộng", "bookmarks", "dấu trang", "untitled", "untitled - google chrome"
    }
    if t_lower in junk_exact:
        return True

    # If no artist is reported (typical for general webpages, but NOT YouTube/Spotify)
    if not a_lower:
        for suffix in [" - google chrome", " - microsoft edge", " - brave", " - opera", " - firefox"]:
            if t_lower.endswith(suffix):
                return True
        known_sites = [
            "facebook", "shopee", "lazada", "tiki", "github", "vnexpress",
            "dantri", "tuoitre", "reddit", "twitter", "instagram", "tiktok"
        ]
        for site in known_sites:
            if site in t_lower and not ("ft." in t_lower or "feat" in t_lower or "-" in t_lower or "|" in t_lower):
                return True

    return False


class MediaListenerWorker(QObject):
    media_updated = Signal(object) # Emits MediaState
    session_closed = Signal()

    def __init__(self, poll_interval: float = 0.15):
        super().__init__()
        self.poll_interval = poll_interval
        self._running = True
        
        # State tracking across poll ticks
        self.current_title = None
        self.current_artist = None
        self.current_thumb_bytes = None
        self.is_playing = False
        self.last_raw_pos = None
        self.last_upd_time = None
        self.last_win_pos = 0.0
        self.last_win_time = time.time()
        self.last_active_media_state = None
        self.no_media_since = None

    @staticmethod
    def _compute_gsmtc_position(timeline, is_playing: bool, duration: float):
        """
        Computes exact current playback position from Windows GSMTC timeline.
        Chrome/Edge only updates timeline.position on play/pause/seek and stores the exact wall-clock
        timestamp in timeline.last_updated_time, so true position while playing is position + (now - last_updated_time).
        """
        raw_pos = timeline.position.total_seconds() if (timeline and timeline.position) else 0.0
        upd_time = getattr(timeline, "last_updated_time", None) if timeline else None
        has_valid_upd = bool(upd_time is not None and getattr(upd_time, "year", 0) >= 2020)

        if is_playing and has_valid_upd:
            try:
                age = (datetime.now(timezone.utc) - upd_time).total_seconds()
                max_age = (duration + 15.0) if (duration and duration > 0) else 7200.0
                if -2.0 <= age <= max_age:
                    est = max(0.0, raw_pos + max(0.0, age))
                    if duration and duration > 0:
                        est = min(duration, est)
                    return raw_pos, upd_time, est, True
            except Exception:
                pass

        return raw_pos, upd_time, max(0.0, raw_pos), (not is_playing and has_valid_upd)

    def stop(self):
        self._running = False

    def run(self):
        if not WINSDK_AVAILABLE:
            print("[MediaListenerWorker] winsdk not available, running dummy loop.")
            while self._running:
                QThread.msleep(1000)
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._poll_loop())
        finally:
            loop.close()

    async def _poll_loop(self):
        while self._running:
            try:
                state = await self._get_current_media_state()
                if state:
                    self.no_media_since = None
                    self.media_updated.emit(state)
                else:
                    if self.current_title is not None:
                        now = time.time()
                        if self.no_media_since is None:
                            self.no_media_since = now
                        elif now - self.no_media_since > 5.0: # Grace period of 5 seconds before closing
                            self.current_title = None
                            self.current_artist = None
                            self.last_active_media_state = None
                            self.session_closed.emit()
            except Exception as e:
                pass
            await asyncio.sleep(self.poll_interval)

    async def _get_best_session_data(self, manager):
        sessions = manager.get_sessions()
        curr_session = manager.get_current_session()
        
        candidates = []
        for s in sessions:
            try:
                props = await s.try_get_media_properties_async()
                if not props or not props.title:
                    continue
                title = props.title.strip()
                artist = (props.artist or "").strip()
                album = (props.album_title or "").strip()
                app_id = (s.source_app_user_model_id or "").lower()

                playback = s.get_playback_info()
                status = playback.playback_status if playback else PlaybackStatus.CLOSED
                is_playing = (status == PlaybackStatus.PLAYING)

                timeline = s.get_timeline_properties()
                duration = timeline.end_time.total_seconds() if (timeline and timeline.end_time) else 0.0
                raw_pos, upd_time, true_pos, has_valid_upd = self._compute_gsmtc_position(timeline, is_playing, duration)

                # Filter out obvious non-music browser tabs if not currently playing
                if is_browser_junk_title(title, artist, app_id) and not is_playing:
                    continue

                # Scoring: heavily favor active music playback
                score = 0
                if is_playing:
                    score += 1000
                if artist:
                    score += 300
                if duration > 15.0:
                    score += 200
                if "spotify" in app_id:
                    score += 100
                if s == curr_session:
                    score += 50
                # Stickiness to avoid switching when user clicks another tab in Chrome
                if self.current_title and title == self.current_title:
                    score += 600 if is_playing else 250

                candidates.append({
                    "score": score,
                    "session": s,
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "is_playing": is_playing,
                    "duration": duration,
                    "raw_position": raw_pos,
                    "upd_time": upd_time,
                    "position": true_pos,
                    "has_valid_upd": has_valid_upd,
                    "app_id": app_id,
                    "thumbnail_ref": props.thumbnail
                })
            except Exception:
                continue

        if not candidates:
            if curr_session:
                try:
                    props = await curr_session.try_get_media_properties_async()
                    if props and props.title:
                        title = props.title.strip()
                        artist = (props.artist or "").strip()
                        app_id = (curr_session.source_app_user_model_id or "").lower()
                        if not is_browser_junk_title(title, artist, app_id):
                            playback = curr_session.get_playback_info()
                            is_playing = (playback.playback_status == PlaybackStatus.PLAYING) if playback else False
                            timeline = curr_session.get_timeline_properties()
                            dur = timeline.end_time.total_seconds() if (timeline and timeline.end_time) else 0.0
                            raw_pos, upd_time, true_pos, has_valid_upd = self._compute_gsmtc_position(timeline, is_playing, dur)
                            return {
                                "session": curr_session,
                                "title": title,
                                "artist": artist,
                                "album": (props.album_title or "").strip(),
                                "is_playing": is_playing,
                                "duration": dur,
                                "raw_position": raw_pos,
                                "upd_time": upd_time,
                                "position": true_pos,
                                "has_valid_upd": has_valid_upd,
                                "app_id": app_id,
                                "thumbnail_ref": props.thumbnail
                            }
                except Exception:
                    pass
            return None

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[0]

    async def _get_current_media_state(self) -> MediaState:
        try:
            manager = await MediaManager.request_async()
            if not manager:
                return None

            best = await self._get_best_session_data(manager)
            if not best:
                return None

            title = best["title"]
            artist = best["artist"]
            album = best["album"]
            win_is_playing = best["is_playing"]
            raw_pos = best.get("raw_position", best["position"])
            upd_time = best.get("upd_time")
            true_pos = best["position"]
            has_valid_upd = best.get("has_valid_upd", False)
            duration = best["duration"]
            app_id = best.get("app_id", "")

            # Guard against Chrome tab-switching mutating single session:
            # If we were tracking a song, and incoming candidate has no artist and is not playing (or is junk):
            # retain the last active song state rather than adopting a webpage title!
            if self.current_title and (title != self.current_title):
                if not win_is_playing and (not artist or is_browser_junk_title(title, artist, app_id)):
                    if self.last_active_media_state:
                        return self.last_active_media_state

            now = time.time()

            # 1. Song changed (or first startup)
            if title != self.current_title or artist != self.current_artist:
                was_tracking_prev = (self.current_title is not None)
                prev_raw_pos = self.last_raw_pos
                prev_upd_time = self.last_upd_time

                self.current_title = title
                self.current_artist = artist
                self.is_playing = win_is_playing
                self.current_thumb_bytes = await self._read_thumbnail_bytes(best.get("thumbnail_ref"))

                # Only reset stale position if switching from a previous song AND Chrome carried over the old timeline!
                # On initial app startup (was_tracking_prev == False), ALWAYS honor the true mid-song position!
                if was_tracking_prev and true_pos > 5.0:
                    stale_upd = (upd_time is not None and prev_upd_time is not None and upd_time == prev_upd_time)
                    stale_pos = (prev_raw_pos is not None and abs(raw_pos - prev_raw_pos) < 1.5)
                    if stale_upd or stale_pos:
                        true_pos = 0.0

                self.last_raw_pos = raw_pos
                self.last_upd_time = upd_time
                self.last_win_pos = true_pos
                self.last_win_time = now
                calc_position = true_pos
            else:
                # 2. Same song: Use exact GSMTC wall-clock position when available, or extrapolate smoothly
                if self.current_thumb_bytes is None and best.get("thumbnail_ref") is not None:
                    self.current_thumb_bytes = await self._read_thumbnail_bytes(best.get("thumbnail_ref"))

                if has_valid_upd:
                    # Exact drift-free position (handles continuous playback, pause, seek forward & seek back to 0:00!)
                    self.last_raw_pos = raw_pos
                    self.last_upd_time = upd_time
                    self.last_win_pos = true_pos
                    self.last_win_time = now
                    calc_position = true_pos
                else:
                    if raw_pos != self.last_raw_pos:
                        self.last_raw_pos = raw_pos
                        self.last_win_pos = raw_pos
                        self.last_win_time = now
                        calc_position = raw_pos
                    elif win_is_playing:
                        calc_position = self.last_win_pos + (now - self.last_win_time)
                    else:
                        calc_position = self.last_win_pos

                # 3. Handle Play / Pause state change
                if win_is_playing != self.is_playing:
                    self.is_playing = win_is_playing
                    self.last_win_pos = calc_position
                    self.last_win_time = now

            state = MediaState(
                title=title,
                artist=artist,
                album=album,
                is_playing=win_is_playing,
                position=calc_position,
                duration=duration,
                thumbnail_bytes=self.current_thumb_bytes
            )
            self.last_active_media_state = state
            return state
        except Exception as e:
            return None

    async def _read_thumbnail_bytes(self, thumb_ref) -> bytes:
        if not thumb_ref:
            return None
        try:
            stream = await asyncio.wait_for(thumb_ref.open_read_async(), timeout=1.5)
            size = stream.size
            if size <= 0 or size > 10 * 1024 * 1024:
                return None
            reader = DataReader(stream)
            await asyncio.wait_for(reader.load_async(size), timeout=1.5)
            buf = bytearray(size)
            reader.read_bytes(buf)
            return bytes(buf)
        except Exception:
            return None

    def send_control(self, action: str):
        if not WINSDK_AVAILABLE:
            return
        asyncio.run(self._async_send_control(action))

    async def _async_send_control(self, action: str):
        try:
            manager = await MediaManager.request_async()
            if not manager:
                return
            best = await self._get_best_session_data(manager)
            session = best["session"] if best else manager.get_current_session()
            if session:
                if action == "play_pause":
                    playback = session.get_playback_info()
                    if playback and playback.playback_status == PlaybackStatus.PLAYING:
                        await session.try_pause_async()
                    else:
                        await session.try_play_async()
                elif action == "next":
                    await session.try_skip_next_async()
                elif action == "prev":
                    await session.try_skip_previous_async()
        except Exception as e:
            print(f"[MediaControl Error] {e}")

