"""Vorvia renderer core: text-card videos with spoken voice-over. NO music is ever added.
v1 scope (rights-safe by construction): colored text cards + TTS narration + burned-in captions.
No external images/video/audio are fetched, so there is nothing to license."""
import json, os, re, subprocess, tempfile, hashlib, shutil, textwrap, uuid
from PIL import Image, ImageDraw, ImageFont
import visuals as V

ANIM_FPS = int(os.environ.get('ANIM_FPS', '15'))

MAX_SCENES, MAX_TOTAL_SEC, MAX_CHARS = 15, 120, 500
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
            if isinstance(d, dict) and 'scenes' in d:
                return d
        except Exception:
            continue
    raise SpecError('no valid RENDER_SPEC JSON with "scenes" found')

def validate(spec):
    scenes = spec.get('scenes')
    if not isinstance(scenes, list) or not scenes:
        raise SpecError('scenes must be a non-empty list')
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
        out.append({'text': text or voice, 'voice': voice or text, 'dur': max(0.0, min(dur, 30.0)),
                    'visual': kind if kind in V.KINDS else 'title', 'data': data})
        total += dur
    w = int(spec.get('width') or 720); h = int(spec.get('height') or 1280)
    fps = int(spec.get('fps') or 24)
    if not (240 <= w <= 1080 and 240 <= h <= 1920) or not (10 <= fps <= 30):
        raise SpecError('unsupported width/height/fps')
    return out, w, h, fps

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
        p = subprocess.run(['piper', '--model', model, '--output_file', wav], input=text, capture_output=True, text=True, timeout=120)
        if p.returncode == 0 and os.path.exists(wav):
            return 'piper'
    tf = os.path.join(tmp, 'v.txt'); open(tf, 'w').write(text)
    try:
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'flite=textfile=%s:voice=slt' % tf, '-ar', '22050', wav], 120)
        return 'flite'
    except Exception:
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=22050:cl=mono', '-t', '3', wav])
        return 'silent'

def render(raw_spec, out_dir, brand=''):
    spec = extract_spec(raw_spec)
    scenes, w, h, fps = validate(spec)
    rid = uuid.uuid4().hex[:16]
    os.makedirs(out_dir, exist_ok=True)
    final = os.path.join(out_dir, rid + '.mp4')
    engines, clips = set(), []
    with tempfile.TemporaryDirectory() as tmp:
        for k, sc in enumerate(scenes):
            png, wav, clip = [os.path.join(tmp, '%d.%s' % (k, e)) for e in ('png', 'wav', 'mp4')]
            engines.add(tts(sc['voice'], wav, tmp))
            dur = max(sc['dur'], duration(wav) + 0.5)
            afps = min(fps, ANIM_FPS)
            scene = V.Scene(sc['visual'], sc['text'], sc['voice'], sc['data'], k, len(scenes), w, h, dur, brand or str(spec.get('brand') or ''))
            # frames are drawn in Python and piped to ffmpeg as raw RGB (no temp image files)
            p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (w, h),
                                  '-framerate', str(afps), '-i', '-', '-i', wav, '-t', '%.2f' % dur, '-af', 'apad',
                                  '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '27', '-g', str(afps * 2), '-threads', '1',
                                  '-pix_fmt', 'yuv420p', '-r', str(afps), '-c:a', 'aac', '-ar', '44100', '-ac', '1', clip],
                                 stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for n in range(int(dur * afps) + 1):
                    p.stdin.write(scene.frame(n / afps).tobytes())
            except BrokenPipeError:
                pass
            finally:
                try: p.stdin.close()
                except Exception: pass
            err = p.stderr.read().decode()[-300:]
            if p.wait() != 0:
                raise RuntimeError('ffmpeg scene encode failed: ' + err)
            clips.append(clip)
        lst = os.path.join(tmp, 'list.txt')
        open(lst, 'w').write(''.join("file '%s'\n" % c for c in clips))
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', '-movflags', '+faststart', final], 300)
    total = duration(final)
    if total > MAX_TOTAL_SEC:
        os.remove(final); raise SpecError('total duration %.0fs exceeds limit %ds' % (total, MAX_TOTAL_SEC))
    info = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', final]))
    kinds = {s['codec_type'] for s in info['streams']}
    size = os.path.getsize(final)
    verified = {'video', 'audio'} <= kinds and total > 1 and size > 1000
    sha = hashlib.sha256(open(final, 'rb').read()).hexdigest()
    return {'renderId': rid, 'file': final, 'durationSec': round(total, 2), 'bytes': size, 'sha256': sha,
            'width': w, 'height': h, 'fps': min(fps, ANIM_FPS), 'scenes': len(scenes), 'tts': sorted(engines),
            'verified': bool(verified), 'music': False}
