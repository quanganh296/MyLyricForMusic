import colorsys
from io import BytesIO
from PIL import Image, ImageFilter
from modules.qt_compat import QPixmap, QImage


def _relative_luminance(r: int, g: int, b: int) -> float:
    """Compute WCAG relative luminance for sRGB values (0..255)."""
    def lin(c):
        v = c / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _pil_from_source(source) -> Image.Image:
    """Convert raw image bytes, PIL Image, or QImage into an RGB PIL Image."""
    if source is None:
        return None
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    if isinstance(source, (bytes, bytearray)):
        try:
            return Image.open(BytesIO(source)).convert("RGB")
        except Exception:
            return None
    if isinstance(source, QImage):
        try:
            if source.isNull():
                return None
            qimg = source.convertToFormat(QImage.Format.Format_RGB888)
            w, h = qimg.width(), qimg.height()
            bpl = qimg.bytesPerLine()
            ptr = qimg.bits()
            ptr.setsize(h * bpl)
            return Image.frombytes("RGB", (w, h), bytes(ptr), "raw", "RGB", bpl)
        except Exception:
            return None
    return None


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    """Convert RGB PIL Image to QPixmap cleanly."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class ThemeExtractor:
    """Extracts a harmonious adaptive color palette and blurred backdrop from video artwork/frames."""

    DEFAULT_PALETTE = {
        "active_color": "#7dd3fc",
        "sub_color": "rgba(226, 232, 240, 0.75)",
        "far_color": "rgba(203, 213, 225, 0.42)",
        "scrim_rgb": (15, 23, 42),
        "border_rgba": "rgba(125, 211, 252, 0.35)",
        "accent_hex": "#38bdf8",
    }

    @classmethod
    def is_browser_placeholder_icon(cls, source) -> bool:
        """
        Detects generic browser/transition icons sent by Windows GSMTC during tab or video switches
        (such as the 4-color Google Chrome logo, Google 'G' icon, tiny favicons, or blank frames).
        Returns True when the image should NOT be used as the video's Mode 1 background.
        """
        if source is None:
            return True

        try:
            if isinstance(source, (bytes, bytearray)):
                raw_img = Image.open(BytesIO(source))
            elif isinstance(source, Image.Image):
                raw_img = source
            else:
                raw_img = _pil_from_source(source)
                if raw_img is None:
                    return True

            orig_w, orig_h = raw_img.size
            if orig_w <= 0 or orig_h <= 0:
                return True

            # 1. Tiny browser favicons (16/32/48/64px) are never real video/album artwork
            if max(orig_w, orig_h) <= 64:
                return True

            rgba = raw_img.convert("RGBA")
            rgb = rgba.convert("RGB")

            # 2. Blank / solid-color loading frames
            tiny = rgb.resize((32, 32), Image.Resampling.BILINEAR)
            tiny_px = list(tiny.getdata())
            if tiny_px:
                r_vals = [p[0] for p in tiny_px]
                g_vals = [p[1] for p in tiny_px]
                b_vals = [p[2] for p in tiny_px]
                if max(max(r_vals) - min(r_vals), max(g_vals) - min(g_vals), max(b_vals) - min(b_vals)) < 12:
                    return True

            # 3. Square-ish icons: check for Chrome 4-color circular logo & Google 'G' logo
            aspect = orig_w / max(1, orig_h)
            if 0.80 <= aspect <= 1.25:
                small = rgba.resize((64, 64), Image.Resampling.BILINEAR)
                px = small.load()

                # Auto-trim uniform or transparent outer padding (Chrome often centers its logo in a tile)
                corners = [px[0, 0], px[63, 0], px[0, 63], px[63, 63]]
                transparent_corners = sum(1 for c in corners if c[3] < 40)
                white_corners = sum(1 for c in corners if c[3] >= 40 and c[0] > 230 and c[1] > 230 and c[2] > 230)
                dark_corners = sum(1 for c in corners if c[3] >= 40 and c[0] < 35 and c[1] < 35 and c[2] < 35)

                bg_ref = None
                if transparent_corners >= 3:
                    bg_ref = "transparent"
                elif white_corners >= 3 or dark_corners >= 3:
                    bg_ref = (
                        sum(c[0] for c in corners) // 4,
                        sum(c[1] for c in corners) // 4,
                        sum(c[2] for c in corners) // 4,
                    )

                work = small
                if bg_ref is not None:
                    x0, y0, x1, y1 = 64, 64, -1, -1
                    for y in range(64):
                        for x in range(64):
                            r, g, b, a = px[x, y]
                            if bg_ref == "transparent":
                                is_fg = (a >= 40)
                            else:
                                is_fg = (a >= 40) and (abs(r - bg_ref[0]) + abs(g - bg_ref[1]) + abs(b - bg_ref[2]) > 38)
                            if is_fg:
                                if x < x0: x0 = x
                                if y < y0: y0 = y
                                if x > x1: x1 = x
                                if y > y1: y1 = y
                    if x1 > x0 + 14 and y1 > y0 + 14:
                        bw, bh = x1 - x0 + 1, y1 - y0 + 1
                        if 0.78 <= (bw / bh) <= 1.28:
                            work = small.crop((x0, y0, x1 + 1, y1 + 1)).resize((64, 64), Image.Resampling.BILINEAR)

                wpx = work.load()

                def _zone_hue_ratio(rx0, ry0, rx1, ry1, predicate):
                    matched = 0
                    opaque = 0
                    for yy in range(ry0, ry1):
                        for xx in range(rx0, rx1):
                            r, g, b, a = wpx[xx, yy]
                            if a < 40:
                                continue
                            opaque += 1
                            h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                            if predicate(h * 360.0, s, v):
                                matched += 1
                    return (matched / opaque) if opaque >= 12 else 0.0

                is_blue = lambda h, s, v: 190.0 <= h <= 245.0 and s >= 0.38 and v >= 0.35
                is_red = lambda h, s, v: (h <= 22.0 or h >= 338.0) and s >= 0.38 and v >= 0.35
                is_green = lambda h, s, v: 95.0 <= h <= 165.0 and s >= 0.32 and v >= 0.30
                is_yellow = lambda h, s, v: 26.0 <= h <= 68.0 and s >= 0.38 and v >= 0.45

                # Chrome circular logo: Blue center, Red top, Green bottom-left, Yellow bottom-right
                c_blue = _zone_hue_ratio(20, 20, 44, 44, is_blue)
                t_red = _zone_hue_ratio(12, 2, 52, 24, is_red)
                bl_green = _zone_hue_ratio(2, 26, 32, 62, is_green)
                br_yellow = _zone_hue_ratio(32, 24, 62, 62, is_yellow)
                if c_blue >= 0.16 and t_red >= 0.16 and bl_green >= 0.16 and br_yellow >= 0.16:
                    return True

                # Google 'G' logo: Red top, Yellow left, Green bottom, Blue right, with neutral/transparent corners
                if transparent_corners >= 3 or white_corners >= 3 or dark_corners >= 3:
                    g_red = _zone_hue_ratio(12, 0, 52, 22, is_red)
                    g_yellow = _zone_hue_ratio(0, 14, 24, 50, is_yellow)
                    g_green = _zone_hue_ratio(12, 42, 52, 64, is_green)
                    g_blue = _zone_hue_ratio(34, 24, 64, 54, is_blue)
                    if g_red >= 0.14 and g_yellow >= 0.14 and g_green >= 0.14 and g_blue >= 0.14:
                        return True

            return False
        except Exception:
            return False

    @classmethod
    def extract_adaptive_palette(cls, source) -> dict:
        img = _pil_from_source(source)
        if img is None:
            return cls.DEFAULT_PALETTE.copy()

        try:
            small = img.resize((64, 64), Image.Resampling.BILINEAR)
            pixels = list(small.getdata())
            n = len(pixels)
            if n == 0:
                return cls.DEFAULT_PALETTE.copy()

            # 1. Compute average ambient color for deep tinted background scrim
            avg_r = sum(p[0] for p in pixels) / n
            avg_g = sum(p[1] for p in pixels) / n
            avg_b = sum(p[2] for p in pixels) / n
            ah, asat, aval = colorsys.rgb_to_hsv(avg_r / 255.0, avg_g / 255.0, avg_b / 255.0)
            scrim_r, scrim_g, scrim_b = colorsys.hsv_to_rgb(ah, min(asat, 0.55), min(max(aval * 0.25, 0.06), 0.16))
            scrim_rgb = (int(scrim_r * 255), int(scrim_g * 255), int(scrim_b * 255))

            # 2. Bucket vibrant pixels into 36 hue bins (10 degrees each)
            buckets = [[] for _ in range(36)]
            bucket_weights = [0.0] * 36

            for r, g, b in pixels:
                h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                if s >= 0.18 and 0.18 <= v <= 0.96:
                    idx = int(h * 36) % 36
                    weight = (s ** 1.3) * (0.4 + 0.6 * v)
                    buckets[idx].append((h, s, v, weight))
                    bucket_weights[idx] += weight

            best_idx = max(range(36), key=lambda i: bucket_weights[i])
            if bucket_weights[best_idx] > 5.0 and buckets[best_idx]:
                # Weighted average hue & saturation from winning bucket
                total_w = sum(x[3] for x in buckets[best_idx])
                win_h = sum(x[0] * x[3] for x in buckets[best_idx]) / total_w
                win_s = sum(x[1] * x[3] for x in buckets[best_idx]) / total_w

                # Craft vibrant, high-contrast active lyric color matching video hue
                target_s = max(0.32, min(win_s * 0.85, 0.68))
                target_v = 0.98

                # Guarantee strong perceived luminance (WCAG contrast against dark blurred backdrop)
                for _ in range(10):
                    ar, ag, ab = colorsys.hsv_to_rgb(win_h, target_s, target_v)
                    ri, gi, bi = int(ar * 255), int(ag * 255), int(ab * 255)
                    if _relative_luminance(ri, gi, bi) >= 0.56:
                        break
                    target_s = max(0.18, target_s - 0.07)
                    target_v = min(1.0, target_v + 0.02)

                active_hex = f"#{ri:02x}{gi:02x}{bi:02x}"

                # Harmonious softer tint for neighboring lines
                sr, sg, sb = colorsys.hsv_to_rgb(win_h, min(target_s * 0.35, 0.25), 0.94)
                sub_rgba = f"rgba({int(sr*255)}, {int(sg*255)}, {int(sb*255)}, 0.76)"
                far_rgba = f"rgba({int(sr*255)}, {int(sg*255)}, {int(sb*255)}, 0.42)"
                border_rgba = f"rgba({ri}, {gi}, {bi}, 0.38)"
                accent_hex = active_hex
            else:
                # Monochrome / neutral video -> crisp warm white
                active_hex = "#f8fafc"
                sub_rgba = "rgba(226, 232, 240, 0.75)"
                far_rgba = "rgba(203, 213, 225, 0.40)"
                border_rgba = "rgba(255, 255, 255, 0.28)"
                accent_hex = "#e2e8f0"

            return {
                "active_color": active_hex,
                "sub_color": sub_rgba,
                "far_color": far_rgba,
                "scrim_rgb": scrim_rgb,
                "border_rgba": border_rgba,
                "accent_hex": accent_hex,
            }
        except Exception as e:
            print(f"[ThemeExtractor Error] {e}")
            return cls.DEFAULT_PALETTE.copy()

    @classmethod
    def create_blurred_background(cls, source, target_w: int = 520, target_h: int = 280,
                                  blur_radius: int = 26, scrim_rgb: tuple = None) -> QPixmap:
        img = _pil_from_source(source)
        if img is None:
            return QPixmap()

        try:
            # Center-crop to target aspect ratio (cover fill without stretching)
            iw, ih = img.size
            target_ratio = max(0.2, target_w / max(1, target_h))
            img_ratio = iw / max(1, ih)

            if img_ratio > target_ratio:
                new_w = int(ih * target_ratio)
                left = max(0, (iw - new_w) // 2)
                img = img.crop((left, 0, left + new_w, ih))
            else:
                new_h = int(iw / target_ratio)
                top = max(0, (ih - new_h) // 2)
                img = img.crop((0, top, iw, top + new_h))

            # Resize to working resolution and apply rich Gaussian blur
            work_w = min(520, max(240, target_w))
            work_h = max(120, int(work_w / target_ratio))
            blurred = img.resize((work_w, work_h), Image.Resampling.BILINEAR)
            blurred = blurred.filter(ImageFilter.GaussianBlur(radius=blur_radius))

            # Blend with deep tinted scrim so blurred video shines through while lyrics stay crisp
            if scrim_rgb is None:
                scrim_rgb = (12, 16, 28)
            overlay = Image.new("RGB", (work_w, work_h), scrim_rgb)
            blended = Image.blend(blurred, overlay, alpha=0.52)

            return _pil_to_qpixmap(blended)
        except Exception as e:
            print(f"[ThemeExtractor Blur Error] {e}")
            return QPixmap()

