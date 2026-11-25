import os
import json
import hashlib

class LyricsCache:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)

    def _get_key(self, title: str, artist: str) -> str:
        raw = f"{title.strip().lower()} - {artist.strip().lower()}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    def get(self, title: str, artist: str):
        key = self._get_key(title, artist)
        file_path = os.path.join(self.cache_dir, f"{key}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Cache Error] Failed to read cache for {title}: {e}")
        return None

    def set(self, title: str, artist: str, data: dict):
        key = self._get_key(title, artist)
        file_path = os.path.join(self.cache_dir, f"{key}.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Cache Error] Failed to write cache for {title}: {e}")
