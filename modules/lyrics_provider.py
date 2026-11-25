import re
import unicodedata
import urllib.parse
import requests


_CJK_SCRIPT_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]')
_CJK_RUN_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+')


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
        inline_ts_pattern = re.compile(r'<\d+:\d+(?:[\.\:]\d+)?>')
        
        has_timestamps = False
        raw_lines = lrc_text.splitlines()

        for raw_line in raw_lines:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            matches = list(pattern.finditer(raw_line))
            if matches:
                has_timestamps = True
                text = pattern.sub('', raw_line)
                text = inline_ts_pattern.sub('', text)
                text = re.sub(r'\s+', ' ', text).strip()
                if not text:
                    continue
                for m in matches:
                    minutes = int(m.group(1))
                    seconds = int(m.group(2))
                    frac_str = m.group(3)
                    if frac_str:
                        if len(frac_str) == 3:
                            fraction = int(frac_str) / 1000.0
                        else:
                            fraction = int(frac_str) / (10 ** len(frac_str))
                    else:
                        fraction = 0.0
                    time_in_sec = minutes * 60 + seconds + fraction
                    lines.append({"time": time_in_sec, "text": text})

        if has_timestamps and lines:
            lines.sort(key=lambda x: x["time"])
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
            "official music video", "official video", "official mv", "lyric video",
            "lyrics video", "official audio", "full audio", "m/v", "mv", "hd", "4k",
            "visualizer", "performance video", "music video", "cover", "remix",
            "full track", "audio", "video lyric", "mv lyric", "mv official", "mv hd",
            "ost", "lyrics", "lyric", "karaoke"
        ]
        for phrase in noise_phrases:
            cleaned = re.sub(r'(?i)\b' + re.escape(phrase) + r'\b', ' ', cleaned)
            cleaned = re.sub(r'(?i)\b' + re.escape(phrase.replace('/', r'\/')) + r'\b', ' ', cleaned)

        # 6. Remove quotes and feat. suffix
        cleaned = re.sub(r'[\"\'“”„‟‘’＂＇]', '', cleaned)
        cleaned = re.sub(r'\b(ft|feat|featuring)\.?\b.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        # Strip leading/trailing separator junk like "+ |", "-", ":", "/", "•"
        cleaned = re.sub(r'^[-\|\:\+&·•—–｜：／\/\s]+|[-\|\:\+&·•—–｜：／\/\s]+$', '', cleaned)
        return cleaned.strip()

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
        """Extracts likely song-title-only segments (excluding artist name and noise tags)."""
        clean_t = self.clean_title(title)
        norm_a = self._normalize_artist(artist)
        noise_upper = {"OFFICIAL", "MV", "AUDIO", "LYRIC", "LYRICS", "VIDEO", "M/V", "HD", "4K", "VIETSUB", "ENGSUB"}

        segs = []
        # 1. Titles inside CJK brackets 「...」『...』《...》 or quotes '...' / "..."
        for pat in [r'[「『《〈]([^」』》〉]{1,60})[」』》〉]', r"['\"“]([^'\"”]{2,60})['\"”]"]:
            for m in re.findall(pat, title):
                qc = self.clean_title(m)
                if qc and not self._is_artist_part(qc, norm_a) and qc not in segs:
                    segs.append(qc)

        # 2. Non-artist segments from spaced-separator split
        parts = self._split_title_segments(clean_t)
        non_artist = [
            p for p in parts
            if p.upper() not in noise_upper and not self._is_artist_part(p, norm_a)
        ]
        for p in non_artist:
            if p not in segs:
                segs.append(p)

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

        # Check artist / featured artist match against BOTH req_artist and raw req_title (e.g. "Michita ft 愛海")
        res_meta = f"{res_title} {res_artist}".lower()
        req_meta_tokens = set(re.findall(r'[a-z0-9]{3,}|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]{2,}',
                                         f"{req_title} {req_artist}".lower()))
        stop_meta = {'official', 'music', 'video', 'lyric', 'lyrics', 'vietsub', 'engsub', 'feat', 'topic'}
        req_meta_tokens -= stop_meta
        if req_meta_tokens:
            hits = sum(1 for tok in req_meta_tokens if tok in res_meta)
            score += min(220.0, hits * 55.0)

        # Duration match bonus / mismatch penalty
        if target_dur and target_dur > 30.0 and item_dur and item_dur > 30.0:
            diff = abs(float(item_dur) - float(target_dur))
            if diff <= 5.0:
                score += 140.0
            elif diff <= 15.0:
                score += 75.0
            elif diff > 75.0:
                score -= 160.0
            elif diff > 35.0:
                score -= 70.0

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

        # 1. Check local cache first (auto-invalidate legacy unsynced, duration-mismatched, OR wrong-song cached entries!)
        if self.cache:
            cached_data = self.cache.get(clean_t, clean_a)
            if not cached_data and title != clean_t:
                cached_data = self.cache.get(title, artist)
            if cached_data and cached_data.get("lines"):
                src = str(cached_data.get("source") or "")
                is_manual = ("Manual" in src) or ("Custom" in src)
                cached_dur = float(cached_data.get("track_duration") or 0.0)
                dur_changed = (duration > 30.0 and cached_dur > 30.0 and abs(duration - cached_dur) > 15.0)
                cached_title_ok = is_manual or self.is_valid_match(title, cached_data.get("title", ""), req_artist=clean_a)
                if cached_title_ok and (is_manual or (cached_data.get("has_real_timestamps", False) and not dur_changed)):
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

        if is_intl:
            # Pass 1 (SYNCED ONLY): LRCLIB Exact -> LRCLIB Search (ranked!) -> NetEase CloudSearch -> ZingMP3
            data, pf = self._fetch_lrclib_exact(exact_title_query, norm_a or clean_a, duration=duration, require_synced=True)
            if pf and not plain_fallback:
                plain_fallback = pf

            if not data:
                for cand in candidates:
                    data, pf = self._fetch_lrclib_search(cand, req_title=title, req_artist=clean_a, duration=duration, require_synced=True)
                    if pf and not plain_fallback:
                        plain_fallback = pf
                    if data:
                        break
            if not data:
                for cand in candidates[:3]:
                    data = self._fetch_netease_search(cand, req_title=title, req_artist=clean_a)
                    if data:
                        break
            if not data:
                for cand in candidates[:3]:
                    data = self._fetch_zingmp3_search(cand, req_title=title, req_artist=clean_a, duration=duration)
                    if data:
                        break
        else:
            # Pass 1 (SYNCED ONLY): ZingMP3 (strictly validated & ranked) -> LRCLIB Exact -> LRCLIB Search (ranked!) -> NetEase CloudSearch
            for cand in candidates:
                data = self._fetch_zingmp3_search(cand, req_title=title, req_artist=clean_a, duration=duration)
                if data:
                    break
            if not data:
                data, pf = self._fetch_lrclib_exact(exact_title_query, norm_a or clean_a, duration=duration, require_synced=True)
                if pf and not plain_fallback:
                    plain_fallback = pf
            if not data:
                for cand in candidates:
                    data, pf = self._fetch_lrclib_search(cand, req_title=title, req_artist=clean_a, duration=duration, require_synced=True)
                    if pf and not plain_fallback:
                        plain_fallback = pf
                    if data:
                        break
            if not data:
                for cand in candidates[:2]:
                    data = self._fetch_netease_search(cand, req_title=title, req_artist=clean_a)
                    if data:
                        break

        # Pass 2: Use best scored plainLyrics fallback ONLY if zero synced lyrics exist anywhere
        if not data and plain_fallback:
            data = plain_fallback

        if data:
            self._apply_auto_intro_offset(data, duration)
            if self.cache:
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
                req_is_remix = bool(re.search(r'(?i)\b(remix|bootleg|cover|live|lofi|slowed)\b', req_title or ""))

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

                        # Artist match bonus
                        if norm_req_a and norm_req_a in self._fold_latin(artists):
                            score += 150.0
                        # Skip unsolicited remix/bootleg/cover on ZingMP3 so LRCLIB can provide the real original track
                        sug_is_remix = bool(re.search(r'(?i)\b(remix|bootleg|cover|live|lofi|slowed)\b', res_title))
                        if sug_is_remix and not req_is_remix:
                            continue
                        # Duration alignment
                        if duration > 30.0 and sug_dur > 30.0:
                            diff = abs(sug_dur - duration)
                            if diff <= 6.0:
                                score += 120.0
                            elif diff <= 18.0:
                                score += 60.0
                            elif diff > 50.0:
                                score -= 80.0

                        valid_sugs.append((score, res_title, artists, lyric_url))

                valid_sugs.sort(key=lambda x: x[0], reverse=True)
                for _, res_title, artists, lyric_url in valid_sugs:
                    l_resp = requests.get(lyric_url, headers=self.headers, timeout=5)
                    if l_resp.status_code == 200 and l_resp.content:
                        lrc_text = l_resp.content.decode("utf-8", errors="replace").lstrip("\ufeff")
                        parsed = self.parse_lrc(lrc_text)
                        if parsed:
                            return {
                                "title": res_title,
                                "artist": artists,
                                "synced": True,
                                "has_real_timestamps": True,
                                "lines": parsed,
                                "raw_lrc": lrc_text,
                                "source": "ZingMP3"
                            }
        except Exception as e:
            print(f"[ZingMP3 Error] {e}")
        return None

    def _fetch_lrclib_exact(self, title: str, artist: str, duration: float = 0.0, require_synced: bool = False):
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
                if synced:
                    parsed = self.parse_lrc(synced, duration=dur_val)
                    if parsed:
                        synced_dict = {
                            "title": res.get("trackName", title),
                            "artist": res.get("artistName", artist),
                            "synced": True,
                            "has_real_timestamps": True,
                            "lines": parsed,
                            "raw_lrc": synced,
                            "source": "LRCLIB Exact"
                        }
                        # If duration differs significantly (e.g. 4:39 Audio vs 5:26 Official MV),
                        # keep as fallback so ranked LRCLIB Search can find the exact-duration MV sync!
                        if duration > 30.0 and res_dur > 30.0 and abs(res_dur - duration) > 20.0:
                            return None, synced_dict
                        return synced_dict, None
                if plain:
                    parsed = self.parse_lrc(plain, duration=dur_val)
                    plain_dict = {
                        "title": res.get("trackName", title),
                        "artist": res.get("artistName", artist),
                        "synced": True,
                        "has_real_timestamps": False,
                        "plain": plain,
                        "lines": parsed,
                        "source": "LRCLIB Exact (Plain)"
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

                        synced = item.get("syncedLyrics")
                        if synced:
                            parsed = self.parse_lrc(synced, duration=dur_for_parse)
                            if parsed:
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
                                        "lines": parsed,
                                        "raw_lrc": synced,
                                        "source": "LRCLIB Search"
                                    }
                                continue

                        plain = item.get("plainLyrics")
                        if plain:
                            parsed = self.parse_lrc(plain, duration=dur_for_parse)
                            if parsed:
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
                                        "source": "LRCLIB Search (Plain)"
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
                            if parsed and len(parsed) >= 5:
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
        """Returns a list of search result candidates from LRCLIB and ZingMP3 (auto-prioritizes LRCLIB for CJK/intl)."""
        results = []
        if not query:
            return results

        # Automatically resolve YouTube URL if passed as query
        yt_id = self.extract_youtube_id(query)
        if yt_id:
            yt_info = self.fetch_youtube_info(yt_id)
            if yt_info and yt_info.get("title"):
                query = yt_info["title"]

        queries = self.get_search_candidates(query)
        if query.strip() and query.strip() not in queries:
            queries.append(query.strip())

        seen_keys = set()

        def _search_zing():
            for q in queries[:3]:
                try:
                    url = f"https://ac.zingmp3.vn/v1/web/ac-suggestions?query={urllib.parse.quote(q)}"
                    resp = requests.get(url, headers=self.headers, timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("data", {}).get("items", [])
                        for item in items:
                            for sug in item.get("suggestions", []):
                                if sug.get("type") == 1:
                                    title = sug.get("title", "")
                                    artists = ", ".join([a.get("name", "") for a in sug.get("artists", []) if a.get("name")])
                                    lyric_url = sug.get("lyricLink")
                                    key = f"zmp3_{title}_{artists}"
                                    if key not in seen_keys:
                                        seen_keys.add(key)
                                        results.append({
                                            "id": key,
                                            "trackName": title,
                                            "artistName": artists,
                                            "albumName": "ZingMP3",
                                            "duration": sug.get("duration", 210),
                                            "synced": bool(lyric_url),
                                            "syncedLyrics": lyric_url,
                                            "plainLyrics": None,
                                            "source": "ZingMP3"
                                        })
                except Exception as e:
                    print(f"[ZingMP3 Custom Search Error] {e}")

        def _search_lrclib():
            for q in queries[:3]:
                try:
                    url = f"https://lrclib.net/api/search?q={urllib.parse.quote(q)}"
                    resp = requests.get(url, headers=self.headers, timeout=5)
                    if resp.status_code == 200:
                        raw_list = resp.json()
                        if not isinstance(raw_list, list):
                            continue
                        for item in raw_list:
                            item_id = item.get("id")
                            key = f"lrclib_{item_id}"
                            if key not in seen_keys:
                                seen_keys.add(key)
                                results.append({
                                    "id": key,
                                    "trackName": item.get("trackName"),
                                    "artistName": item.get("artistName"),
                                    "albumName": item.get("albumName"),
                                    "duration": item.get("duration"),
                                    "synced": bool(item.get("syncedLyrics")),
                                    "syncedLyrics": item.get("syncedLyrics"),
                                    "plainLyrics": item.get("plainLyrics"),
                                    "source": "LRCLIB"
                                })
                except Exception as e:
                    print(f"[LRCLIB Custom Search Error] {e}")

        if self._has_intl_script(query):
            _search_lrclib()
            _search_zing()
        else:
            _search_zing()
            _search_lrclib()

        return results
