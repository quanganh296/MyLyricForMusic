import qtawesome as qta
from modules.qt_compat import QIcon, QPixmap

class IconFactory:
    """Generates crisp Font Awesome QIcons and QPixmaps via qtawesome."""

    FA_MAP = {
        "search": "fa5s.search",
        "settings": "fa5s.cog",
        "lock": "fa5s.lock",
        "unlock": "fa5s.lock-open",
        "compact": "fa5s.compress-alt",
        "expand": "fa5s.expand-alt",
        "close": "fa5s.times",
        "prev": "fa5s.step-backward",
        "next": "fa5s.step-forward",
        "play_pause": "fa5s.play",
        "music": "fa5s.music",
        "volume": "fa5s.volume-up",
        "mute": "fa5s.volume-mute",
        "youtube": "fa5b.youtube",
        "link": "fa5s.link",
        "edit": "fa5s.edit",
        "paste": "fa5s.paste",
        "bolt": "fa5s.bolt",
        "check": "fa5s.check",
        "save": "fa5s.save",
        "palette": "fa5s.palette",
        "clock": "fa5s.clock",
        "eye": "fa5s.eye",
        "video": "fa5s.video",
        "user": "fa5s.user",
        "info": "fa5s.info-circle",
        "film": "fa5s.film",
        "align_center": "fa5s.align-center",
        "zoom_in": "fa5s.search-plus",
        "zoom_out": "fa5s.search-minus",
        "plus": "fa5s.plus",
        "minus": "fa5s.minus",
        "fullscreen": "fa5s.expand",
        "exit_fullscreen": "fa5s.compress",
        "headphones": "fa5s.headphones",
        "bluetooth": "fa5b.bluetooth-b",
        "battery_full": "fa5s.battery-full",
        "battery_3": "fa5s.battery-three-quarters",
        "battery_2": "fa5s.battery-half",
        "battery_1": "fa5s.battery-quarter",
        "battery_0": "fa5s.battery-empty",
        "language": "fa5s.language",
        "microphone": "fa5s.microphone",
        "chevron_down": "fa5s.chevron-down",
    }

    @classmethod
    def _resolve_name(cls, icon_type: str) -> str:
        return cls.FA_MAP.get(icon_type, icon_type)

    @classmethod
    def create_icon(cls, icon_type: str, color: str = "#e2e8f0", size: int = 24) -> QIcon:
        fa_name = cls._resolve_name(icon_type)
        try:
            return qta.icon(fa_name, color=color)
        except Exception as e:
            print(f"[IconFactory Warning] Failed to load Font Awesome icon '{fa_name}': {e}")
            return QIcon()

    @classmethod
    def create_pixmap(cls, icon_type: str, color: str = "#e2e8f0", size: int = 16) -> QPixmap:
        icon = cls.create_icon(icon_type, color=color, size=size)
        return icon.pixmap(size, size)
