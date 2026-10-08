"""Vorvia renderer v3: animated, original, programmatically drawn scenes (no external assets, no music).
Every visual is abstract/diagrammatic (circuits, wires, formulas, bars, checklists), so there is nothing to license
and nothing that conflicts with modest-content rules. Pure Pillow, no numpy."""
import math, os, textwrap
from PIL import Image, ImageDraw, ImageFont

FONTS = ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf']
# (top color, bottom color, accent) - dark, readable, never plain black
THEMES = [((8, 26, 48), (16, 74, 110), '#38BDF8'), ((10, 38, 30), (18, 92, 70), '#34D399'),
          ((36, 18, 62), (84, 44, 128), '#C084FC'), ((46, 24, 10), (118, 62, 22), '#FBBF24'),
          ((8, 30, 40), (20, 82, 98), '#22D3EE')]
KINDS = {'title', 'circuit', 'wire_heat', 'formula', 'bars', 'checklist', 'warning', 'counter'}

_fc = {}
def font(size):
    size = int(size)
    if size not in _fc:
        for p in FONTS:
            if os.path.exists(p):
                _fc[size] = ImageFont.truetype(p, size); break
        else:
            _fc[size] = ImageFont.load_default()
    return _fc[size]

def hexrgb(h):
    h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def mix(a, b, k):
    k = max(0.0, min(1.0, k)); return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))

def ease(x):
    x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3

def background(w, h, idx):
    top, bot, _ = THEMES[idx % len(THEMES)]
    img = Image.new('RGB', (w, h)); d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=mix(top, bot, y / h))
    grid = mix(top, bot, 0.35); step = max(40, w // 9)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=grid)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=grid)
    return img

def wrap(d, text, f, maxw):
    words, lines, cur = str(text).split(), [], ''
    for wd in words:
        t = (cur + ' ' + wd).strip()
        if d.textlength(t, font=f) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = wd
    if cur:
        lines.append(cur)
    return lines or ['']

def center_text(d, text, f, cx, y, fill):
    tw = d.textlength(text, font=f); d.text((cx - tw / 2, y), text, font=f, fill=fill)

def clean(s, n=60):
    return ''.join(ch for ch in str(s) if ch.isprintable())[:n]

class Scene:
    """Static layers are built once; frame(t) only draws what moves."""
    def __init__(self, kind, text, voice, data, idx, total, w, h, dur, brand, bg=None):
        self.kind = kind if kind in KINDS else 'title'
        self.text, self.voice, self.idx, self.total = clean(text, 140), clean(voice, 1000), idx, total
        self.w, self.h, self.dur, self.brand = w, h, max(dur, 1.0), clean(brand, 40)
        self.data = data if isinstance(data, dict) else {}
        self.accent = hexrgb(THEMES[idx % len(THEMES)][2])
        self.base = background(w, h, idx)
        self.region = (int(w * 0.08), int(h * 0.30), int(w * 0.92), int(h * 0.74))
        words = self.voice.split(); n = 6
        self.chunks = [' '.join(words[i:i + n]) for i in range(0, len(words), n)] or ['']
        self.bg = bg  # optional ClipFrames: stock footage background
        self._static()

    def _static(self):
        d = ImageDraw.Draw(self.base); w, h = self.w, self.h
        bf = font(max(16, w // 32))
        if self.brand:
            center_text(d, self.brand, bf, w / 2, h - int(h * 0.055), (200, 220, 230))
        self.hf = font(max(30, w // 13))
        self.hlines = wrap(d, self.text, self.hf, w * 0.84)[:4]

    def frame(self, t):
        w, h = self.w, self.h
        if self.bg is not None:
            from PIL import Image as _I
            img = _I.blend(self.bg.next(), _I.new('RGB', (w, h), (0, 0, 0)), 0.5)
            d = ImageDraw.Draw(img)
            if self.brand:
                center_text(d, self.brand, font(max(16, w // 32)), w / 2, h - int(h * 0.055), (230, 240, 245))
        else:
            img = self.base.copy(); d = ImageDraw.Draw(img)
        # headline slides in and fades up
        e = ease(t / 0.6); lh = int(self.hf.size * 1.3); y = int(h * 0.06) + int((1 - e) * 36)
        col = mix((40, 60, 80), (255, 255, 255), e)
        for ln in self.hlines:
            center_text(d, ln, self.hf, w / 2, y, col); y += lh
        d.rectangle([int(w * 0.30), y + 6, int(w * 0.30 + w * 0.40 * e), y + 12], fill=self.accent)
        if self.bg is None:
            getattr(self, 'v_' + self.kind)(d, t)
        # burned-in caption, chunked over the scene duration
        cf = font(max(22, w // 20)); k = min(len(self.chunks) - 1, int(t / self.dur * len(self.chunks)))
        cl = wrap(d, self.chunks[k], cf, w * 0.86)[:2]; cy = int(h * 0.80)
        for ln in cl:
            center_text(d, ln, cf, w / 2, cy, (255, 255, 255)); cy += int(cf.size * 1.3)
        # progress bar across the whole video
        prog = (self.idx + min(1.0, t / self.dur)) / self.total
        d.rectangle([0, h - 8, int(w * prog), h], fill=self.accent)
        return img

    # ---------- visuals ----------
    def v_title(self, d, t):
        x0, y0, x1, y1 = self.region; cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        for k in range(3):
            p = (t * 0.5 + k / 3) % 1.0; r = int(40 + p * min(x1 - x0, y1 - y0) * 0.5)
            c = mix(self.accent, (10, 30, 50), p); d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=5)
        d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=self.accent)

    def _loop_pos(self, s, xl, yt, xr, yb):
        W, H = xr - xl, yb - yt; per = 2 * (W + H); s = (s % 1.0) * per
        if s < W: return xl + s, yt
        s -= W
        if s < H: return xr, yt + s
        s -= H
        if s < W: return xr - s, yb
        s -= W
        return xl, yb - s

    def v_circuit(self, d, t):
        x0, y0, x1, y1 = self.region; xl, xr = x0 + 40, x1 - 40; yt, yb = y0 + 40, y1 - 40
        heat = float(self.data.get('heat', ease(t / self.dur) * 0.8)); wc = (150, 170, 190); wd = 8
        mid = (yt + yb) // 2
        d.line([(xl, yt), (xr, yt)], fill=wc, width=wd); d.line([(xl, yb), (xr, yb)], fill=wc, width=wd)
        d.line([(xr, yt), (xr, mid - 70)], fill=wc, width=wd); d.line([(xr, mid + 70), (xr, yb)], fill=wc, width=wd)
        d.line([(xl, yt), (xl, mid - 28)], fill=wc, width=wd); d.line([(xl, mid + 28), (xl, yb)], fill=wc, width=wd)
        d.line([(xl - 38, mid - 28), (xl + 38, mid - 28)], fill=(255, 255, 255), width=8)       # battery: long plate
        d.line([(xl - 20, mid + 28), (xl + 20, mid + 28)], fill=(255, 255, 255), width=8)       # short plate
        pts = [(xr, mid - 70)]
        for i in range(6):
            pts.append((xr + (26 if i % 2 == 0 else -26), mid - 70 + (i + 1) * 140 / 7))
        pts.append((xr, mid + 70))
        glow = mix((90, 140, 200), (255, 90, 40), heat)
        r = int(24 + 36 * heat)
        d.ellipse([xr - r - 34, mid - r, xr + r - 34 + 68, mid + r], outline=mix((10, 30, 50), glow, 0.6), width=4)
        d.line(pts, fill=glow, width=10)
        f = font(max(18, self.w // 28))
        d.text((xl + 54, mid - 14), 'battery', font=f, fill=(210, 225, 235))
        d.text((xr - 150, mid + 100), 'resistance', font=f, fill=glow)
        n = 14
        for k in range(n):
            x, y = self._loop_pos(t * 0.22 + k / n, xl, yt, xr, yb)
            d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=self.accent)
        d.text((x0 + 10, y1 - 4), 'electrons flowing = current', font=f, fill=(210, 225, 235))

    def v_wire_heat(self, d, t):
        x0, y0, x1, y1 = self.region; cy = (y0 + y1) // 2; L = float(self.data.get('level', ease(t / self.dur)))
        bh = 70; segs = 40; sw = (x1 - x0) / segs
        for i in range(segs):
            local = max(0.0, min(1.0, L * 1.25 - (i / segs) * 0.25 + 0.05 * math.sin(t * 4 + i)))
            c = mix((70, 140, 220), (255, 70, 30), local)
            d.rectangle([x0 + i * sw, cy - bh // 2, x0 + (i + 1) * sw + 1, cy + bh // 2], fill=c)
        d.rounded_rectangle([x0 - 4, cy - bh // 2 - 4, x1 + 4, cy + bh // 2 + 4], radius=14, outline=(230, 240, 250), width=4)
        for k in range(10):
            x = x0 + ((t * 0.3 + k / 10) % 1.0) * (x1 - x0)
            d.ellipse([x - 7, cy - 7, x + 7, cy + 7], fill=(255, 255, 255))
        amp = 8 + 34 * L
        for j in range(4):
            pts = [(x0 + i * (x1 - x0) / 60, cy - bh // 2 - 50 - j * 36 - amp * math.sin(i * 0.5 + t * 5 + j)) for i in range(61)]
            d.line(pts, fill=mix((120, 160, 200), (255, 120, 60), L), width=4)
        f = font(max(18, self.w // 26))
        d.text((x0, cy + bh), 'current (I) →', font=f, fill=(220, 235, 245))
        d.text((x0, cy + bh + int(f.size * 1.5)), 'more current = more heat', font=f, fill=mix((200, 220, 240), (255, 140, 90), L))

    def v_formula(self, d, t):
        x0, y0, x1, y1 = self.region; formula = clean(self.data.get('formula') or self.text, 30)
        f = font(max(40, min(self.w // 7, int((x1 - x0) / max(4, len(formula)) * 1.7))))
        n = int(len(formula) * min(1.0, t / (self.dur * 0.45) )) + 1; shown = formula[:n]
        tw = d.textlength(formula, font=f); fy = y0 + 20
        d.rounded_rectangle([(self.w - tw) / 2 - 24, fy - 16, (self.w + tw) / 2 + 24, fy + f.size + 22], radius=22, outline=self.accent, width=5)
        d.text(((self.w - tw) / 2, fy), shown, font=f, fill=(255, 255, 255))
        legend = [clean(x, 46) for x in (self.data.get('legend') or [])][:4]; lf = font(max(20, self.w // 24)); yy = fy + f.size + 70
        for i, item in enumerate(legend):
            if t > self.dur * (0.35 + 0.15 * i):
                d.ellipse([x0 + 4, yy + 8, x0 + 20, yy + 24], fill=self.accent); d.text((x0 + 34, yy), item, font=lf, fill=(230, 240, 248)); yy += int(lf.size * 1.8)

    def v_bars(self, d, t):
        x0, y0, x1, y1 = self.region; labels = [clean(x, 12) for x in (self.data.get('labels') or ['A', 'B', 'C'])][:6]
        vals = [float(v) for v in (self.data.get('values') or [1, 2, 3])][:len(labels)]
        vals += [0.0] * (len(labels) - len(vals)); top = max(vals) or 1.0; n = len(labels)
        gw = (x1 - x0) / n; f = font(max(16, self.w // 30)); base = y1 - 50; mh = (y1 - y0) - 110
        for i, (lb, v) in enumerate(zip(labels, vals)):
            g = ease((t - 0.15 * i) / (self.dur * 0.5)); bh = int(mh * v / top * g)
            bx0 = x0 + i * gw + gw * 0.15; bx1 = x0 + (i + 1) * gw - gw * 0.15
            d.rounded_rectangle([bx0, base - bh, bx1, base], radius=10, fill=mix(self.accent, (255, 255, 255), 0.1 * i))
            center_text(d, ('%g' % v) if g > 0.5 else '', f, (bx0 + bx1) / 2, base - bh - int(f.size * 1.4), (255, 255, 255))
            center_text(d, lb, f, (bx0 + bx1) / 2, base + 10, (210, 225, 235))
        d.line([(x0, base), (x1, base)], fill=(200, 215, 225), width=3)

    def v_checklist(self, d, t):
        x0, y0, x1, y1 = self.region; items = [clean(x, 44) for x in (self.data.get('items') or [])][:6]
        f = font(max(22, self.w // 22)); y = y0 + 10
        for i, it in enumerate(items):
            if t >= self.dur * (0.08 + 0.7 * i / max(1, len(items))):
                d.rounded_rectangle([x0, y, x0 + 46, y + 46], radius=10, outline=self.accent, width=5)
                d.line([(x0 + 10, y + 24), (x0 + 20, y + 36), (x0 + 38, y + 10)], fill=self.accent, width=7)
                d.text((x0 + 66, y + 4), it, font=f, fill=(255, 255, 255)); y += int(f.size * 2.1)

    def v_warning(self, d, t):
        x0, y0, x1, y1 = self.region; cx, cy = (x0 + x1) // 2, (y0 + y1) // 2; s = 1 + 0.06 * math.sin(t * 5); R = int(150 * s)
        d.polygon([(cx, cy - R), (cx - R * 0.95, cy + R * 0.7), (cx + R * 0.95, cy + R * 0.7)], outline=(255, 190, 40), width=12)
        center_text(d, '!', font(int(R * 1.1)), cx, cy - int(R * 0.55), (255, 190, 40))

    def v_counter(self, d, t):
        x0, y0, x1, y1 = self.region; v = float(self.data.get('value', 0)); unit = clean(self.data.get('unit', ''), 16)
        shown = v * ease(t / (self.dur * 0.6)); s = ('%d' % round(shown)) if abs(v) >= 100 else ('%.1f' % shown)
        center_text(d, s, font(self.w // 3), self.w / 2, (y0 + y1) / 2 - self.w // 5, (255, 255, 255))
        if unit:
            center_text(d, unit, font(self.w // 12), self.w / 2, (y0 + y1) / 2 + self.w // 6, self.accent)
