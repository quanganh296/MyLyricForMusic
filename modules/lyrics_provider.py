import re
import unicodedata
import urllib.parse
import requests


_CJK_SCRIPT_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]')
_CJK_RUN_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+')
_LRC_OFFSET_TAG_RE = re.compile(r'^\[offset\s*:\s*([+-]?\d+)\s*\]$', re.IGNORECASE)
_LRC_CREDIT_LINE_RE = re.compile(
    "(?i)^\\s*(?:"
    "(?:bài\\s*hát|ca\\s*sĩ|sáng\\s*tác|thể\\s*hiện|nhạc\\s*sĩ|hòa\\s*âm|phối\\s*khí|lời\\s*bài\\s*hát|"
    "title|artist|album|composer|lyricist|arranger|producer|performed\\s*by|written\\s*by|produced\\s*by|"
    "by|singer|vocal|lyrics\\s*by|music\\s*by)\\s*[:：\\-]|"
    "(?:作词|作詞|作曲|编曲|編曲|演唱|制作人|製作人|混音|监制|監製|词|詞|曲|歌|原唱|翻唱)\\s*[:：]|"
    "[\u266a\u266b\U0001f3b5\U0001f3b6\\*\\-~=_•·\\.]+$"
    ")"
)
_INTRO_OFFSET_CACHE = {}


def fetch_youtube_intro_offset(video_id: str, timeout: float = 2.5) -> float:
    """
    Queries SponsorBlock's public music_offtopic API for non-music cinematic intro duration on
    YouTube Official MVs (e.g. [0.0, 12.145] -> returns 12.15s). Only counts segments starting
    near 0:00 (start <= 3.0s) so outro/credits segments NEVER falsely shift lyrics!
    """
    if not video_id or len(video_id) != 11:
        return 0.0
    if video_id in _INTRO_OFFSET_CACHE:
        return _INTRO_OFFSET_CACHE[video_id]
    intro_end = 0.0
    try:
        url = f"https://sponsor.ajay.app/api/skipSegments?videoID={video_id}&category=music_offtopic"
        resp = requests.get(
            url,
            headers={"User-Agent": "LyricNow/1.2 (Windows Desktop Lyrics App)"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            segs = resp.json()
            if isinstance(segs, list):
                for seg in segs:
                    pair = seg.get("segment")
                    if isinstance(pair, list) and len(pair) == 2:
                        s_t = float(pair[0] or 0.0)
                        e_t = float(pair[1] or 0.0)
                        if s_t <= 3.0 and 3.0 <= e_t <= 90.0:
                            intro_end = max(intro_end, round(e_t, 2))
    except Exception:
        pass
    _INTRO_OFFSET_CACHE[video_id] = intro_end
    if len(_INTRO_OFFSET_CACHE) > 128:
        _INTRO_OFFSET_CACHE.pop(next(iter(_INTRO_OFFSET_CACHE)))
    return intro_end


class LyricsProvider:
    def __init__(self, cache_manager=None):
        self.cache = cache_manager
        self.headers = {
            "User-Agent": "LyricOverLayPrivate/1.0 (Windows Desktop Lyrics App)"
        }

    def _has_cjk(self, text: str) -> bool:
        return bool(_CJK_SCRIPT_RE.search(text or ""))

    def parse_lrc(self, lrc_text: str, duration: float = 210.0):
        """
        Parses LRC formatted or plain text lyrics.
        If plain text without timestamps, auto-distributes timestamps across song duration.
        """
        if not lrc_text:
            return []

        lines = []
        pattern = re.compile(r'\[(\d+):(\d+)(?:[\.\:](\d+))?\]')
        inline_ts_pattern = re.compile(r'<(\d+):(\d+)(?:[\.\:](\d+))?>')
        
        has_timestamps = False
        lrc_header_offset_sec = 0.0
        raw_lines = lrc_text.splitlines()

        def _parse_ts(m_grp1, m_grp2, m_grp3) -> float:
            minutes = int(m_grp1)
            seconds = int(m_grp2)
            if m_grp3:
                fraction = int(m_grp3) / 1000.0 if len(m_grp3) == 3 else int(m_grp3) / (10 ** len(m_grp3))
            else:
                fraction = 0.0
            return minutes * 60 + seconds + fraction

        for raw_line in raw_lines:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            m_off = _LRC_OFFSET_TAG_RE.match(raw_line)
            if m_off:
                try:
                    # Standard LRC [offset:+ms]: positive moves lyrics earlier, negative moves lyrics later
                    off_ms = int(m_off.group(1))
                    if -30000 <= off_ms <= 30000:
                        lrc_header_offset_sec = off_ms / 1000.0
                except Exception:
                    pass
                continue

            matches = list(pattern.finditer(raw_line))
            if matches:
                has_timestamps = True
                raw_after_line_ts = pattern.sub('', raw_line)

                # Extract Enhanced LRC word-level timestamps (<mm:ss.xx>word) if present!
                inline_matches = list(inline_ts_pattern.finditer(raw_after_line_ts))
                parsed_words = None
                if inline_matches:
                    parsed_words = []
                    # Any prefix before first inline tag uses line start timestamp
                    prefix_txt = raw_after_line_ts[:inline_matches[0].start()]
                    if prefix_txt:
                        w_t0 = max(0.0, _parse_ts(matches[0].group(1), matches[0].group(2), matches[0].group(3)) - lrc_header_offset_sec)
                        parsed_words.append({"time": w_t0, "text": prefix_txt})
                    for idx_im, im in enumerate(inline_matches):
                        w_time = max(0.0, _parse_ts(im.group(1), im.group(2), im.group(3)) - lrc_header_offset_sec)
                        seg_end = inline_matches[idx_im + 1].start() if idx_im + 1 < len(inline_matches) else len(raw_after_line_ts)
                        w_txt = raw_after_line_ts[im.end():seg_end]
                        if w_txt:
                            parsed_words.append({"time": w_time, "text": w_txt})

                text = inline_ts_pattern.sub('', raw_after_line_ts)
                text = re.sub(r'\s+', ' ', text).strip()
                if not text:
                    continue
                for m in matches:
                    time_in_sec = max(0.0, _parse_ts(m.group(1), m.group(2), m.group(3)) - lrc_header_offset_sec)
                    entry = {"time": time_in_sec, "text": text}
                    if parsed_words and len(matches) == 1:
                        entry["words"] = parsed_words
                    lines.append(entry)

        if has_timestamps and lines:
            lines.sort(key=lambda x: x["time"])
            # Strip leading non-vocal credit/metadata lines (e.g. 'Bài hát:', 'Ca sĩ:', '作词:', music-note symbols)
            # during the first 15s so the app waits cleanly on Intro until real singing begins!
            while len(lines) > 4 and lines[0]["time"] <= 15.0 and _LRC_CREDIT_LINE_RE.search(lines[0]["text"]):
                lines.pop(0)
            # Deduplicate identical-timestamp bilingual LRC pairs (keep original primary line)
            deduped = []
            for item in lines:
                if deduped and abs(item["time"] - deduped[-1]["time"]) < 0.02:
                    continue
                deduped.append(item)
            return deduped

        # --- PLAIN TEXT LYRICS (Pasted from Genius / Google without [mm:ss] timestamps) ---
        filtered_plain = []
        skip_noise_block = False

        for r in raw_lines:
            line_str = r.strip()
            if not line_str:
                continue

            line_lower = line_str.lower()
            
            # 1. Skip Genius / Web Scraper Noise Blocks
            if any(noise in line_lower for noise in [
                "you might also like", "contributors", "embed", "see live tracklist",
                "lyricsovh", "genius.com", "hover over lyrics"
            ]):
                skip_noise_block = True
                continue

            if skip_noise_block:
                if line_str.startswith("[") or any(kw in line_lower for kw in ["verse", "chorus", "outro", "bridge"]):
                    skip_noise_block = False
                elif len(line_str.split()) >= 3:
                    skip_noise_block = False
                else:
                    continue

            filtered_plain.append(line_str)

        if not filtered_plain:
            return []

        # 2. Section Header Detector e.g. [Verse 1: Hngle], [Chorus], [Intro], [Pre-Chorus]
        def is_section_header(s: str) -> bool:
            sc = s.strip().lower()
            if sc.startswith("[") and (sc.endswith("]") or ":" in sc):
                return True
            if any(sc.startswith(kw) for kw in ["verse", "chorus", "pre-chorus", "intro", "outro", "bridge", "lời bài hát"]):
                return True
            return False

        dur = duration if (duration and duration > 30.0) else 210.0
        
        # YouTube intro music usually lasts ~16s to 24s before vocals start
        vocal_start_delay = max(16.0, min(24.0, dur * 0.08))
        
        # 3. Separate singing lines vs section headers & calculate word weights for natural cadence
        singing_items = []
        for idx, text in enumerate(filtered_plain):
            if not is_section_header(text):
                if self._has_intl_script(text):
                    # CJK/non-space scripts: weight by visible character count
                    char_count = len(re.sub(r'\s+', '', text))
                    weight = max(3, char_count // 2)
                else:
                    words = len(text.split())
                    weight = max(3, words)
                singing_items.append((idx, text, weight))

        total_weight = sum(w for _, _, w in singing_items)
        usable_dur = max(20.0, dur - vocal_start_delay - 10.0)

        singing_time_map = {}
        curr_time = vocal_start_delay
        for idx, text, w in singing_items:
            singing_time_map[idx] = round(curr_time, 2)
            line_duration = usable_dur * (w / max(1, total_weight))
            curr_time += line_duration

        result_lines = []
        for i, text in enumerate(filtered_plain):
            if is_section_header(text):
                if i == 0:
                    # First section title displayed during intro music (t = 1.0s)
                    result_lines.append({"time": 1.0, "text": text})
                else:
                    # Find next singing line's timestamp and place header slightly before it
                    next_t = None
                    for j in range(i + 1, len(filtered_plain)):
                        if j in singing_time_map:
                            next_t = singing_time_map[j]
                            break
                    if next_t is not None:
                        result_lines.append({"time": max(0.0, round(next_t - 1.2, 2)), "text": text})
                    else:
                        result_lines.append({"time": round(curr_time, 2), "text": text})
            else:
                t = singing_time_map.get(i, vocal_start_delay)
                result_lines.append({"time": t, "text": text})

        return result_lines

    def extract_youtube_id(self, url_or_text: str) -> str:
        """Extracts 11-character YouTube video ID from various YouTube URL formats."""
        if not url_or_text:
            return None
        text_clean = url_or_text.strip()
        pattern = r'(?:https?:\/\/)?(?:www\.|m\.|music\.)?(?:youtube\.com\/(?:watch\?.*?v=|shorts\/|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
        m = re.search(pattern, text_clean)
        if m:
            return m.group(1)
        if re.fullmatch(r'[a-zA-Z0-9_-]{11}', text_clean) and not re.search(r'\s', text_clean):
            return text_clean
        return None

    def fetch_youtube_info(self, url_or_id: str) -> dict:
        """Fetches video title, author, and thumbnail from YouTube oEmbed or page metadata."""
        vid = self.extract_youtube_id(url_or_id) if url_or_id else None
        if not vid:
            return None

        # 1. Primary: YouTube Official oEmbed API (Fast & free of authentication)
        try:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(oembed_url, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "video_id": vid,
                    "title": data.get("title", ""),
                    "author": data.get("author_name", ""),
                    "thumbnail": data.get("thumbnail_url", f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"),
                    "url": f"https://www.youtube.com/watch?v={vid}"
                }
        except Exception as e:
            print(f"[YouTube oEmbed Error] {e}")

        # 2. Fallback: Direct page meta scrape
        try:
            page_url = f"https://www.youtube.com/watch?v={vid}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "vi,en;q=0.9"
            }
            resp = requests.get(page_url, headers=headers, timeout=6)
            if resp.status_code == 200:
                m_title = re.search(r'<title>(.*?) - YouTube<\/title>', resp.text)
                title = m_title.group(1) if m_title else ""
                m_author = re.search(r'"ownerChannelName":"(.*?)"', resp.text)
                if not m_author:
                    m_author = re.search(r'"author":"(.*?)"', resp.text)
                author = m_author.group(1) if m_author else ""
                if title:
                    return {
                        "video_id": vid,
                        "title": title,
                        "author": author,
                        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                        "url": page_url
                    }
        except Exception as e:
            print(f"[YouTube Scrape Error] {e}")

        return None

    def search_by_youtube_url(self, url_or_id: str) -> dict:
        """
        Takes a YouTube URL, resolves exact video title & author, and searches for synced/plain lyrics.
        Returns a dict containing video info, direct lyrics match (if any), and full candidate list.
        """
        info = self.fetch_youtube_info(url_or_id)
        if not info:
            return None

        title = info.get("title", "")
        author = info.get("author", "")

        # Try direct fetch first
        direct_match = self.fetch_lyrics(title, author)

        # Get list of search candidates
        candidates = self.search_custom(title)

        return {
            "video_info": info,
            "direct_match": direct_match,
            "candidates": candidates
        }

    _INTL_SCRIPT_RE = re.compile(
        r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\u0e00-\u0e7f\u0400-\u04ff]'
    )
    _CJK_IDEO_KANA_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+')
    _OTHER_NON_LATIN_RE = re.compile(r'[\uac00-\ud7af\u0e00-\u0e7f\u0400-\u04ff]+')
    _LENT_BRACKET_NOISE_RE = re.compile(
        r'(?i)(official|mv|m/v|pv|video|audio|lyric|lyrics|hd|4k|ver|cover|live|ost|full|short|'
        r'sub|vietsub|engsub|karaoke|music|teaser|公式|歌詞|中字|中日|字幕|官方|完整|高音質|高画質|'
        r'動態|动态|纯享|가사|뮤비|뮤직|자막|nhạc|chính thức)'
    )

    def _has_intl_script(self, text: str) -> bool:
        """Returns True if text contains Japanese, Korean, Chinese, Thai, or Cyrillic characters."""
        return bool(self._INTL_SCRIPT_RE.search(text or ""))

    _VERSION_TAG_DEFS = (
        ("solo", re.compile(r'(?i)\bsolo(?:\s+ver(?:sion)?)?\b')),
        ("acoustic", re.compile(r'(?i)\bacoustic\b')),
        ("piano", re.compile(r'(?i)\bpiano(?:\s+ver(?:sion)?)?\b')),
        ("live", re.compile(r'(?i)\blive\b')),
        ("lofi", re.compile(r'(?i)\blo-?fi\b')),
        ("remix", re.compile(r'(?i)\b(remix|bootleg|cukak|vinahouse|edm|house|mashup)\b')),
        ("cover", re.compile(r'(?i)\bcover\b')),
        ("demo", re.compile(r'(?i)\bdemo\b')),
        ("speed", re.compile(r'(?i)\b(speed\s*up|sped\s*up|slowed|reverb)\b')),
        ("unplugged", re.compile(r'(?i)\bunplugged\b')),
    )

    def _extract_version_tags(self, text: str) -> set:
        if not text:
            return set()
        tags = set()
        for name, pat in self._VERSION_TAG_DEFS:
            if pat.search(text):
                tags.add(name)
        return tags

    def _version_match_score(self, req_title: str, cand_title: str) -> float:
        """
        Scores alignment of version tags (Solo Version, Acoustic, Remix, Lofi, Live, Demo, etc.)
        so 'Forget Me Now (Solo Version)' always prefers Solo Version over Duet/Remix!
        """
        req_tags = self._extract_version_tags(req_title)
        cand_tags = self._extract_version_tags(cand_title)
        score = 0.0

        for t in req_tags:
            if t in cand_tags:
                score += 220.0
            else:
                score -= 80.0

        for t in cand_tags:
            if t not in req_tags:
                score -= 120.0

        # Fine-grained Demo 1 vs Demo 2 alignment
        if "demo" in req_tags:
            req_d2 = bool(re.search(r'(?i)\bdemo\s*2\b', req_title or ""))
            cand_d1 = bool(re.search(r'(?i)\bdemo\s*1\b', cand_title or ""))
            cand_d2 = bool(re.search(r'(?i)\bdemo\s*2\b', cand_title or ""))
            if req_d2:
                score += 80.0 if cand_d2 else (-40.0 if cand_d1 else 0.0)
            else:
                if cand_d1 or ("demo" in cand_tags and not cand_d2):
                    score += 60.0
                elif cand_d2:
                    score -= 60.0

        return score

    def clean_search_query(self, title: str) -> str:
        """
        Cleans YouTube noise (Official MV, Lyrics Video, HD, 4K...) for manual search display
        while PRESERVING meaningful version tags like (Solo Version), (Acoustic), (Remix), (Demo).
        """
        if not title:
            return ""
        cleaned = title.replace('\u3000', ' ')

        def _keep_version_paren(m):
            full = m.group(0)
            inner = m.group(1).strip()
            if inner and self._extract_version_tags(inner):
                return f" ({inner}) "
            return " "

        cleaned = re.sub(r'[\(\[\{（［](.*?)[\)\]\}）］]', _keep_version_paren, cleaned)
        cleaned = re.sub(r'【(.*?)】', lambda m: f" {m.group(1).strip()} " if (m.group(1).strip() and not self._LENT_BRACKET_NOISE_RE.search(m.group(1))) else " ", cleaned)
        cleaned = re.sub(r'[「」『』《》〈〉]', ' ', cleaned)

        noise_phrases = [
            "official music video", "official video", "official mv", "official lyrics video",
            "official lyric video", "lyric video", "lyrics video", "official audio",
            "full audio", "m/v", "mv", "hd", "4k", "visualizer", "performance video",
            "music video", "full track", "video lyric", "mv lyric", "mv official",
            "mv hd", "vietsub", "engsub", "lyrics", "lyric", "karaoke"
        ]
        for phrase in noise_phrases:
            cleaned = re.sub(r'(?i)\b' + re.escape(phrase) + r'\b', ' ', cleaned)
            cleaned = re.sub(r'(?i)\b' + re.escape(phrase.replace('/', r'\/')) + r'\b', ' ', cleaned)

        cleaned = re.sub(r'(?i)(?:[\|\-–—\(\[]\s*)?\b(?:ep|album|mixtape|mini\s*album|playlist|tracklist)\b.*$', '', cleaned)
        cleaned = re.sub(r'[\"\'“”„‟‘’＂＇]', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r'^[-\|\:\+&·•—–｜：／\/\s]+|[-\|\:\+&·•—–｜：／\/\s]+$', '', cleaned)
        cleaned = re.sub(r'^\s*(?:track\s*#?\s*)?\d{1,2}\s*[\.\)\-:]\s+', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def clean_title(self, title: str) -> str:
        """Removes common noise from YouTube song titles across Vietnamese, English, Japanese, Korean, Chinese, etc."""
        if not title:
            return ""
        cleaned = title.replace('\u3000', ' ')

        # 1. Handle CJK lenticular brackets 【...】: strip if metadata tag, unwrap if artist/title
        def _replace_lenticular(m):
            inner = m.group(1).strip()
            if not inner or self._LENT_BRACKET_NOISE_RE.search(inner):
                return ' '
            return f' {inner} '

        cleaned = re.sub(r'【(.*?)】', _replace_lenticular, cleaned)

        # 2. Unwrap CJK title quotation brackets 「...」, 『...』, 《...》, 〈...〉 (keep the song title inside!)
        cleaned = re.sub(r'[「」『』《》〈〉]', ' ', cleaned)

        # 3. Remove text in ASCII/full-width parentheses/brackets e.g. (Official Music Video), [MV], （公式）
        cleaned = re.sub(r'[\(\[\{（［].*?[\)\]\}）］]', ' ', cleaned)

        # 4. Remove CJK & multilingual YouTube noise phrases (no \b needed for CJK)
        cjk_noise = [
            "ミュージックビデオ", "公式mv", "公式", "歌詞付き", "中日歌詞", "中日字幕",
            "中文字幕", "動態歌詞", "动态歌词", "官方完整版", "官方mv", "官方版", "完整版",
            "高音質", "高画質", "纯享版", "中字", "歌詞", "歌词",
            "뮤직비디오", "한글가사", "뮤비", "가사", "자막",
            "full ver.", "full ver", "short ver.", "short ver", "tv size",
            "vietsub", "engsub", "romaji", "pinyin", "nhạc phim"
        ]
        for phrase in cjk_noise:
            cleaned = re.sub(re.escape(phrase), ' ', cleaned, flags=re.IGNORECASE)

        # 5. Remove common ASCII YouTube noise phrases
        noise_phrases = [
            "official music video", "official video", "official mv", "official lyrics video",
            "official lyric video", "lyric video", "lyrics video", "official audio",
            "full audio", "m/v", "mv", "hd", "4k", "visualizer", "performance video",
            "music video", "cover", "remix", "full track", "audio", "video lyric",
            "mv lyric", "mv official", "mv hd", "official", "ost", "lyrics", "lyric", "karaoke"
        ]
        for phrase in noise_phrases:
            cleaned = re.sub(r'(?i)\b' + re.escape(phrase) + r'\b', ' ', cleaned)
            cleaned = re.sub(r'(?i)\b' + re.escape(phrase.replace('/', r'\/')) + r'\b', ' ', cleaned)

        # 6. Strip trailing Album / EP / Mixtape / Playlist tags (e.g. '| EP "Luv"', '- Album "..."')
        cleaned = re.sub(r'(?i)(?:[\|\-–—\(\[]\s*)?\b(?:ep|album|mixtape|mini\s*album|playlist|tracklist)\b.*$', '', cleaned)

        # 7. Remove quotes, feat. suffix, and leading track numbers (e.g. '3. ', '01 - ', 'Track 2:')
        cleaned = re.sub(r'[\"\'“”„‟‘’＂＇]', '', cleaned)
        cleaned = re.sub(r'\b(ft|feat|featuring)\.?\b.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r'^[-\|\:\+&·•—–｜：／\/\s]+|[-\|\:\+&·•—–｜：／\/\s]+$', '', cleaned)
        cleaned = re.sub(r'^\s*(?:track\s*#?\s*)?\d{1,2}\s*[\.\)\-:]\s+', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    _VI_DIACRITIC_RE = re.compile(
        r'[ăâđêôơưĂÂĐÊÔƠƯáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]'
    )
    _FOREIGN_HINT_RE = re.compile(
        r'(?i)(vietsub|nhạc\s*(?:hoa|trung|hàn|nhật|thái|nga)|tiếng\s*(?:hàn|nhật|trung|thái|nga)|'
        r'korean|japanese|chinese|k-?pop|j-?pop|c-?pop|anime|ost)'
    )
    _EP_ALBUM_TAIL_RE = re.compile(
        r'(?i)(?:[\|\-–—\(\[]\s*)?\b(?:ep|album|mixtape|mini\s*album|playlist|tracklist)\b.*$'
    )

    def _is_lyric_script_compatible(self, req_title: str, parsed_lines: list, artist_matched: bool = True) -> bool:
        """
        Guards against cross-language wrong-song matches:
        1) A clearly Vietnamese song title must never accept CJK lyrics (e.g. EP 'Luv' -> Korean Apink).
        2) A title containing CJK/Japanese/Korean characters (e.g. 'Cry for me - Michita ft 愛海')
           must never accept pure-Latin lyrics from an UNRELATED artist (e.g. 'Violet Skies').
        """
        if not req_title or not parsed_lines:
            return True

        sample = "".join((l.get("text") or "") for l in parsed_lines[:18])
        non_ws = re.sub(r'\s+', '', sample)
        if len(non_ws) < 10:
            return True
        cjk_hits = len(self._INTL_SCRIPT_RE.findall(non_ws))

        # Guard 1: Vietnamese title (no CJK, no foreign hint) must not accept CJK lyrics
        if self._VI_DIACRITIC_RE.search(req_title) and not self._has_intl_script(req_title) and not self._FOREIGN_HINT_RE.search(req_title):
            if cjk_hits >= 12 and (cjk_hits / len(non_ws)) >= 0.25:
                return False

        # Guard 2: CJK/international-script title with NO artist match must not accept pure-Latin wrong-artist lyrics
        if (not artist_matched) and self._has_intl_script(req_title):
            if cjk_hits < 3:
                return False

        return True

    def _extract_expected_artist_tokens(self, req_title: str, req_artist: str = "", res_title: str = "") -> tuple:
        """
        Extracts meaningful artist tokens from BOTH req_artist (channel/artist) and non-title parts
        of req_title (e.g. 'Michita', '愛海' from 'vietsub + lyrics | Cry for me - Michita ft 愛海').
        Returns (title_artist_tokens, channel_artist_tokens).
        """
        stop_meta = {
            'official', 'music', 'video', 'lyric', 'lyrics', 'vietsub', 'engsub', 'feat',
            'featuring', 'topic', 'audio', 'full', 'track', 'version', 'ver', 'remix',
            'cover', 'live', 'acoustic', 'solo', 'demo', 'piano', 'lofi', 'slowed',
            'karaoke', 'ost', 'hd', '4k', 'mv', 'pv', 'amv', 'romaji', 'pinyin', 'sub',
            'channel', 'entertainment', 'records', 'studio', 'production', 'media',
            'nhac', 'phim', 'the', 'and', 'for', 'you', 'with', 'from', 'this', 'that'
        }
        tok_pat = re.compile(r'[a-z0-9]{3,}|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]{2,}')

        res_title_toks = set(tok_pat.findall(self._fold_latin(res_title or "")))
        raw_title_toks = set(tok_pat.findall(self._fold_latin(req_title or "")))
        raw_title_cjk = set(re.findall(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]{2,}', req_title or ""))
        res_title_cjk = set(re.findall(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]{2,}', res_title or ""))

        title_artist_toks = (raw_title_toks - res_title_toks - stop_meta) | (raw_title_cjk - res_title_cjk)
        norm_a = self._normalize_artist(req_artist or "")
        chan_toks = (set(tok_pat.findall(self._fold_latin(norm_a))) - stop_meta) | set(
            re.findall(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]{2,}', norm_a)
        )
        return title_artist_toks, chan_toks

    def _check_artist_match(self, req_title: str, req_artist: str, res_title: str, res_artist: str) -> tuple:
        """
        Checks whether res_artist/res_title matches the requested artist (either from YouTube title
        like 'Cry for me - Michita ft 愛海' or from GSMTC artist).
        Returns (matched: bool, has_explicit_title_artist: bool, hit_count: int).
        """
        title_art_toks, chan_toks = self._extract_expected_artist_tokens(req_title, req_artist, res_title)
        res_meta_f = self._fold_latin(f"{res_title or ''} {res_artist or ''}")
        res_meta_raw = f"{res_title or ''} {res_artist or ''}".lower()

        title_hits = sum(1 for tok in title_art_toks if (tok in res_meta_f or tok in res_meta_raw))
        chan_hits = sum(1 for tok in chan_toks if (tok in res_meta_f or tok in res_meta_raw))
        has_title_artist = bool(title_art_toks)
        matched = (title_hits > 0) or (chan_hits > 0)
        return matched, has_title_artist, title_hits + chan_hits

    _CHANNEL_NOISE_RE = re.compile(
        r'(?i)\b(official|vevo|topic|music|channel|entertainment|records|tv|media|'
        r'production|productions|studio|studios|audio|lyrics|lyric|vietsub|engsub)\b'
    )
    _GENERIC_SINGLE_WORDS = {
        'anh', 'em', 'toi', 'ban', 'minh', 'ta', 'nguoi', 'cua', 'co', 'khong',
        'la', 'va', 'mot', 'hai', 'yeu', 'thuong', 'nho', 'dau', 'tim', 'nay', 'noi',
        'the', 'you', 'me', 'my', 'your', 'for', 'and', 'with', 'this', 'that', 'love', 'time', 'one'
    }

    def _fold_latin(self, text: str) -> str:
        """Lowercases and strips Vietnamese/Latin diacritics (đ->d) for accent-insensitive title matching."""
        if not text:
            return ""
        s = text.replace("đ", "d").replace("Đ", "D")
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return s.lower()

    def _normalize_artist(self, artist: str) -> str:
        if not artist:
            return ""
        s = self._CHANNEL_NOISE_RE.sub(" ", artist)
        s = re.sub(r'^[-\|\:\+&·•—–｜：／\/\s]+|[-\|\:\+&·•—–｜：／\/\s]+$', '', s)
        return re.sub(r'\s+', ' ', s).strip()

    def _is_artist_part(self, part: str, norm_artist: str) -> bool:
        """Returns True ONLY if 'part' itself is just the artist name (never when 'part' is 'Song + Artist')."""
        if not part or not norm_artist:
            return False
        p_f = re.sub(r'[^a-z0-9\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+', ' ', self._fold_latin(part)).strip()
        a_f = re.sub(r'[^a-z0-9\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+', ' ', self._fold_latin(norm_artist)).strip()
        if not p_f or not a_f:
            return False
        if p_f == a_f:
            return True
        # part is a shorter alias/subset of the artist name (e.g. 'Soobin' vs 'Soobin Hoang Son')
        if len(p_f) >= 4 and p_f in a_f:
            return True
        p_toks = set(w for w in p_f.split() if len(w) >= 2)
        a_toks = set(w for w in a_f.split() if len(w) >= 2)
        if p_toks and a_toks and p_toks.issubset(a_toks):
            return True
        # Or artist name matches almost the entire part (e.g. 'Son Tung M-TP Official' vs 'Son Tung M-TP')
        if a_f in p_f and len(p_f) <= len(a_f) + 6:
            return True
        return False

    def _split_title_segments(self, clean_t: str) -> list:
        """
        Splits a cleaned YouTube title into segments on |, ｜, ：, ／, or SPACED hyphens (' - '),
        preserving internal hyphens inside names like 'Sơn Tùng M-TP', 'K-ICM', 'G-Dragon', 'Jay-Z'.
        """
        if not clean_t:
            return []
        parts = [p.strip() for p in re.split(r'\s+[-–—:]\s+|[|｜：／]', clean_t) if p.strip()]
        # If no split occurred and CJK text has tight hyphen like '周杰伦-晴天', split between CJK chars
        if len(parts) == 1 and "-" in clean_t:
            cjk_split = [
                p.strip() for p in re.split(
                    r'(?<=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af])-(?=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af])',
                    clean_t
                ) if p.strip()
            ]
            if len(cjk_split) > 1:
                parts = cjk_split
        return parts

    def _extract_song_segments(self, title: str, artist: str = "") -> list:
        """Extracts likely song-title-only segments (excluding artist name, EP/Album tags, and noise)."""
        clean_t = self.clean_title(title)
        title_no_meta = self._EP_ALBUM_TAIL_RE.sub("", title or "")
        norm_a = self._normalize_artist(artist)
        noise_upper = {"OFFICIAL", "MV", "AUDIO", "LYRIC", "LYRICS", "VIDEO", "M/V", "HD", "4K", "VIETSUB", "ENGSUB"}

        segs = []
        # 1. CJK title quotation brackets 「...」『...』《...》 (highest priority for JP/CN YouTube titles)
        for m in re.findall(r'[「『《〈]([^」』》〉]{1,60})[」』》〉]', title_no_meta):
            qc = self.clean_title(m)
            if qc and not self._is_artist_part(qc, norm_a) and qc not in segs:
                segs.append(qc)

        # 2. Non-artist main segments from spaced-separator split (e.g. 'Nắng có mang em về', 'Đừng Làm Trái Tim Anh Đau')
        parts = self._split_title_segments(clean_t)
        non_artist = [
            p for p in parts
            if p.upper() not in noise_upper and not self._is_artist_part(p, norm_a)
        ]
        for p in non_artist:
            if p not in segs:
                segs.append(p)

        # 3. ASCII/curly quoted titles ONLY after stripping EP/Album suffixes (e.g. TWICE "FANCY", BTS '봄날')
        for m in re.findall(r"['\"“]([^'\"”]{2,60})['\"”]", title_no_meta):
            qc = self.clean_title(m)
            if not qc or self._is_artist_part(qc, norm_a) or qc in segs:
                continue
            # Avoid letting a stray 1-word ASCII quote override an existing multi-word Vietnamese main title
            if segs and len(qc.split()) == 1 and not self._has_intl_script(qc) and self._VI_DIACRITIC_RE.search(segs[0]):
                continue
            segs.append(qc)

        return segs

    def is_valid_match(self, req_title: str, res_title: str, req_artist: str = "") -> bool:
        """
        Strict multilingual title validator. Prevents false-positive wrong-song matches on a single
        common word (e.g. 'Đừng Làm Trái Tim Anh Đau' vs 'Nơi Này Có Anh' sharing only 'anh').
        """
        if not req_title or not res_title:
            return True

        stop_words = {
            'official', 'mv', 'audio', 'lyric', 'lyrics', 'video', 'hd', '4k',
            'ft', 'feat', 'full', 'track', 'ver', 'version', 'music', 'vietsub', 'engsub',
            'remix', 'bootleg', 'cover', 'live', 'acoustic', 'ost', 'karaoke',
            '公式', '歌詞', '中字', '가사', '뮤비', '자막'
        }

        def get_latin_tokens(s: str) -> set:
            folded = self._fold_latin(s)
            return {w for w in re.findall(r'[a-z0-9]+', folded) if len(w) >= 2 and w not in stop_words}

        def get_non_latin_tokens(s: str) -> set:
            s_low = s.lower()
            toks = set()
            for run in self._OTHER_NON_LATIN_RE.findall(s_low):
                if run not in stop_words:
                    toks.add(run)
            for run in self._CJK_IDEO_KANA_RE.findall(s_low):
                if run in stop_words:
                    continue
                toks.add(run)
                if len(run) >= 2:
                    for i in range(len(run) - 1):
                        bg = run[i:i + 2]
                        if bg not in stop_words:
                            toks.add(bg)
            return toks

        # Build candidate variants of res_title (core without parenthetical tags + non-noise parenthetical subtitles like '(봄날)')
        res_variants = []
        res_core = self.clean_title(res_title)
        if res_core:
            res_variants.append(res_core)
        for paren in re.findall(r'[\(\[（]([^)\]）]{1,50})[\)\]）]', res_title):
            p_low = paren.strip().lower()
            if p_low and not self._LENT_BRACKET_NOISE_RE.search(p_low) and not re.search(r'\b(feat|ft|remix|bootleg|paused|合作)\b', p_low):
                pc = self.clean_title(paren)
                if pc and pc not in res_variants:
                    res_variants.append(pc)
        if res_title.strip() and res_title.strip() not in res_variants:
            res_variants.append(res_title.strip())

        # Build requested song candidates (extracted song-title segments first, then full title)
        req_segs = self._extract_song_segments(req_title, req_artist)
        req_cands = list(req_segs)
        # Also include any non-noise parenthetical subtitle from req_title (e.g. 'Spring Day' in '봄날 (Spring Day)')
        for paren in re.findall(r'[\(\[（]([^)\]）]{2,50})[\)\]）]', req_title):
            p_low = paren.strip().lower()
            if p_low and not self._LENT_BRACKET_NOISE_RE.search(p_low) and not self._is_artist_part(paren, self._normalize_artist(req_artist)):
                pc = self.clean_title(paren)
                if pc and pc not in req_cands:
                    req_cands.append(pc)
        req_full_clean = self.clean_title(req_title)
        if req_full_clean and req_full_clean not in req_cands:
            req_cands.append(req_full_clean)

        # Check each (res_variant, req_candidate) pair
        req_all_nl = get_non_latin_tokens(req_title)
        for rv in res_variants:
            rv_nl = get_non_latin_tokens(rv)
            if rv_nl:
                # CJK / Korean / Thai / Cyrillic matching
                if req_all_nl:
                    nl_overlap = rv_nl & req_all_nl
                    if nl_overlap and (len(nl_overlap) / len(rv_nl)) >= 0.50:
                        return True
                    # Direct CJK run containment check for concise titles
                    for run in self._CJK_IDEO_KANA_RE.findall(rv):
                        if len(run) >= 2 and run in req_title:
                            return True
                    for run in self._OTHER_NON_LATIN_RE.findall(rv):
                        if len(run) >= 2 and run in req_title:
                            return True

            rv_lat = get_latin_tokens(rv)
            if not rv_lat:
                continue

            for rc in req_cands:
                rc_lat = get_latin_tokens(rc)
                if not rc_lat:
                    continue
                overlap = rv_lat & rc_lat
                if not overlap:
                    continue

                if len(rv_lat) == 1:
                    only_w = next(iter(rv_lat))
                    if rv_lat == rc_lat:
                        return True
                    if only_w not in self._GENERIC_SINGLE_WORDS and len(rc_lat) <= 2:
                        return True
                else:
                    # Multi-word Latin/Vietnamese song title: MUST match >= 2 words AND >= 65% of returned title!
                    res_cov = len(overlap) / len(rv_lat)
                    req_cov = len(overlap) / len(rc_lat)
                    if len(overlap) >= 2 and res_cov >= 0.65 and (req_cov >= 0.45 or res_cov >= 0.85):
                        return True

        return False

    def get_search_candidates(self, title: str, artist: str = "") -> list:
        candidates = []
        clean_t = self.clean_title(title)
        norm_a = self._normalize_artist(artist)

        def _add(c: str):
            c = re.sub(r'^[-\|\:\+&·•—–｜：／\/\s]+|[-\|\:\+&·•—–｜：／\/\s]+$', '', (c or ""))
            c = re.sub(r'\s+', ' ', c).strip()
            if c and len(c) >= 1 and not self._is_artist_part(c, norm_a) and c not in candidates:
                candidates.append(c)

        parts = self._split_title_segments(clean_t)
        song_segs = self._extract_song_segments(title, artist)
        full_norm = re.sub(r'\s*[|｜：]\s*', ' ', clean_t)
        full_norm = re.sub(r'\s+[-–—]\s+', ' ', full_norm).strip()

        # Check if the YouTube channel name matches one of the segments in the title
        artist_in_title = any(self._is_artist_part(p, norm_a) for p in parts)

        # 1. If the title itself holds BOTH song & artist (e.g. 'Cry for me - Michita' on a fan channel),
        #    search the full combined 'Song Artist' query FIRST so we never get wrong-artist covers!
        if len(parts) >= 2 and not artist_in_title:
            _add(full_norm)

        # 2. Extracted song-title segments paired with normalized channel artist (e.g. 'Đừng Làm Trái Tim Anh Đau Sơn Tùng M-TP')
        if norm_a:
            for seg in song_segs:
                _add(f"{seg} {norm_a}")

        # 3. Full combined title (if not added yet), then bare song-title segments
        _add(full_norm)
        for seg in song_segs:
            _add(seg)

        return candidates

    def _score_lyric_lines(self, parsed_lines: list, has_real_sync: bool, item_dur: float, target_dur: float,
                           req_title: str, req_artist: str, res_title: str, res_artist: str) -> float:
        """Scores a candidate lyric entry: strongly prioritizes real synced LRC, matching artist/feat, duration, and unfragmented full lines."""
        score = 0.0
        if has_real_sync and len(parsed_lines) >= 5:
            score += 1000.0
        elif has_real_sync:
            score += 300.0

        # Strong artist / featured artist verification against BOTH req_artist and raw req_title (e.g. "Michita ft 愛海")
        artist_matched, has_title_artist, art_hits = self._check_artist_match(req_title, req_artist, res_title, res_artist)
        if artist_matched:
            score += 550.0 + min(220.0, art_hits * 70.0)
        elif has_title_artist:
            # Title explicitly named a specific artist (e.g. 'Michita ft 愛海') that DOES NOT match res_artist (e.g. 'Violet Skies')!
            score -= 480.0

        # Version tag alignment (Solo Version, Acoustic, Live, Lofi, Remix, Demo...)
        score += self._version_match_score(req_title, res_title)

        # Duration match bonus / mismatch penalty (strongly favors exact MV-duration LRC over shorter studio LRC!)
        if target_dur and target_dur > 30.0 and item_dur and item_dur > 30.0:
            diff = abs(float(item_dur) - float(target_dur))
            if diff <= 4.0:
                score += 280.0
            elif diff <= 10.0:
                score += 140.0
            elif diff <= 20.0:
                score += 20.0
            elif diff > 50.0:
                score -= 220.0
            elif diff > 25.0:
                score -= 120.0

        # Anti-fragmentation & line completeness score
        if parsed_lines:
            n = len(parsed_lines)
            frag_count = 0
            dangling_comma_count = 0
            for ln in parsed_lines:
                t = (ln.get("text") or "").strip()
                non_ws = re.sub(r'\s+', '', t)
                if len(non_ws) <= 5:
                    frag_count += 1
                if t.endswith(("、", ",", "，")):
                    dangling_comma_count += 1
            frag_ratio = frag_count / max(1, n)
            comma_ratio = dangling_comma_count / max(1, n)
            score -= frag_ratio * 130.0
            score -= comma_ratio * 160.0
            if 12 <= n <= 100 and frag_ratio < 0.25:
                score += 65.0

        return score

    def _apply_auto_intro_offset(self, data: dict, video_duration: float) -> dict:
        """
        Detects trimmed-intro YouTube videos (e.g. 3:35 Vietsub vs 5:03 official album LRC)
        where the synced LRC's final vocal line extends past the video's total duration,
        and computes an automatic sync_offset so lyrics start right on cue.
        """
        if not data or not data.get("has_real_timestamps") or not video_duration or video_duration <= 30.0:
            return data
        lines = data.get("lines") or []
        if len(lines) < 5:
            return data

        t_first = float(lines[0]["time"])
        t_last = float(lines[-1]["time"])
        data["track_duration"] = round(float(video_duration), 1)

        # Only trigger when mathematically proven intro was trimmed:
        # LRC vocals run past the end of the video AND LRC has a long instrumental intro (> 22s).
        if t_last > (video_duration - 2.0) and t_first > 22.0:
            overflow = t_last - (video_duration - 12.0)
            est_offset = min(t_first - 10.0, max(overflow, t_first - 14.0))
            if est_offset >= 5.0:
                data["sync_offset"] = round(est_offset, 2)
                data["auto_sync_offset"] = True
                print(
                    f"[LyricsProvider] Auto intro-trim offset +{est_offset:.2f}s "
                    f"(video={video_duration:.1f}s, LRC t0={t_first:.1f}s..t_last={t_last:.1f}s)"
                )
        return data

    def fetch_lyrics(self, title: str, artist: str = "", duration: float = 0.0) -> dict:
        if not title:
            return None

        clean_t = self.clean_title(title)
        clean_a = artist.strip()
        norm_a = self._normalize_artist(clean_a)
        song_segs = self._extract_song_segments(title, clean_a)
        exact_title_query = song_segs[0] if song_segs else clean_t

        # 1. Check local cache first: check EXACT raw title BEFORE cleaned title so '(Solo Version)' never collides with original!
        if self.cache:
            req_ver_tags = self._extract_version_tags(title)
            cached_data = self.cache.get(title, clean_a)
            if not cached_data and title != clean_t:
                fallback_cached = self.cache.get(clean_t, clean_a)
                if fallback_cached:
                    # Only reuse stripped-title cache if version tags match (or neither has version tags)
                    cand_ver_tags = self._extract_version_tags(fallback_cached.get("title", ""))
                    if req_ver_tags == cand_ver_tags:
                        cached_data = fallback_cached
            if cached_data and cached_data.get("lines"):
                src = str(cached_data.get("source") or "")
                is_manual = ("Manual" in src) or ("Custom" in src)
                cached_dur = float(cached_data.get("track_duration") or 0.0)
                cached_src_dur = float(cached_data.get("source_duration") or 0.0)
                cached_lines = cached_data.get("lines") or []
                dur_changed = (duration > 30.0 and cached_dur > 30.0 and abs(duration - cached_dur) > 10.0)
                # Auto-upgrade legacy/mismatched auto-cached studio lyrics when playing a longer Official MV (e.g. 248s MV vs 215s studio)
                legacy_mv_mismatch = (
                    (not is_manual)
                    and (not cached_data.get("_best_dur_checked", False))
                    and duration > 30.0
                    and (
                        (cached_src_dur > 30.0 and abs(cached_src_dur - duration) > 10.0)
                        or (cached_src_dur <= 0.0 and cached_lines and (duration - float(cached_lines[-1]["time"])) > 28.0)
                    )
                )
                cached_art_ok = True
                if not is_manual:
                    c_matched, c_has_title_art, _ = self._check_artist_match(
                        title, clean_a, cached_data.get("title", ""), cached_data.get("artist", "")
                    )
                    if c_has_title_art and not c_matched:
                        cached_art_ok = False
                cached_title_ok = is_manual or self.is_valid_match(title, cached_data.get("title", ""), req_artist=clean_a)
                cached_script_ok = is_manual or self._is_lyric_script_compatible(title, cached_lines, artist_matched=cached_art_ok)
                req_is_remix = bool(re.search(r'(?i)\b(remix|bootleg|cover|live|lofi|slowed)\b', title or ""))
                cached_unwanted_remix = (not is_manual) and (not req_is_remix) and bool(
                    re.search(r'(?i)\b(remix|bootleg|cover|lofi|slowed)\b', str(cached_data.get("title") or ""))
                )
                if cached_title_ok and cached_art_ok and cached_script_ok and (not cached_unwanted_remix) and (not legacy_mv_mismatch) and (is_manual or (cached_data.get("has_real_timestamps", False) and not dur_changed)):
                    # If cached entry has no user-saved offset yet, still check intro-trim alignment
                    if "sync_offset" not in cached_data and duration > 30.0:
                        self._apply_auto_intro_offset(cached_data, duration)
                    print(f"[LyricsProvider] Loaded from cache: {clean_t}")
                    return cached_data

        candidates = self.get_search_candidates(title, artist)
        print(f"[LyricsProvider] Search candidates for '{title}': {candidates}")

        is_intl = self._has_intl_script(title) or self._has_intl_script(artist)
        data = None
        plain_fallback = None

        def _dur_diff(d_item):
            if not d_item or duration <= 30.0:
                return 9999.0
            sd = float(d_item.get("source_duration") or 0.0)
            return abs(sd - duration) if sd > 30.0 else 9999.0

        def _search_best_lrclib():
            """
            Checks LRCLIB candidates and picks the best synced LRC:
            1) STRICTLY prefers artist-matched tracks (so 'Cry for me - Michita ft 愛海' NEVER gets
               overwritten by unrelated 'Cry for Me - Violet Skies' even if durations differ!).
            2) Among tracks with equal artist-match tier (e.g. MV vs Studio of the same song),
               picks the closest-duration high-quality synced LRC!
            """
            nonlocal plain_fallback
            best_lrc = None
            best_lrc_art = False
            best_lrc_diff = 9999.0
            best_lrc_score = -1e9

            def _consider(res_item):
                nonlocal best_lrc, best_lrc_art, best_lrc_diff, best_lrc_score
                if not res_item:
                    return
                r_art = bool(res_item.get("_artist_matched", False))
                r_diff = _dur_diff(res_item)
                r_sc = float(res_item.get("_score", 0.0))
                if best_lrc is None:
                    best_lrc, best_lrc_art, best_lrc_diff, best_lrc_score = res_item, r_art, r_diff, r_sc
                    return
                # NEVER let an unmatched-artist track replace an artist-matched track!
                if best_lrc_art and not r_art:
                    return
                if r_art and not best_lrc_art:
                    best_lrc, best_lrc_art, best_lrc_diff, best_lrc_score = res_item, r_art, r_diff, r_sc
                    return
                # Same artist-match tier -> prefer significantly closer duration, then higher quality score
                if r_diff + 2.0 < best_lrc_diff or (abs(r_diff - best_lrc_diff) <= 2.0 and r_sc > best_lrc_score):
                    best_lrc, best_lrc_art, best_lrc_diff, best_lrc_score = res_item, r_art, r_diff, r_sc

            ex, pf = self._fetch_lrclib_exact(exact_title_query, norm_a or clean_a, duration=duration, require_synced=True, req_title=title)
            if pf and not plain_fallback:
                plain_fallback = pf
            _consider(ex)
            if best_lrc and best_lrc_art and (duration <= 30.0 or best_lrc_diff <= 6.0):
                return best_lrc

            for cand in candidates:
                res, pf = self._fetch_lrclib_search(cand, req_title=title, req_artist=clean_a, duration=duration, require_synced=True)
                if pf and not plain_fallback:
                    plain_fallback = pf
                _consider(res)
                # Stop early once we have an artist-matched result with exact video duration!
                if best_lrc and best_lrc_art and (duration <= 30.0 or best_lrc_diff <= 6.0):
                    break
            return best_lrc

        if is_intl:
            # Pass 1 (SYNCED ONLY): LRCLIB (duration-aligned!) -> NetEase CloudSearch -> ZingMP3
            data = _search_best_lrclib()
            if not data:
                for cand in candidates[:3]:
                    data = self._fetch_netease_search(cand, req_title=title, req_artist=clean_a)
                    if data:
                        break
            if not data:
                for cand in candidates[:3]:
                    z_res = self._fetch_zingmp3_search(cand, req_title=title, req_artist=clean_a, duration=duration)
                    if z_res:
                        z_res.pop("_artist_matched", None)
                        data = z_res
                        break
        else:
            # Pass 1 (SYNCED ONLY): ZingMP3 (strictly artist & duration checked) -> LRCLIB (exact MV duration!) -> NetEase -> fallback
            zing_weak_fallback = None
            zing_dur_mismatch_fallback = None
            for cand in candidates:
                z_res = self._fetch_zingmp3_search(cand, req_title=title, req_artist=clean_a, duration=duration)
                if z_res:
                    is_art = z_res.pop("_artist_matched", False)
                    z_diff = _dur_diff(z_res)
                    if is_art:
                        # If playing an Official MV whose length differs from ZingMP3 studio audio by > 8s
                        # (e.g. 248s MV vs 215s audio), check LRCLIB first for an exact 248s MV-synced LRC!
                        if duration > 30.0 and z_diff > 8.0 and z_diff < 9000.0:
                            if zing_dur_mismatch_fallback is None or z_diff < _dur_diff(zing_dur_mismatch_fallback):
                                zing_dur_mismatch_fallback = z_res
                        else:
                            data = z_res
                            break
                    elif not zing_weak_fallback:
                        zing_weak_fallback = z_res

            if not data:
                lrc_res = _search_best_lrclib()
                if lrc_res:
                    if zing_dur_mismatch_fallback:
                        # Prefer LRCLIB if its duration matches the playing video significantly closer than ZingMP3!
                        if _dur_diff(lrc_res) + 4.0 < _dur_diff(zing_dur_mismatch_fallback):
                            data = lrc_res
                        else:
                            data = zing_dur_mismatch_fallback
                    else:
                        data = lrc_res

            if not data and zing_dur_mismatch_fallback:
                data = zing_dur_mismatch_fallback

            if not data:
                for cand in candidates[:2]:
                    data = self._fetch_netease_search(cand, req_title=title, req_artist=clean_a)
                    if data:
                        break
            if not data and zing_weak_fallback:
                data = zing_weak_fallback

        # Pass 2: Use best scored plainLyrics fallback ONLY if zero synced lyrics exist anywhere
        if not data and plain_fallback:
            data = plain_fallback

        if data:
            data.pop("_artist_matched", None)
            data.pop("_score", None)
            if duration > 30.0:
                data["track_duration"] = round(float(duration), 1)
                data["_best_dur_checked"] = True
            self._apply_auto_intro_offset(data, duration)
            if self.cache:
                self.cache.set(title, clean_a, data)
                if not self._extract_version_tags(title) and clean_t != title:
                    self.cache.set(clean_t, clean_a, data)

        return data

    def _fetch_zingmp3_search(self, query: str, req_title: str = "", req_artist: str = "", duration: float = 0.0) -> dict:
        try:
            url = f"https://ac.zingmp3.vn/v1/web/ac-suggestions?query={urllib.parse.quote(query)}"
            resp = requests.get(url, headers=self.headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", {}).get("items", [])
                valid_sugs = []
                norm_req_a = self._fold_latin(self._normalize_artist(req_artist))
                req_title_low = (req_title or "").lower()
                req_is_remix = bool(re.search(r'(?i)\b(remix|bootleg|cover|live|lofi|slowed)\b', req_title_low))
                req_wants_demo = bool(re.search(r'(?i)\bdemo\b', req_title_low))
                req_wants_demo2 = bool(re.search(r'(?i)\bdemo\s*2\b', req_title_low))

                for item in items:
                    for sug in item.get("suggestions", []):
                        if sug.get("type") != 1:
                            continue
                        lyric_url = sug.get("lyricLink")
                        if not lyric_url:
                            continue
                        res_title = sug.get("title", "")
                        if req_title and not self.is_valid_match(req_title, res_title, req_artist=req_artist):
                            continue

                        artists = ", ".join([a.get("name", "") for a in sug.get("artists", []) if a.get("name")])
                        sug_dur = float(sug.get("duration") or 0.0)
                        score = 0.0

                        # Artist match bonus (check against both channel artist AND artist named in YouTube title)
                        artists_f = self._fold_latin(artists)
                        req_title_f = self._fold_latin(req_title)
                        artist_matched = False
                        if norm_req_a and norm_req_a in artists_f:
                            score += 150.0
                            artist_matched = True
                        elif artists_f and any(tok in req_title_f for tok in re.findall(r'[a-z0-9]{3,}', artists_f)):
                            score += 110.0
                            artist_matched = True

                        # If artist does NOT match AND ZingMP3 title has extra words not in req_title (e.g. 'Hoàn Hảo Hơn' vs 'Hoàn Hảo | B RAY'), skip so LRCLIB can provide the exact track!
                        if not artist_matched and req_title:
                            res_words = set(re.findall(r'[a-z0-9]{2,}', self._fold_latin(self.clean_title(res_title))))
                            req_words = set(re.findall(r'[a-z0-9]{2,}', req_title_f))
                            if res_words and (res_words - req_words):
                                continue

                        # Skip unsolicited remix/bootleg/cover on ZingMP3 so LRCLIB can provide the real original track
                        sug_is_remix = bool(re.search(r'(?i)\b(remix|bootleg|cover|live|lofi|slowed)\b', res_title))
                        if sug_is_remix and not req_is_remix:
                            continue

                        # Version tag alignment (Solo Version, Acoustic, Demo, Live, Lofi, Remix...)
                        score += self._version_match_score(req_title, res_title)

                        # Solo version explicitly prefers single-artist track over multi-artist duet
                        if "solo" in self._extract_version_tags(req_title):
                            if len(sug.get("artists", [])) == 1:
                                score += 60.0
                            elif len(sug.get("artists", [])) > 1:
                                score -= 40.0

                        # Duration alignment
                        if duration > 30.0 and sug_dur > 30.0:
                            diff = abs(sug_dur - duration)
                            if diff <= 6.0:
                                score += 120.0
                            elif diff <= 18.0:
                                score += 60.0
                            elif diff > 50.0:
                                score -= 80.0

                        valid_sugs.append((score, artist_matched, sug_dur, res_title, artists, lyric_url))

                valid_sugs.sort(key=lambda x: x[0], reverse=True)
                for _, is_art_match, sug_dur, res_title, artists, lyric_url in valid_sugs:
                    l_resp = requests.get(lyric_url, headers=self.headers, timeout=5)
                    if l_resp.status_code == 200 and l_resp.content:
                        lrc_text = l_resp.content.decode("utf-8", errors="replace").lstrip("\ufeff")
                        parsed = self.parse_lrc(lrc_text)
                        if parsed and self._is_lyric_script_compatible(req_title, parsed):
                            return {
                                "title": res_title,
                                "artist": artists,
                                "synced": True,
                                "has_real_timestamps": True,
                                "source_duration": round(float(sug_dur), 1) if sug_dur > 0 else 0.0,
                                "lines": parsed,
                                "raw_lrc": lrc_text,
                                "source": "ZingMP3",
                                "_artist_matched": is_art_match,
                            }
        except Exception as e:
            print(f"[ZingMP3 Error] {e}")
        return None

    def _fetch_lrclib_exact(self, title: str, artist: str, duration: float = 0.0, require_synced: bool = False, req_title: str = ""):
        """Returns (synced_result_or_none, plain_fallback_or_none)."""
        try:
            params = {"track_name": title}
            if artist:
                params["artist_name"] = artist
            
            url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(params)}"
            resp = requests.get(url, headers=self.headers, timeout=5)
            if resp.status_code == 200:
                res = resp.json()
                synced = res.get("syncedLyrics")
                plain = res.get("plainLyrics")
                res_dur = float(res.get("duration") or 0.0)
                dur_val = duration if (duration and duration > 30.0) else (res_dur or 210.0)
                check_t = req_title or title
                res_t = res.get("trackName", title)
                res_a = res.get("artistName", artist)
                ex_art_ok, _, _ = self._check_artist_match(check_t, artist, res_t, res_a)
                if synced:
                    parsed = self.parse_lrc(synced, duration=dur_val)
                    if parsed and self._is_lyric_script_compatible(check_t, parsed, artist_matched=ex_art_ok):
                        synced_dict = {
                            "title": res_t,
                            "artist": res_a,
                            "synced": True,
                            "has_real_timestamps": True,
                            "source_duration": round(float(res_dur), 1) if res_dur > 0 else 0.0,
                            "lines": parsed,
                            "raw_lrc": synced,
                            "source": "LRCLIB Exact",
                            "_artist_matched": ex_art_ok,
                            "_score": self._score_lyric_lines(parsed, True, res_dur, duration, check_t, artist, res_t, res_a),
                        }
                        # If duration differs significantly (e.g. 3:35 Audio vs 4:08 Official MV),
                        # keep as fallback so ranked LRCLIB Search can find the exact-duration MV sync!
                        if duration > 30.0 and res_dur > 30.0 and abs(res_dur - duration) > 8.0:
                            return None, synced_dict
                        return synced_dict, None
                if plain:
                    parsed = self.parse_lrc(plain, duration=dur_val)
                    if parsed and self._is_lyric_script_compatible(check_t, parsed, artist_matched=ex_art_ok):
                        plain_dict = {
                            "title": res_t,
                            "artist": res_a,
                            "synced": True,
                            "has_real_timestamps": False,
                            "plain": plain,
                            "lines": parsed,
                            "source": "LRCLIB Exact (Plain)",
                            "_artist_matched": ex_art_ok,
                        }
                        return (None if require_synced else plain_dict), plain_dict
        except Exception as e:
            print(f"[LRCLIB Exact Error] {e}")
        return None, None

    def _fetch_lrclib_search(self, query: str, req_title: str = "", req_artist: str = "",
                             duration: float = 0.0, require_synced: bool = False):
        """Evaluates ALL valid LRCLIB matches and picks the highest-quality synced LRC (full lines, matching artist & duration)."""
        best_synced = None
        best_synced_score = -1e9
        best_plain = None
        best_plain_score = -1e9

        try:
            url = f"https://lrclib.net/api/search?q={urllib.parse.quote(query)}"
            resp = requests.get(url, headers=self.headers, timeout=5)
            if resp.status_code == 200:
                results = resp.json()
                if isinstance(results, list) and len(results) > 0:
                    for item in results:
                        res_t = item.get("trackName", "")
                        res_a = item.get("artistName", "")
                        item_dur = item.get("duration") or 0.0
                        if req_title and not self.is_valid_match(req_title, res_t, req_artist=req_artist):
                            continue

                        dur_for_parse = duration if (duration and duration > 30.0) else (item_dur or 210.0)

                        art_ok, _, _ = self._check_artist_match(req_title, req_artist, res_t, res_a)

                        synced = item.get("syncedLyrics")
                        if synced:
                            parsed = self.parse_lrc(synced, duration=dur_for_parse)
                            if parsed and self._is_lyric_script_compatible(req_title, parsed, artist_matched=art_ok):
                                sc = self._score_lyric_lines(
                                    parsed, True, item_dur, duration,
                                    req_title, req_artist, res_t, res_a
                                )
                                if sc > best_synced_score:
                                    best_synced_score = sc
                                    best_synced = {
                                        "title": res_t,
                                        "artist": res_a,
                                        "synced": True,
                                        "has_real_timestamps": True,
                                        "source_duration": round(float(item_dur), 1) if item_dur and item_dur > 0 else 0.0,
                                        "lines": parsed,
                                        "raw_lrc": synced,
                                        "source": "LRCLIB Search",
                                        "_artist_matched": art_ok,
                                        "_score": sc,
                                    }
                                continue

                        plain = item.get("plainLyrics")
                        if plain:
                            parsed = self.parse_lrc(plain, duration=dur_for_parse)
                            if parsed and self._is_lyric_script_compatible(req_title, parsed, artist_matched=art_ok):
                                sc = self._score_lyric_lines(
                                    parsed, False, item_dur, duration,
                                    req_title, req_artist, res_t, res_a
                                )
                                if sc > best_plain_score:
                                    best_plain_score = sc
                                    best_plain = {
                                        "title": res_t,
                                        "artist": res_a,
                                        "synced": True,
                                        "has_real_timestamps": False,
                                        "plain": plain,
                                        "lines": parsed,
                                        "source": "LRCLIB Search (Plain)",
                                        "_artist_matched": art_ok,
                                        "_score": sc,
                                    }
        except Exception as e:
            print(f"[LRCLIB Search Error] {e}")

        if best_synced:
            return best_synced, best_plain
        return (None if require_synced else best_plain), best_plain

    def _fetch_netease_search(self, query: str, req_title: str = "", req_artist: str = "") -> dict:
        try:
            netease_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://music.163.com/"
            }
            resp = requests.post(
                "https://music.163.com/api/cloudsearch/pc",
                data={"s": query, "type": 1, "limit": 6, "offset": 0},
                headers=netease_headers,
                timeout=5
            )
            if resp.status_code == 200:
                res = resp.json()
                if not isinstance(res, dict) or not isinstance(res.get("result"), dict):
                    return None
                songs = res["result"].get("songs") or []
                for song in songs:
                    if not isinstance(song, dict):
                        continue
                    song_id = song.get("id")
                    song_name = song.get("name", "")
                    if not song_id or (req_title and not self.is_valid_match(req_title, song_name, req_artist=req_artist)):
                        continue

                    ar_list = song.get("ar") or song.get("artists") or []
                    artists = ", ".join([a.get("name", "") for a in ar_list if isinstance(a, dict) and a.get("name")])

                    lyric_url = f"https://music.163.com/api/song/lyric?os=pc&id={song_id}&lv=-1&kv=-1&tv=-1"
                    l_resp = requests.get(lyric_url, headers=netease_headers, timeout=5)
                    if l_resp.status_code == 200:
                        l_data = l_resp.json()
                        if not isinstance(l_data, dict) or not isinstance(l_data.get("lrc"), dict):
                            continue
                        lrc_text = l_data["lrc"].get("lyric", "")
                        if lrc_text and "[" in lrc_text:
                            parsed = self.parse_lrc(lrc_text)
                            if parsed and len(parsed) >= 5 and self._is_lyric_script_compatible(req_title, parsed):
                                return {
                                    "title": song_name,
                                    "artist": artists,
                                    "synced": True,
                                    "has_real_timestamps": True,
                                    "lines": parsed,
                                    "raw_lrc": lrc_text,
                                    "source": "NetEase"
                                }
        except Exception as e:
            print(f"[NetEase Error] {e}")
        return None

    def search_custom(self, query: str):
        """Returns verified, well-ranked lyric candidates (with non-empty lyrics) from ZingMP3, LRCLIB, and NetEase."""
        results = []
        if not query:
            return results

        # Automatically resolve YouTube URL if passed as query
        yt_id = self.extract_youtube_id(query)
        if yt_id:
            yt_info = self.fetch_youtube_info(yt_id)
            if yt_info and yt_info.get("title"):
                query = yt_info["title"]

        # Build up to 4 DISTINCT high-signal queries (version-specific first, then broad title fallback; NEVER bare artist!)
        queries = []
        seen_q_norm = set()

        def _add_q(q_str: str):
            q_str = re.sub(r'\s+', ' ', (q_str or "")).strip()
            q_str = re.sub(r'^[-\|\:\s]+|[-\|\:\s]+$', '', q_str).strip()
            q_norm = re.sub(r'[^a-z0-9\u00c0-\u024f\u1e00-\u1eff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+', ' ', q_str.lower()).strip()
            if q_str and q_norm and q_norm not in seen_q_norm:
                seen_q_norm.add(q_norm)
                queries.append(q_str)

        search_clean = self.clean_search_query(query)
        unwrapped = re.sub(r'[\(\[\{（［](.*?)[\)\]\}）］]', r' \1 ', search_clean)
        unwrapped = re.sub(r'\s*[|｜]\s*|\s+[-–—]\s+', ' ', unwrapped)

        # 1. Exact song segment + version tag (e.g. 'Forget Me Now Solo Version')
        ver_parts = re.split(r'\s+[-–—]\s+|\s*[|｜]\s*', search_clean)
        if len(ver_parts) >= 2:
            ver_parts_sorted = sorted(
                [p.strip() for p in ver_parts if p.strip()],
                key=lambda p: (1 if self._extract_version_tags(p) else 0, len(p.split()), len(p)),
                reverse=True
            )
            top_seg = re.sub(r'[\(\[\{（［](.*?)[\)\]\}）］]', r' \1 ', ver_parts_sorted[0])
            _add_q(top_seg)

        # 2. Full unwrapped query (artist + song + version)
        _add_q(unwrapped)

        # 3. Clean title without version tag (so other versions & tracks with unusual tags are STILL found!)
        cleaned_no_ver = re.sub(r'\s*[|｜]\s*|\s+[-–—]\s+', ' ', self.clean_title(query))
        _add_q(cleaned_no_ver)

        # 4. Primary song title segment alone (broadest fallback, never bare artist!)
        song_segs = self._extract_song_segments(query)
        if song_segs:
            best_seg = max(song_segs, key=lambda s: (len(s.split()), len(s)))
            _add_q(best_seg)
        _add_q(query.strip())

        seen_keys = set()
        seen_content = set()

        def _search_zing():
            for q in queries[:4]:
                try:
                    url = f"https://ac.zingmp3.vn/v1/web/ac-suggestions?query={urllib.parse.quote(q)}"
                    resp = requests.get(url, headers=self.headers, timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("data", {}).get("items", [])
                        for item in items:
                            for sug in item.get("suggestions", []):
                                if sug.get("type") != 1:
                                    continue
                                lyric_url = (sug.get("lyricLink") or "").strip()
                                # Skip songs that have NO lyric link on ZingMP3 (otherwise selecting them yields 0 lines!)
                                if not lyric_url or not lyric_url.startswith("http"):
                                    continue
                                title = sug.get("title", "")
                                artists = ", ".join([a.get("name", "") for a in sug.get("artists", []) if a.get("name")])
                                key = f"zmp3_{sug.get('id') or title}_{artists}"
                                if key not in seen_keys:
                                    seen_keys.add(key)
                                    results.append({
                                        "id": key,
                                        "trackName": title,
                                        "artistName": artists,
                                        "albumName": "ZingMP3",
                                        "duration": sug.get("duration", 210),
                                        "synced": True,
                                        "syncedLyrics": lyric_url,
                                        "plainLyrics": None,
                                        "source": "ZingMP3"
                                    })
                except Exception as e:
                    print(f"[ZingMP3 Custom Search Error] {e}")

        def _search_lrclib():
            for q in queries[:4]:
                try:
                    url = f"https://lrclib.net/api/search?q={urllib.parse.quote(q)}"
                    resp = requests.get(url, headers=self.headers, timeout=5)
                    if resp.status_code == 200:
                        raw_list = resp.json()
                        if not isinstance(raw_list, list):
                            continue
                        for item in raw_list:
                            synced_str = (item.get("syncedLyrics") or "").strip()
                            plain_str = (item.get("plainLyrics") or "").strip()
                            # Skip instrumental / empty LRCLIB rows with zero lyrics
                            if not synced_str and not plain_str:
                                continue
                            item_id = item.get("id")
                            key = f"lrclib_{item_id}"
                            # Deduplicate identical LRCLIB uploads (same title + duration + text fingerprint)
                            t_norm = (item.get("trackName") or "").strip().lower()
                            a_norm = (item.get("artistName") or "").strip().lower()
                            dur_bin = int(round(float(item.get("duration") or 0) / 3.0))
                            lrc_fp = re.sub(r'\s+', '', (synced_str or plain_str)[:90])
                            content_sig = f"lrc|{t_norm}|{a_norm}|{dur_bin}|{bool(synced_str)}|{lrc_fp}"
                            if key not in seen_keys and content_sig not in seen_content:
                                seen_keys.add(key)
                                seen_content.add(content_sig)
                                results.append({
                                    "id": key,
                                    "trackName": item.get("trackName"),
                                    "artistName": item.get("artistName"),
                                    "albumName": item.get("albumName"),
                                    "duration": item.get("duration"),
                                    "synced": bool(synced_str),
                                    "syncedLyrics": synced_str or None,
                                    "plainLyrics": plain_str or None,
                                    "source": "LRCLIB"
                                })
                except Exception as e:
                    print(f"[LRCLIB Custom Search Error] {e}")

        def _search_netease():
            for q in queries[:2]:
                try:
                    ne_headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Referer": "https://music.163.com/"
                    }
                    resp = requests.post(
                        "https://music.163.com/api/cloudsearch/pc",
                        data={"s": q, "type": 1, "limit": 6, "offset": 0},
                        headers=ne_headers,
                        timeout=5
                    )
                    if resp.status_code != 200:
                        continue
                    songs = resp.json().get("result", {}).get("songs", [])
                    for song in songs[:5]:
                        sid = song.get("id")
                        key = f"netease_{sid}"
                        if not sid or key in seen_keys:
                            continue
                        l_resp = requests.get(
                            f"https://music.163.com/api/song/lyric?id={sid}&lv=1",
                            headers=ne_headers,
                            timeout=4
                        )
                        if l_resp.status_code != 200:
                            continue
                        lrc_str = (l_resp.json().get("lrc", {}).get("lyric") or "").strip()
                        if not lrc_str:
                            continue
                        parsed_check = self.parse_lrc(lrc_str)
                        if not parsed_check:
                            continue
                        seen_keys.add(key)
                        title = song.get("name", "")
                        artists = ", ".join([a.get("name", "") for a in (song.get("ar") or song.get("artists") or []) if a.get("name")])
                        dur_sec = (song.get("dt") or song.get("duration") or 0) / 1000.0
                        has_ts = bool(re.search(r'\[\d+:\d+', lrc_str))
                        results.append({
                            "id": key,
                            "trackName": title,
                            "artistName": artists,
                            "albumName": (song.get("al") or {}).get("name", "NetEase"),
                            "duration": dur_sec if dur_sec > 0 else 210,
                            "synced": has_ts,
                            "syncedLyrics": lrc_str if has_ts else None,
                            "plainLyrics": lrc_str if not has_ts else None,
                            "source": "NetEase"
                        })
                except Exception as e:
                    print(f"[NetEase Custom Search Error] {e}")

        if self._has_intl_script(query):
            _search_lrclib()
            _search_zing()
        else:
            _search_zing()
            _search_lrclib()

        # Fallback to NetEase if fewer than 3 TITLE-MATCHING synced results were found
        relevant_synced = sum(
            1 for r in results
            if r.get("synced") and self.is_valid_match(query, r.get("trackName") or "")
        )
        if relevant_synced < 3:
            _search_netease()

        # Rank by: (1) matches queried title, (2) version tag match (Solo/Remix/Acoustic/Demo), (3) synced first, (4) original order
        req_ver_tags = self._extract_version_tags(query)
        def _custom_rank(pair):
            idx, r = pair
            cand_title = r.get("trackName") or ""
            cand_artist = r.get("artistName") or ""
            title_ok = self.is_valid_match(query, cand_title)
            ver_score = self._version_match_score(query, cand_title)
            # Solo version prefers single-artist credit over multi-artist duet
            if "solo" in req_ver_tags:
                is_multi = any(sep in cand_artist for sep in (",", "&", "•", "ft.", "feat"))
                ver_score += (-40.0 if is_multi else 40.0)
            return (0 if title_ok else 1, -ver_score, 0 if r.get("synced") else 1, idx)

        results = [r for _, r in sorted(enumerate(results), key=_custom_rank)]
        return results
