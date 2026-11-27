import math
import re
from modules.qt_compat import (
    QWidget, QPushButton, QMenu, Qt, Signal, QTimer,
    QPainter, QPainterPath, QColor, QFont, QFontMetrics,
    QPen, QRect, QRectF, QSize, QSizePolicy
)
from modules.icon_factory import IconFactory


_CJK_CHAR_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\u0e00-\u0e7f]')
_TOKEN_SPLIT_RE = re.compile(
    r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]'
    r'|\s+'
    r'|[^\s\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+'
)
_VOWEL_GROUP_RE = re.compile(
    r'[aeiouyàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]+',
    re.IGNORECASE
)


def _count_line_syllables(text: str) -> float:
    """Estimates vocal syllable count for Vietnamese, English, and CJK lines."""
    if not text:
        return 1.0
    cjk_count = len(_CJK_CHAR_RE.findall(text))
    non_cjk = _CJK_CHAR_RE.sub(" ", text)
    words = [w for w in re.split(r'\s+', non_cjk.strip()) if re.search(r'[a-zA-Z0-9\u00c0-\u024f\u1e00-\u1eff]', w)]
    lat_syl = 0.0
    for w in words:
        v_groups = len(_VOWEL_GROUP_RE.findall(w))
        # Vietnamese words are typically 1 syllable; longer English words scale with vowel groups
        lat_syl += max(1.0, min(4.0, float(v_groups)))
    return max(1.0, float(cjk_count) + lat_syl)


def build_karaoke_word_schedule(lines: list, idx: int) -> list:
    """
    Computes exact word/character highlight intervals [{"text", "start", "end", "is_space"}]
    for lines[idx], automatically adapting speed to BOTH slow ballads AND fast rap verses!
    Uses true enhanced LRC <mm:ss.xx> word timestamps when present, otherwise computes
    local tempo from surrounding lines + syllable & punctuation breath weighting.
    """
    if not lines or idx < 0 or idx >= len(lines):
        return []

    line = lines[idx]
    text = (line.get("text") or "").strip()
    if not text:
        return []

    t_start = float(line.get("time", 0.0))

    # 1. Exact enhanced word-level LRC timestamps (<mm:ss.xx>) if present
    explicit_words = line.get("words")
    if isinstance(explicit_words, list) and len(explicit_words) >= 2:
        next_line_t = float(lines[idx + 1]["time"]) if idx + 1 < len(lines) else (t_start + 3.5)
        out = []
        for wi, w in enumerate(explicit_words):
            ws = float(w.get("time", t_start))
            if wi + 1 < len(explicit_words):
                we = max(ws + 0.05, float(explicit_words[wi + 1].get("time", ws + 0.25)))
            else:
                we = max(ws + 0.12, min(next_line_t, ws + 0.85))
            wt = w.get("text") or ""
            if not out:
                wt = wt.lstrip()
            if not wt:
                continue
            out.append({"text": wt, "start": ws, "end": we, "is_space": wt.isspace()})
        if out:
            return out

    # 2. Estimate local vocal tempo (syllables/sec) from nearby non-break lines [-2..+2]
    total_syl = 0.0
    total_dur = 0.0
    for j in range(max(0, idx - 2), min(len(lines) - 1, idx + 3)):
        gap = float(lines[j + 1]["time"]) - float(lines[j]["time"])
        if 0.35 <= gap <= 7.5:
            syl = _count_line_syllables(lines[j].get("text", ""))
            total_syl += syl
            total_dur += gap

    local_rate = (total_syl / total_dur) if total_dur >= 0.6 else 3.2
    local_rate = max(1.1, min(11.5, local_rate))  # Supports slow 1.1 syl/s ballad up to 11.5 syl/s fast rap!

    cur_syl = _count_line_syllables(text)
    est_sing_dur = cur_syl / local_rate

    if idx + 1 < len(lines):
        raw_gap = max(0.25, float(lines[idx + 1]["time"]) - t_start)
        # If gap is a normal vocal phrase (ballad OR fast rap), lock tightly to raw_gap!
        # Only cap when raw_gap clearly includes a long instrumental pause after a short phrase.
        if raw_gap <= max(est_sing_dur * 1.50, 2.6):
            active_dur = raw_gap * 0.94
        else:
            active_dur = min(raw_gap * 0.90, max(est_sing_dur * 1.18, 2.0))
    else:
        active_dur = max(1.4, min(6.0, est_sing_dur * 1.05))

    # 3. Split into renderable tokens & assign phonetic + punctuation pause weights
    raw_tokens = _TOKEN_SPLIT_RE.findall(text)
    if not raw_tokens:
        return [{"text": text, "start": t_start, "end": t_start + active_dur, "is_space": False}]

    weights = []
    pauses = []
    for tok in raw_tokens:
        if tok.isspace():
            weights.append(0.08)
            pauses.append(0.0)
            continue

        if _CJK_CHAR_RE.search(tok):
            w = 1.0
        else:
            core = re.sub(r'[^\w\u00c0-\u024f\u1e00-\u1eff]', '', tok)
            if not core:
                w = 0.20
            else:
                vg = len(_VOWEL_GROUP_RE.findall(core))
                # Blend vowel groups & char length so multi-syllable English words take longer than 'I'/'a'
                w = max(0.75, min(3.8, 0.65 * max(1, vg) + 0.10 * len(core)))

        # Natural breath pause after punctuation marks
        p = 0.0
        stripped = tok.rstrip()
        if stripped.endswith((",", "、", "，")):
            p = 0.75
        elif stripped.endswith((".", "!", "?", ";", "…", "。", "！", "？")):
            p = 1.10

        weights.append(w)
        pauses.append(p)

    # Last token does not need a trailing breath pause
    if pauses:
        pauses[-1] = 0.0

    total_w = sum(weights) + sum(pauses)
    if total_w <= 0.0:
        total_w = 1.0

    schedule = []
    cursor = t_start
    for tok, w, p in zip(raw_tokens, weights, pauses):
        dur = active_dur * (w / total_w)
        is_sp = tok.isspace()
        end_t = cursor + (max(0.001, dur) if is_sp else max(0.012, dur))
        schedule.append({
            "text": tok,
            "start": cursor,
            "end": end_t,
            "is_space": is_sp,
        })
        cursor = end_t + active_dur * (p / total_w)

    # Guarantee total sweep never overflows active_dur even on ultra-fast 12+ syl/s rap bars
    if schedule and schedule[-1]["end"] > t_start + active_dur + 1e-6:
        actual_span = schedule[-1]["end"] - t_start
        if actual_span > 1e-6:
            ratio = active_dur / actual_span
            for item in schedule:
                item["start"] = t_start + (item["start"] - t_start) * ratio
                item["end"] = t_start + (item["end"] - t_start) * ratio

    return schedule


class ModeDropdownButton(QPushButton):
    """
    Sleek single-pill mode selector button with active mode icon, name, and right-aligned
    down-chevron arrow. Clicking opens a dark-glass dropdown menu listing all 3 modes.
    """
    mode_selected = Signal(int)

    MODE_META = {
        1: ("Video", "film", "Mode 1: Video bên phải + Lyric bên trái"),
        2: ("Lyric", "align_center", "Mode 2: Chỉ hiện Lyric căn giữa"),
        3: ("Karaoke", "microphone", "Mode 3: Hát Karaoke chữ sáng từng từ"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = 1
        self._accent_hex = "#38bdf8"
        self._hovered = False
        self.setFixedHeight(26)
        self.setMinimumWidth(94)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.clicked.connect(self._open_menu)

    def set_mode_state(self, mode: int, accent_hex: str = None):
        self._mode = mode if mode in (1, 2, 3) else 1
        if accent_hex:
            self._accent_hex = accent_hex
        label, _, tip = self.MODE_META[self._mode]
        self.setToolTip(f"Đang chọn {label} — Nhấn để đổi chế độ hiển thị")
        # Size neatly to fit label + icon + chevron
        fm = QFontMetrics(QFont("Segoe UI", 9, QFont.Weight.Bold))
        needed = fm.horizontalAdvance(label) + 46
        self.setFixedWidth(max(92, needed))
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def _open_menu(self):
        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        accent = self._accent_hex or "#38bdf8"
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: rgba(18, 22, 34, 242);
                color: #f1f5f9;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
                padding: 5px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                font-weight: 600;
            }}
            QMenu::item {{
                padding: 7px 14px 7px 10px;
                border-radius: 5px;
                margin: 1px 0;
            }}
            QMenu::item:selected {{
                background-color: {accent};
                color: #09090b;
            }}
        """)

        for m_id in (1, 2, 3):
            name, icon_key, desc = self.MODE_META[m_id]
            label_txt = f" {name}  (Đang chọn)" if m_id == self._mode else f" {name}"
            act = menu.addAction(
                IconFactory.create_icon(icon_key, accent if m_id == self._mode else "#cbd5e1", 14),
                label_txt
            )
            act.setToolTip(desc)
            act.triggered.connect(lambda checked=False, mid=m_id: self.mode_selected.emit(mid))

        pos = self.mapToGlobal(self.rect().bottomLeft())
        pos.setY(pos.y() + 4)
        menu.exec(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        bg = QColor(self._accent_hex)
        if not bg.isValid():
            bg = QColor("#38bdf8")
        if self._hovered:
            bg = bg.lighter(110)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 6.0, 6.0)

        label, icon_key, _ = self.MODE_META[self._mode]
        fg = QColor("#09090b")

        # Left icon
        pix = IconFactory.create_pixmap(icon_key, "#09090b", 13)
        iy = int((self.height() - pix.height()) / 2)
        painter.drawPixmap(9, iy, pix)

        # Mode label text
        font = QFont("Segoe UI", 9)
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(fg)
        text_rect = QRectF(26, 0, self.width() - 46, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

        # Crisp vector down-chevron on right side
        cx = self.width() - 13.0
        cy = self.height() / 2.0 + 0.5
        pen = QPen(fg, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(cx - 3.5, cy - 1.8)
        path.lineTo(cx, cy + 1.8)
        path.lineTo(cx + 3.5, cy - 1.8)
        painter.drawPath(path)
        painter.end()


class KaraokeLyricWidget(QWidget):
    """
    High-FPS word-by-word Karaoke active lyric renderer:
    - Unsung text stays soft/dimmed; each word/character smoothly lights up left-to-right
      in exact sync with song tempo (both slow ballads and fast rap!).
    - Supports continuous horizontal alignment interpolation (0.0 Left -> 1.0 Center)
      for silky-smooth slide-to-center transitions when toggling Video OFF/ON.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(34)

        self._text = ""
        self._schedule = []
        self._playback_time = 0.0
        self._align_progress = 0.0  # 0.0 = Left, 1.0 = Center
        self._is_intro = False

        self._font_families = ["Segoe UI", "Yu Gothic UI", "Meiryo UI", "Malgun Gothic", "Microsoft YaHei UI", "Leelawadee UI"]
        self._font_px = 24
        self._lit_color = QColor("#7dd3fc")
        self._dim_color = QColor(255, 255, 255, 102)
        self._intro_color = QColor(255, 255, 255, 170)
        self._rows_cache = None
        self._cache_width = -1

    def set_style(self, families: list, font_px: int, lit_hex: str):
        changed = (
            self._font_families != families
            or self._font_px != font_px
            or self._lit_color.name().lower() != (lit_hex or "").lower()
        )
        self._font_families = list(families)
        self._font_px = max(14, int(font_px))
        c = QColor(lit_hex)
        if c.isValid():
            self._lit_color = c
        if changed:
            self._rows_cache = None
            self._recompute_min_height()
            self.update()

    def set_align_progress(self, p: float):
        p = max(0.0, min(1.0, float(p)))
        if abs(p - self._align_progress) > 0.001:
            self._align_progress = p
            self.update()

    def set_static_text(self, text: str):
        self._text = (text or "").strip()
        self._schedule = []
        self._is_intro = True
        self._rows_cache = None
        self._recompute_min_height()
        self.update()

    def set_lyric_line(self, lines: list, idx: int, placeholder_text: str = ""):
        if not lines or idx < 0 or idx >= len(lines):
            self._text = placeholder_text or "... (Nhạc dạo đầu) ..."
            self._schedule = []
            self._is_intro = True
        else:
            self._text = (lines[idx].get("text") or "").strip()
            self._schedule = build_karaoke_word_schedule(lines, idx)
            self._is_intro = False
        self._rows_cache = None
        self._recompute_min_height()
        self.update()

    def set_playback_time(self, t_sec: float):
        if abs(t_sec - self._playback_time) >= 0.008:
            self._playback_time = t_sec
            self.update()

    def _make_font(self, px: int = None) -> QFont:
        f = QFont()
        f.setFamilies(self._font_families)
        f.setPixelSize(px or self._font_px)
        f.setBold(True)
        return f

    def _layout_rows(self, avail_w: int):
        """Wraps scheduled tokens into crisp visual rows with exact x/width geometry."""
        avail_w = max(160, avail_w)
        if self._rows_cache is not None and self._cache_width == avail_w:
            return self._rows_cache

        font = self._make_font(self._font_px)
        fm = QFontMetrics(font)

        # Auto-shrink slightly if a single line is super long and would wrap past 3 rows
        chosen_px = self._font_px
        for scale in (1.0, 0.90, 0.80, 0.72, 0.64):
            test_px = max(13, int(round(self._font_px * scale)))
            f_test = self._make_font(test_px)
            fm_test = QFontMetrics(f_test)
            br = fm_test.boundingRect(QRect(0, 0, avail_w, 2000), Qt.TextFlag.TextWordWrap, self._text or "A")
            if br.height() <= fm_test.lineSpacing() * 2.6 or scale == 0.64:
                chosen_px = test_px
                font = f_test
                fm = fm_test
                break

        tokens = self._schedule if self._schedule else [
            {"text": self._text, "start": 0.0, "end": 0.0, "is_space": False}
        ]

        rows = []
        curr_row = []
        curr_x = 0.0
        for tok in tokens:
            t_str = tok["text"]
            tw = float(fm.horizontalAdvance(t_str))
            if curr_row and (curr_x + tw > avail_w) and not tok["is_space"]:
                # Trim trailing space on wrapped row
                while curr_row and curr_row[-1]["is_space"]:
                    curr_row.pop()
                row_w = (curr_row[-1]["x"] + curr_row[-1]["w"]) if curr_row else 0.0
                rows.append({"items": curr_row, "width": row_w})
                curr_row = []
                curr_x = 0.0
                if tok["is_space"]:
                    continue
            if not curr_row and tok["is_space"]:
                continue
            curr_row.append({
                "text": t_str,
                "start": tok["start"],
                "end": tok["end"],
                "is_space": tok["is_space"],
                "x": curr_x,
                "w": tw,
            })
            curr_x += tw

        if curr_row:
            while curr_row and curr_row[-1]["is_space"]:
                curr_row.pop()
            if curr_row:
                row_w = curr_row[-1]["x"] + curr_row[-1]["w"]
                rows.append({"items": curr_row, "width": row_w})

        line_h = fm.lineSpacing() + 4
        self._rows_cache = (font, fm, rows, line_h, chosen_px)
        self._cache_width = avail_w
        return self._rows_cache

    def _recompute_min_height(self):
        avail_w = max(240, self.width() - 8)
        _, _, rows, line_h, _ = self._layout_rows(avail_w)
        h = max(36, len(rows) * line_h + 10)
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rows_cache = None
        self._recompute_min_height()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        avail_w = max(160, w - 8)
        font, fm, rows, line_h, _ = self._layout_rows(avail_w)
        painter.setFont(font)

        if not rows:
            painter.end()
            return

        total_h = len(rows) * line_h
        y0 = max(2.0, (h - total_h) / 2.0)
        ascent = fm.ascent()
        t_now = self._playback_time

        for r_idx, row in enumerate(rows):
            row_w = row["width"]
            # Continuous horizontal alignment: 0.0 = Left (x=4), 1.0 = Exact Center ((w - row_w) / 2)
            left_x = 4.0
            center_x = max(4.0, (w - row_w) / 2.0)
            offset_x = left_x + (center_x - left_x) * self._align_progress
            row_top = y0 + r_idx * line_h
            baseline = row_top + ascent + 2.0

            if self._is_intro:
                painter.setPen(self._intro_color)
                for it in row["items"]:
                    painter.drawText(int(round(offset_x + it["x"])), int(round(baseline)), it["text"])
                continue

            for it in row["items"]:
                tx = offset_x + it["x"]
                tw = it["w"]
                txt = it["text"]
                if not txt:
                    continue

                if t_now >= it["end"]:
                    # Fully sung -> glowing bright active color!
                    painter.setPen(QColor(0, 0, 0, 95))
                    painter.drawText(int(round(tx)) + 1, int(round(baseline)) + 1, txt)
                    painter.setPen(self._lit_color)
                    painter.drawText(int(round(tx)), int(round(baseline)), txt)
                elif t_now <= it["start"]:
                    # Not sung yet -> soft dimmed text
                    painter.setPen(self._dim_color)
                    painter.drawText(int(round(tx)), int(round(baseline)), txt)
                else:
                    # Currently singing -> pixel-accurate left-to-right wipe!
                    span = max(0.015, it["end"] - it["start"])
                    frac = max(0.0, min(1.0, (t_now - it["start"]) / span))
                    split_x = tx + tw * frac

                    # 1. Draw dim unsung base
                    painter.setPen(self._dim_color)
                    painter.drawText(int(round(tx)), int(round(baseline)), txt)

                    # 2. Clip to [tx .. split_x] and draw glowing lit sweep!
                    painter.save()
                    painter.setClipRect(QRectF(tx - 1.0, row_top - 4.0, max(0.0, split_x - tx + 1.0), line_h + 8.0))
                    painter.setPen(QColor(0, 0, 0, 95))
                    painter.drawText(int(round(tx)) + 1, int(round(baseline)) + 1, txt)
                    painter.setPen(self._lit_color)
                    painter.drawText(int(round(tx)), int(round(baseline)), txt)
                    painter.restore()

        painter.end()


class SplitTransitionStage(QWidget):
    """
    Smooth 60-FPS animated stage holding lyrics_widget (left/center) and video_display (right).
    When toggling Video OFF in Karaoke Mode:
      - Video rapidly glides LEFT while fading smoothly to 0% opacity and disappearing.
      - Lyrics smoothly glide RIGHT and continuously align to stop cleanly at exact CENTER!
    When toggling Video ON:
      - Smooth reverse transition back to Split (Lyrics Left | Video Right).
    """

    def __init__(self, lyrics_widget: QWidget, video_display: QWidget, parent=None):
        super().__init__(parent)
        self.lyrics_widget = lyrics_widget
        self.video_display = video_display
        self.lyrics_widget.setParent(self)
        self.video_display.setParent(self)
        self.setMouseTracking(True)

        self._video_shown = True
        self._animating = False
        self._anim_target_show = True
        self._anim_step = 0
        self._anim_total_steps = 22  # ~352ms at 16ms/frame (~60 FPS)
        self._on_progress_cb = None
        self._on_finish_cb = None

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_animation)

    def set_callbacks(self, on_progress=None, on_finish=None):
        self._on_progress_cb = on_progress
        self._on_finish_cb = on_finish

    def _split_rects(self):
        w = max(1, self.width())
        h = max(1, self.height())
        gap = 16
        left_w = max(180, int((w - gap) * 12 / 21))
        right_x = left_w + gap
        right_w = max(140, w - right_x)
        return QRect(0, 0, left_w, h), QRect(right_x, 0, right_w, h), QRect(0, 0, w, h)

    def set_video_visible(self, show: bool, animate: bool = False):
        self._anim_timer.stop()
        self._animating = False
        show = bool(show)

        if not animate or self.width() < 80:
            self._video_shown = show
            left_r, right_r, full_r = self._split_rects()
            if show:
                self.lyrics_widget.setGeometry(left_r)
                self.video_display.setGeometry(right_r)
                self.video_display.set_render_opacity(1.0)
                self.video_display.setVisible(True)
                if self._on_progress_cb:
                    self._on_progress_cb(0.0)  # 0.0 = left aligned
            else:
                self.video_display.setVisible(False)
                self.video_display.set_render_opacity(1.0)
                self.lyrics_widget.setGeometry(full_r)
                if self._on_progress_cb:
                    self._on_progress_cb(1.0)  # 1.0 = centered
            if self._on_finish_cb:
                self._on_finish_cb(show)
            return

        # Start smooth 60 FPS directional animation!
        self._anim_target_show = show
        self._anim_step = 0
        self._animating = True
        self.video_display.setVisible(True)
        # Keep lyrics on top so fading video glides cleanly behind without covering lyrics
        self.lyrics_widget.raise_()
        self._tick_animation()
        self._anim_timer.start()

    def _tick_animation(self):
        self._anim_step += 1
        raw_t = min(1.0, self._anim_step / float(self._anim_total_steps))
        # Smooth OutCubic deceleration curve
        ease = 1.0 - (1.0 - raw_t) ** 3

        left_r, right_r, full_r = self._split_rects()
        w = max(1, self.width())
        h = max(1, self.height())

        if not self._anim_target_show:
            # --- TURNING VIDEO OFF ---
            # 1. Video glides RAPIDLY LEFT and fades smoothly to 0
            fast_t = min(1.0, raw_t * 1.45)
            fast_ease = 1.0 - (1.0 - fast_t) ** 3
            vx = int(round(right_r.x() - fast_ease * (w * 0.34)))
            v_alpha = max(0.0, 1.0 - raw_t * 1.50)
            self.video_display.setGeometry(vx, 0, right_r.width(), h)
            self.video_display.set_render_opacity(v_alpha)

            # 2. Lyrics glide RIGHT and settle smoothly at exact CENTER!
            # Phase A (0..0.72): slide lyrics block rightward while aligning Left -> Center
            # Phase B (0.72..1.0): expand width symmetrically around exact w/2 (zero text jump!)
            center_start_x = (w - left_r.width()) / 2.0
            if raw_t < 0.72:
                slide_p = 1.0 - (1.0 - (raw_t / 0.72)) ** 3
                lx = int(round(slide_p * center_start_x))
                lw = left_r.width()
                self.lyrics_widget.setGeometry(lx, 0, lw, h)
                if self._on_progress_cb:
                    self._on_progress_cb(slide_p)
            else:
                settle_p = (raw_t - 0.72) / 0.28
                settle_ease = 1.0 - (1.0 - settle_p) ** 3
                lx = int(round(center_start_x * (1.0 - settle_ease)))
                lw = int(round(left_r.width() + (w - left_r.width()) * settle_ease))
                self.lyrics_widget.setGeometry(lx, 0, lw, h)
                if self._on_progress_cb:
                    self._on_progress_cb(1.0)
        else:
            # --- TURNING VIDEO ON ---
            # 1. Lyrics glide smoothly LEFT from center to left split
            lw = int(round(w + (left_r.width() - w) * ease))
            lx = int(round(((w - lw) / 2.0) * (1.0 - ease)))
            self.lyrics_widget.setGeometry(lx, 0, lw, h)
            if self._on_progress_cb:
                self._on_progress_cb(1.0 - ease)

            # 2. Video glides in smoothly from left-inward and fades in (0 -> 1)
            vx = int(round(right_r.x() - (1.0 - ease) * (w * 0.16)))
            self.video_display.setGeometry(vx, 0, right_r.width(), h)
            self.video_display.set_render_opacity(min(1.0, ease * 1.15))

        if raw_t >= 1.0:
            self._anim_timer.stop()
            self._animating = False
            self._video_shown = self._anim_target_show
            if self._video_shown:
                self.lyrics_widget.setGeometry(left_r)
                self.video_display.setGeometry(right_r)
                self.video_display.set_render_opacity(1.0)
                self.video_display.setVisible(True)
                if self._on_progress_cb:
                    self._on_progress_cb(0.0)
            else:
                self.video_display.setVisible(False)
                self.video_display.set_render_opacity(1.0)
                self.lyrics_widget.setGeometry(full_r)
                if self._on_progress_cb:
                    self._on_progress_cb(1.0)
            if self._on_finish_cb:
                self._on_finish_cb(self._video_shown)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._animating:
            left_r, right_r, full_r = self._split_rects()
            if self._video_shown:
                self.lyrics_widget.setGeometry(left_r)
                self.video_display.setGeometry(right_r)
            else:
                self.lyrics_widget.setGeometry(full_r)
