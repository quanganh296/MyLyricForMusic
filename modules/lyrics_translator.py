import re
from concurrent.futures import ThreadPoolExecutor
import requests
from modules.qt_compat import QThread, Signal

# Characters distinctive to Vietnamese (with diacritics)
_VI_CHARS_RE = re.compile(
    r'[ăâđêôơưĂÂĐÊÔƠƯáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]'
)
# Specific script detectors for accurate song-level source language locking
_JA_KANA_RE = re.compile(r'[\u3040-\u30ff]')
_KO_HANGUL_RE = re.compile(r'[\uac00-\ud7af]')
_CJK_HAN_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
_THAI_RE = re.compile(r'[\u0e00-\u0e7f]')
_CYRILLIC_RE = re.compile(r'[\u0400-\u04ff]')
_ARABIC_RE = re.compile(r'[\u0600-\u06ff]')

# Non-Latin scripts that benefit from romanization (Japanese, Chinese, Korean, Thai, Cyrillic, Arabic, Greek, Hindi)
_NON_LATIN_RE = re.compile(
    r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\u0e00-\u0e7f\u0400-\u04ff\u0600-\u06ff\u0370-\u03ff\u0900-\u097f]'
)
_PURE_ASCII_LATIN_RE = re.compile(r"^[A-Za-z0-9\s\.,!\?\'\"\-\(\)\[\]:;~&/]+$")


def has_non_latin_script(text: str) -> bool:
    return bool(_NON_LATIN_RE.search(text or ""))


def looks_like_vietnamese(lines: list) -> bool:
    """Fast local heuristic: skip network translation if song is clearly Vietnamese."""
    sample = " ".join(l.get("text", "") for l in lines[:15] if l.get("text"))
    if not sample:
        return False
    if has_non_latin_script(sample):
        return False
    vi_hits = len(_VI_CHARS_RE.findall(sample))
    return vi_hits >= 5


def detect_song_source_lang(lines: list) -> str:
    """
    Determines the primary source language across the entire song from script counts.
    Locking sl='ja'/'ko'/'zh-CN'/'th'/'ru' prevents GTX from misclassifying Kanji as Chinese
    or misclassifying mixed-English JP/KR songs as English!
    """
    sample = "\n".join(l.get("text", "") for l in lines[:40] if l.get("text"))
    if not sample:
        return "auto"
    kana_cnt = len(_JA_KANA_RE.findall(sample))
    hangul_cnt = len(_KO_HANGUL_RE.findall(sample))
    han_cnt = len(_CJK_HAN_RE.findall(sample))
    thai_cnt = len(_THAI_RE.findall(sample))
    cyr_cnt = len(_CYRILLIC_RE.findall(sample))
    arab_cnt = len(_ARABIC_RE.findall(sample))

    if kana_cnt >= 3:
        return "ja"
    if hangul_cnt >= 3:
        return "ko"
    if han_cnt >= 4:
        return "zh-CN"
    if thai_cnt >= 4:
        return "th"
    if cyr_cnt >= 4:
        return "ru"
    if arab_cnt >= 4:
        return "ar"
    return "auto"


def _is_non_translatable(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    if s.startswith("[") and s.endswith("]"):
        return True
    if s in ("...", "…", "-", "—", "\u266a", "\u266b") or "(nhạc dạo đầu)" in s.lower():
        return True
    if not re.search(
        r'[A-Za-z0-9\u00C0-\u024F\u1E00-\u1EFF\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0e00-\u0e7f\u0400-\u04ff\u0600-\u06ff]',
        s
    ):
        return True
    return False


def _normalize_lang(code: str) -> str:
    if not code:
        return ""
    c = code.lower().strip()
    if c.startswith("zh"):
        return "zh"
    return c.split("-")[0]


def _capitalize_clean(text: str) -> str:
    s = re.sub(r'\s+', ' ', (text or "")).strip()
    if not s:
        return ""
    # Clean stray spaces before punctuation
    s = re.sub(r'\s+([,\.\!\?])', r'\1', s)
    if s[0].islower():
        return s[0].upper() + s[1:]
    return s


def _gtx_request(text: str, source_lang: str, target_lang: str, want_trans: bool = True, want_rm: bool = False, session=None) -> tuple:
    """Calls Google Translate free GTX endpoint with keep-alive session; returns (translated_text, romanized_text, detected_lang)."""
    url = "https://translate.googleapis.com/translate_a/single"
    params = [
        ("client", "gtx"),
        ("sl", source_lang or "auto"),
        ("tl", target_lang),
    ]
    if want_trans:
        params.append(("dt", "t"))
    if want_rm:
        params.append(("dt", "rm"))
    params.append(("q", text))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    requester = session if session is not None else requests
    resp = requester.get(url, params=params, headers=headers, timeout=5)
    resp.encoding = "utf-8"
    if resp.status_code != 200:
        return None, "", ""
    data = resp.json()
    if not data or not isinstance(data, list) or not data[0]:
        return None, "", ""
    segs = data[0]
    translated = "".join(seg[0] for seg in segs if seg and len(seg) > 0 and seg[0]) if want_trans else ""
    romanized = "".join(seg[3] for seg in segs if seg and len(seg) > 3 and seg[3]) if want_rm else ""
    detected = data[2] if len(data) > 2 and isinstance(data[2], str) else ""
    return translated, romanized, detected


def _clean_trans_line(orig_text: str, tr: str) -> str:
    c = _capitalize_clean(tr)
    if not c or c.lower() == orig_text.strip().lower():
        return ""
    return c


def _clean_romaji_line(orig_text: str, rm: str) -> str:
    if not has_non_latin_script(orig_text) or not rm:
        return ""
    c = _capitalize_clean(rm)
    if not c or c.lower() == orig_text.strip().lower():
        return ""
    return c


def _prioritize_items(items: list, start_idx: int) -> list:
    """Reorders items so the currently playing line and upcoming lines translate FIRST (<0.5s!)."""
    if not items or start_idx <= 0:
        return list(items)
    pivot = max(0, start_idx - 2)
    ahead = [it for it in items if it[0] >= pivot]
    behind = [it for it in items if it[0] < pivot]
    return ahead + behind


def _translate_group(items: list, source_lang: str, target_lang: str, out_trans: list,
                     session=None, cancel_cb=None, progress_cb=None) -> str:
    """
    Translates [(orig_idx, text), ...] with clean '\\n' boundaries, keep-alive session,
    parallel sub-batch mismatch recovery, cancellation checks, and per-batch streaming callback!
    """
    detected_lang = ""
    batches = []
    curr, curr_len = [], 0
    for idx, t in items:
        if curr and (len(curr) >= 14 or curr_len + len(t) > 950):
            batches.append(curr)
            curr, curr_len = [], 0
        curr.append((idx, t))
        curr_len += len(t) + 1
    if curr:
        batches.append(curr)

    norm_tgt = _normalize_lang(target_lang)

    for b_idx, batch in enumerate(batches):
        if cancel_cb and cancel_cb():
            return detected_lang

        joined = "\n".join(t for _, t in batch)
        try:
            trans_block, _, det = _gtx_request(joined, source_lang, target_lang, want_trans=True, want_rm=False, session=session)
        except Exception as e:
            print(f"[LyricsTranslator Trans Error] {e}")
            continue

        if b_idx == 0 and det:
            detected_lang = det
            if source_lang == "auto":
                norm_det = _normalize_lang(det)
                is_false_latin = (norm_tgt in ("en", "vi") and has_non_latin_script(joined))
                if norm_det == norm_tgt and not is_false_latin:
                    return det

        if not trans_block:
            continue

        parts = [p.strip() for p in trans_block.splitlines()]
        # Strip trailing empty lines if GTX added a trailing newline
        while len(parts) > len(batch) and parts and not parts[-1]:
            parts.pop()

        if len(parts) == len(batch):
            for (orig_idx, orig_text), tr_str in zip(batch, parts):
                out_trans[orig_idx] = _clean_trans_line(orig_text, tr_str)
        else:
            # Parallel sub-batch alignment fallback (4 workers -> ~0.6s instead of 30s sequential!)
            subs = [batch[start:start + 3] for start in range(0, len(batch), 3)]

            def _resolve_sub(sub):
                if cancel_cb and cancel_cb():
                    return []
                res_pairs = []
                try:
                    sub_tr, _, _ = _gtx_request("\n".join(t for _, t in sub), source_lang, target_lang, want_trans=True, want_rm=False)
                    sp = [p.strip() for p in (sub_tr or "").splitlines()]
                    while len(sp) > len(sub) and sp and not sp[-1]:
                        sp.pop()
                    if len(sp) == len(sub):
                        for (orig_idx, orig_text), tr_s in zip(sub, sp):
                            res_pairs.append((orig_idx, _clean_trans_line(orig_text, tr_s)))
                    else:
                        for orig_idx, orig_text in sub:
                            if cancel_cb and cancel_cb():
                                break
                            one_tr, _, _ = _gtx_request(orig_text, source_lang, target_lang, want_trans=True, want_rm=False)
                            res_pairs.append((orig_idx, _clean_trans_line(orig_text, one_tr or "")))
                except Exception:
                    pass
                return res_pairs

            with ThreadPoolExecutor(max_workers=min(4, max(1, len(subs)))) as pool:
                for pairs in pool.map(_resolve_sub, subs):
                    for orig_idx, val in pairs:
                        out_trans[orig_idx] = val

        if progress_cb and not (cancel_cb and cancel_cb()):
            progress_cb(detected_lang)

    return detected_lang


def _romanize_group(items: list, source_lang: str, target_lang: str, out_rm: list,
                    session=None, cancel_cb=None, progress_cb=None):
    """
    Fetches exact 1-to-1 source romanization (Romaji / Revised Romanization / Pinyin / Latin)
    using '\\n|\\n' delimiters ONLY for non-Latin lines, with keep-alive & per-batch streaming!
    """
    if not items:
        return
    batches = []
    curr, curr_len = [], 0
    for idx, t in items:
        safe_t = t.replace("|", "/")
        if curr and (len(curr) >= 12 or curr_len + len(safe_t) > 850):
            batches.append(curr)
            curr, curr_len = [], 0
        curr.append((idx, safe_t, t))
        curr_len += len(safe_t) + 3
    if curr:
        batches.append(curr)

    for batch in batches:
        if cancel_cb and cancel_cb():
            return
        joined = "\n|\n".join(st for _, st, _ in batch)
        try:
            _, rm_block, _ = _gtx_request(joined, source_lang, target_lang, want_trans=False, want_rm=True, session=session)
        except Exception as e:
            print(f"[LyricsTranslator Romaji Error] {e}")
            continue

        r_parts = [p.strip() for p in rm_block.split("|")] if rm_block.strip() else []
        if len(r_parts) == len(batch):
            for (orig_idx, _, orig_text), rm in zip(batch, r_parts):
                out_rm[orig_idx] = _clean_romaji_line(orig_text, rm)
        else:
            subs = [batch[start:start + 3] for start in range(0, len(batch), 3)]

            def _resolve_rm_sub(sub):
                if cancel_cb and cancel_cb():
                    return []
                res_pairs = []
                try:
                    _, sub_rm, _ = _gtx_request("\n|\n".join(st for _, st, _ in sub), source_lang, target_lang, want_trans=False, want_rm=True)
                    sp = [p.strip() for p in sub_rm.split("|")] if sub_rm.strip() else []
                    if len(sp) == len(sub):
                        for (orig_idx, _, orig_text), rm in zip(sub, sp):
                            res_pairs.append((orig_idx, _clean_romaji_line(orig_text, rm)))
                    else:
                        for orig_idx, _, orig_text in sub:
                            if cancel_cb and cancel_cb():
                                break
                            _, one_rm, _ = _gtx_request(orig_text, source_lang, target_lang, want_trans=False, want_rm=True)
                            res_pairs.append((orig_idx, _clean_romaji_line(orig_text, one_rm or "")))
                except Exception:
                    pass
                return res_pairs

            with ThreadPoolExecutor(max_workers=min(4, max(1, len(subs)))) as pool:
                for pairs in pool.map(_resolve_rm_sub, subs):
                    for orig_idx, val in pairs:
                        out_rm[orig_idx] = val

        if progress_cb and not (cancel_cb and cancel_cb()):
            progress_cb("")


def translate_and_romanize_lines(lines: list, target_lang: str = "vi", start_idx: int = 0,
                                 cancel_cb=None, on_partial=None) -> tuple:
    """
    Auto-detects song language, prioritizes currently playing lines first, streams partial batches
    immediately via on_partial(translations, romanizations, detected), and uses HTTP keep-alive.
    Returns (translations_list, romanizations_list, detected_lang).
    """
    if not lines:
        return [], [], ""

    n = len(lines)
    norm_tgt = _normalize_lang(target_lang)
    if norm_tgt == "vi" and looks_like_vietnamese(lines):
        return [""] * n, [""] * n, "vi"

    song_lang = detect_song_source_lang(lines)
    if song_lang != "auto" and _normalize_lang(song_lang) == norm_tgt:
        return [""] * n, [""] * n, song_lang

    translations = [""] * n
    romanizations = [""] * n

    primary_items = []
    ascii_items = []
    non_latin_rm_items = []

    for i, l in enumerate(lines):
        raw_t = (l.get("text") or "").replace("\n", " ").strip()
        if _is_non_translatable(raw_t):
            continue
        if song_lang in ("ja", "ko", "zh-CN", "th", "ru", "ar") and _PURE_ASCII_LATIN_RE.match(raw_t):
            if norm_tgt != "en":
                ascii_items.append((i, raw_t))
        else:
            primary_items.append((i, raw_t))
        if has_non_latin_script(raw_t):
            non_latin_rm_items.append((i, raw_t))

    if not primary_items and not ascii_items:
        return translations, romanizations, song_lang if song_lang != "auto" else ""

    # Prioritize currently playing region FIRST so live lyrics get translations in <0.5s!
    primary_items = _prioritize_items(primary_items, start_idx)
    ascii_items = _prioritize_items(ascii_items, start_idx)
    non_latin_rm_items = _prioritize_items(non_latin_rm_items, start_idx)

    detected = song_lang if song_lang != "auto" else ""

    def _emit_partial(det_hint=""):
        nonlocal detected
        if not detected and det_hint:
            detected = det_hint
        if on_partial:
            on_partial(list(translations), list(romanizations), detected)

    with requests.Session() as sess:
        # 1. Translate primary language lines cleanly with '\n' context & locked source_lang
        if primary_items and not (cancel_cb and cancel_cb()):
            det_p = _translate_group(
                primary_items, song_lang, target_lang, translations,
                session=sess, cancel_cb=cancel_cb, progress_cb=_emit_partial
            )
            if not detected and det_p:
                detected = det_p
                if _normalize_lang(det_p) == norm_tgt and not non_latin_rm_items:
                    return [""] * n, [""] * n, det_p

        # 2. Translate embedded English lines (e.g. "Cry for me", "Time goes though") cleanly with sl='en'
        if ascii_items and not (cancel_cb and cancel_cb()):
            _translate_group(
                ascii_items, "en", target_lang, translations,
                session=sess, cancel_cb=cancel_cb, progress_cb=_emit_partial
            )

        # 3. Fetch exact 1-to-1 romanization ONLY for non-Latin lines with locked source_lang
        if non_latin_rm_items and not (cancel_cb and cancel_cb()):
            rm_lang = song_lang if song_lang != "auto" else (detected or "auto")
            _romanize_group(
                non_latin_rm_items, rm_lang, target_lang, romanizations,
                session=sess, cancel_cb=cancel_cb, progress_cb=_emit_partial
            )

    return translations, romanizations, detected


def translate_lyric_lines(lines: list, target_lang: str = "vi") -> tuple:
    """Backward-compatible helper returning (translations_list, detected_lang)."""
    trans, _romaji, det = translate_and_romanize_lines(lines, target_lang)
    return trans, det


class TranslationWorker(QThread):
    """Non-blocking streaming QThread to auto-detect, romanize & translate lyrics progressively (<0.5s first line!)."""
    partial_translated = Signal(str, str, list, list, str)  # req_key, target_lang, trans_list, romaji_list, detected
    translated = Signal(str, str, list, list, str)          # final complete result

    def __init__(self, req_key: str, lines: list, target_lang: str = "vi", start_idx: int = 0):
        super().__init__()
        self.req_key = req_key
        self.lines = list(lines)
        self.target_lang = target_lang
        self.start_idx = max(0, int(start_idx or 0))
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return

        def _on_partial(tr_snap, rm_snap, det):
            if not self._cancelled:
                self.partial_translated.emit(self.req_key, self.target_lang, tr_snap, rm_snap, det)

        trans_list, romaji_list, det = translate_and_romanize_lines(
            self.lines,
            self.target_lang,
            start_idx=self.start_idx,
            cancel_cb=lambda: self._cancelled,
            on_partial=_on_partial,
        )
        if not self._cancelled:
            self.translated.emit(self.req_key, self.target_lang, trans_list, romaji_list, det)
