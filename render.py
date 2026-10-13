"""Vorvia renderer core: text-card videos with spoken voice-over. NO music is ever added.
v1 scope (rights-safe by construction): colored text cards + TTS narration + burned-in captions.
No external images/video/audio are fetched, so there is nothing to license."""
import json, os, re, subprocess, tempfile, hashlib, shutil, textwrap, uuid
from PIL import Image, ImageDraw, ImageFont
import visuals as V
import stock as S

ANIM_FPS = int(os.environ.get('ANIM_FPS', '15'))

MAX_SCENES = int(os.environ.get('MAX_SCENES', '700'))
MAX_TOTAL_SEC = int(os.environ.get('MAX_TOTAL_SEC', '3900'))   # about 65 minutes
MAX_CHARS = 500
WORDS_PER_SEC = 2.3          # measured pace of the voice (used to estimate length before rendering)
LONG_THRESHOLD_SEC = 300     # above this a video is encoded in 'long' mode (smaller bitrate)
FONT_CANDIDATES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
]
PALETTE = ['#0B3D2E', '#12355B', '#3B2A63', '#5B3A12', '#1F4E5F']  # modest, solid, readable

class SpecError(ValueError):
    pass

def extract_spec(raw):
    """Accept a dict, a JSON string, or LLM text containing a ```json block / a JSON object."""
    if isinstance(raw, dict):
        return raw
    s = str(raw or '')
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', s, re.S)
    cands = [m.group(1)] if m else []
    i = s.find('{')
    while i != -1 and len(cands) < 6:
        depth = 0
        for j in range(i, len(s)):
            depth += (s[j] == '{') - (s[j] == '}')
            if depth == 0:
                cands.append(s[i:j + 1]); break
        i = s.find('{', i + 1)
    for c in cands:
        try:
            d = json.loads(c)
            if isinstance(d, dict) and ('scenes' in d or 'chapters' in d):
                return d
        except Exception:
            continue
    raise SpecError('no valid RENDER_SPEC JSON with "scenes" or "chapters" found')

def _sentences(text):
    parts = re.split(r'(?<=[.!?])\s+', re.sub(r'\s+', ' ', str(text or '')).strip())
    return [p for p in parts if p]

def expand_chapters(spec):
    """Long-form specs describe chapters (title + narration + stock phrases); we cut each narration into
    scenes of about 8-17 seconds so the LLM only has to write text, not hundreds of scene objects."""
    out = []
    chapters = spec.get('chapters')
    if not isinstance(chapters, list) or not chapters:
        return out
    for ci, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        title = re.sub(r'\s+', ' ', str(ch.get('title') or 'Chapter %d' % (ci + 1))).strip()[:60]
        stocks = ch.get('stock') or []
        if isinstance(stocks, str):
            stocks = [stocks]
        stocks = [str(x).strip() for x in stocks if str(x).strip()][:12]
        sents = _sentences(ch.get('narration'))
        groups, cur = [], []
        for sn in sents:
            cur.append(sn)
            if len(' '.join(cur).split()) >= 24:
                groups.append(' '.join(cur)); cur = []
        if cur:
            if groups and len(' '.join(cur).split()) < 8:
                groups[-1] += ' ' + ' '.join(cur)
            else:
                groups.append(' '.join(cur))
        for gi, g in enumerate(groups):
            sc = {'text': title, 'voiceover': g[:MAX_CHARS * 2], 'visual': 'title'}
            if stocks:
                sc['stock'] = stocks[gi % len(stocks)]
            out.append(sc)
        for extra in (ch.get('visuals') or [])[:6]:       # optional hand-made data scenes (bars, counter, checklist ...)
            if isinstance(extra, dict):
                out.append(extra)
    return out

def validate(spec):
    scenes = spec.get('scenes')
    if not scenes and spec.get('chapters'):
        scenes = expand_chapters(spec)
    if not isinstance(scenes, list) or not scenes:
        raise SpecError('scenes (or chapters) must be a non-empty list')
    if len(scenes) > MAX_SCENES:
        raise SpecError('too many scenes (max %d)' % MAX_SCENES)
    out, total = [], 0.0
    for k, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            raise SpecError('scene %d is not an object' % k)
        text = str(sc.get('text') or sc.get('onScreenText') or '').strip()
        voice = str(sc.get('voiceover') or sc.get('voiceOver') or sc.get('narration') or '').strip()
        if not text and not voice:
            raise SpecError('scene %d has no text and no voiceover' % k)
        if len(text) > MAX_CHARS or len(voice) > MAX_CHARS * 2:
            raise SpecError('scene %d text too long' % k)
        dur = float(sc.get('duration') or sc.get('durationSec') or 0)
        kind = str(sc.get('visual') or 'title').strip().lower()
        data = sc.get('data') if isinstance(sc.get('data'), dict) else {}
        if len(json.dumps(data)) > 800:
            raise SpecError('scene %d data too large' % k)
        sq = re.sub(r'\s+', ' ', str(sc.get('stock') or '')).strip()[:60]
        out.append({'stock': sq, 'text': text or voice, 'voice': voice or text, 'dur': max(0.0, min(dur, 30.0)),
                    'visual': kind if kind in V.KINDS else 'title', 'data': data})
        total += max(dur, len(voice.split() or text.split()) / WORDS_PER_SEC)
    if total > MAX_TOTAL_SEC:
        raise SpecError('estimated duration %.0fs exceeds limit %ds' % (total, MAX_TOTAL_SEC))
    w = int(spec.get('width') or 720); h = int(spec.get('height') or 1280)
    fps = int(spec.get('fps') or 24)
    if not (240 <= w <= 1920 and 240 <= h <= 1920) or not (6 <= fps <= 30):
        raise SpecError('unsupported width/height/fps')
    return out, w, h, fps, total

def _font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def make_card(path, text, idx, total, w, h, brand=''):
    img = Image.new('RGB', (w, h), PALETTE[idx % len(PALETTE)])
    d = ImageDraw.Draw(img)
    size = max(28, w // 14)
    f = _font(size)
    maxc = max(10, int(w * 0.84 / (size * 0.58)))
    lines = []
    for para in text.split('\n'):
        lines += textwrap.wrap(para, maxc) or ['']
    lh = int(size * 1.35)
    y = (h - lh * len(lines)) // 2
    for ln in lines:
        tw = d.textlength(ln, font=f)
        d.text(((w - tw) / 2, y), ln, font=f, fill='#FFFFFF')
        y += lh
    if brand:
        bf = _font(max(18, w // 30)); bw = d.textlength(brand, font=bf)
        d.text(((w - bw) / 2, h - int(h * 0.06)), brand, font=bf, fill='#CFE8DC')
    d.rectangle([0, h - 8, int(w * (idx + 1) / total), h], fill='#7CD6A8')
    img.save(path)

def run(cmd, timeout=180):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError('%s failed: %s' % (cmd[0], p.stderr[-400:]))
    return p.stdout

def duration(path):
    return float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]).strip())

def tts(text, wav, tmp):
    """Return engine name. piper if PIPER_MODEL is set and installed, else ffmpeg flite, else silence."""
    text = re.sub(r'\s+', ' ', text).strip()
    model = os.environ.get('PIPER_MODEL', '')
    if model and shutil.which('piper') and os.path.exists(model):
        # natural pacing: slightly slower than default, small pauses between sentences.
        # Flag spelling differs between piper-tts 1.2 (underscores) and 1.3+ (hyphens), so try both, then plain.
        base = ['piper', '-m', model, '-f', wav]
        for extra in (['--length-scale', '1.06', '--sentence-silence', '0.3'],
                      ['--length_scale', '1.06', '--sentence_silence', '0.3'], []):
            try:
                p = subprocess.run(base + extra, input=text, capture_output=True, text=True, timeout=120)
                if p.returncode == 0 and os.path.exists(wav) and os.path.getsize(wav) > 1000:
                    return 'piper'
            except Exception:
                pass
    tf = os.path.join(tmp, 'v.txt'); open(tf, 'w').write(text)
    try:
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'flite=textfile=%s:voice=slt' % tf, '-ar', '22050', wav], 120)
        return 'flite'
    except Exception:
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=22050:cl=mono', '-t', '3', wav])
        return 'silent'

# voice polish: remove rumble, gentle compression, broadcast loudness (-16 LUFS), then pad silence to the scene length
VOICE_FX = 'highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=5:release=120,loudnorm=I=-16:TP=-1.5:LRA=9,apad'

def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

class StockCache:
    """Several scenes of a long video share a handful of downloaded clips; each reuse starts at a different offset."""
    def __init__(self, tmp, keep=10):
        self.tmp, self.keep, self.items, self.uses = tmp, keep, {}, {}

    def get(self, query, w, h, idx):
        q = query.lower().strip()
        if q not in self.items:
            path = S.fetch(query, w, h, self.tmp, idx)
            if not path:
                return None, 0.0
            try:
                length = duration(path)
            except Exception:
                length = 0.0
            self.items[q] = (path, length)
            while len(self.items) > self.keep:
                old = next(iter(self.items)); op = self.items.pop(old)[0]
                try: os.remove(op)
                except OSError: pass
        path, length = self.items[q]
        n = self.uses.get(q, 0); self.uses[q] = n + 1
        start = (n * 6.5) % max(1.0, length - 5.0) if length > 8 else 0.0
        return path, start

def render(raw_spec, out_dir, brand='', progress=None):
    spec = extract_spec(raw_spec)
    scenes, w, h, fps, est = validate(spec)
    long_mode = est > LONG_THRESHOLD_SEC
    rid = uuid.uuid4().hex[:16]
    os.makedirs(out_dir, exist_ok=True)
    final = os.path.join(out_dir, rid + '.mp4')
    engines, clips, stock_used = set(), [], []
    # long videos: lower animation rate and a capped bitrate keep render time and file size manageable
    enc = ['-crf', '31', '-maxrate', '900k', '-bufsize', '1800k'] if long_mode else ['-crf', '27']
    with tempfile.TemporaryDirectory() as tmp:
        cache = StockCache(tmp)
        for k, sc in enumerate(scenes):
            png, wav, clip = [os.path.join(tmp, '%d.%s' % (k, e)) for e in ('png', 'wav', 'mp4')]
            engines.add(tts(sc['voice'], wav, tmp))
            dur = max(sc['dur'], duration(wav) + 0.5)
            afps = min(fps, ANIM_FPS)
            bg = None
            if sc.get('stock') and S.enabled():
                sp, start = cache.get(sc['stock'], w, h, k)
                if sp:
                    bg = S.ClipFrames(sp, w, h, afps, start); stock_used.append(sc['stock'])
            scene = V.Scene(sc['visual'], sc['text'], sc['voice'], sc['data'], k, len(scenes), w, h, dur, brand or str(spec.get('brand') or ''), bg)
            # frames are drawn in Python and piped to ffmpeg as raw RGB (no temp image files)
            p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (w, h),
                                  '-framerate', str(afps), '-i', '-', '-i', wav, '-t', '%.2f' % dur, '-af', VOICE_FX,
                                  '-c:v', 'libx264', '-preset', 'ultrafast'] + enc + ['-g', str(afps * 2), '-threads', '1',
                                  '-pix_fmt', 'yuv420p', '-r', str(afps), '-c:a', 'aac', '-b:a', '64k' if long_mode else '128k', '-ar', '44100', '-ac', '1', clip],
                                 stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for n in range(int(dur * afps) + 1):
                    p.stdin.write(scene.frame(n / afps).tobytes())
            except BrokenPipeError:
                pass
            finally:
                try: p.stdin.close()
                except Exception: pass
            if bg: bg.close()
            err = p.stderr.read().decode()[-300:]
            if p.wait() != 0:
                raise RuntimeError('ffmpeg scene encode failed: ' + err)
            clips.append(clip)
            if progress:
                try: progress(k + 1, len(scenes))
                except Exception: pass
        lst = os.path.join(tmp, 'list.txt')
        open(lst, 'w').write(''.join("file '%s'\n" % c for c in clips))
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', '-movflags', '+faststart', final], 1800)
    total = duration(final)
    if total > MAX_TOTAL_SEC * 1.1:
        os.remove(final); raise SpecError('total duration %.0fs exceeds limit %ds' % (total, MAX_TOTAL_SEC))
    info = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', final]))
    kinds = {s['codec_type'] for s in info['streams']}
    size = os.path.getsize(final)
    verified = {'video', 'audio'} <= kinds and total > 1 and size > 1000
    return {'renderId': rid, 'file': final, 'durationSec': round(total, 2), 'bytes': size, 'sha256': _sha256(final),
            'width': w, 'height': h, 'fps': min(fps, ANIM_FPS), 'scenes': len(scenes), 'tts': sorted(engines),
            'verified': bool(verified), 'music': False, 'stockClips': stock_used[:40], 'longMode': long_mode}
