"""Optional licensed stock footage (Pexels API). Disabled unless PEXELS_API_KEY is set.
Pexels license: free for commercial use, attribution optional; do not imply endorsement,
do not show identifiable people in a bad light, do not resell the clips as stock."""
import os, re, subprocess, json
import urllib.request, urllib.parse
from PIL import Image

KEY = os.environ.get('PEXELS_API_KEY', '').strip()
PIXABAY_KEY = os.environ.get('PIXABAY_API_KEY', '').strip()
MAX_BYTES = 30 * 1024 * 1024

def enabled():
    return bool(KEY or PIXABAY_KEY)

def _download(link, path):
    total = 0
    with urllib.request.urlopen(urllib.request.Request(link, headers={'User-Agent': 'vorvia-renderer/1.0'}), timeout=30) as r, open(path, 'wb') as out:
        while True:
            b = r.read(65536)
            if not b:
                return path
            total += len(b)
            if total > MAX_BYTES:
                return None
            out.write(b)

def _fetch_pixabay(q, w, h, tmp, idx):
    url = 'https://pixabay.com/api/videos/?' + urllib.parse.urlencode(
        {'key': PIXABAY_KEY, 'q': q, 'video_type': 'film', 'safesearch': 'true', 'per_page': 10, 'order': 'popular'})
    data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'vorvia-renderer/1.0'}), timeout=20).read().decode())
    for v in data.get('hits', []):
        if v.get('duration', 0) < 4:
            continue
        for size in ('small', 'medium', 'tiny'):
            f = (v.get('videos') or {}).get(size) or {}
            if f.get('url') and int(f.get('width') or 0) >= 640:
                return _download(f['url'], os.path.join(tmp, 'stock%d.mp4' % idx))
    return None

def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={'Authorization': KEY, 'User-Agent': 'vorvia-renderer/1.0'})
    return urllib.request.urlopen(req, timeout=timeout)

def fetch(query, w, h, tmp, idx):
    """Download one portrait/landscape clip for the query. Returns file path or None."""
    if not (KEY or PIXABAY_KEY):
        return None
    q = re.sub(r'[^A-Za-z0-9 ,\-]', ' ', str(query))[:60].strip()
    if not q:
        return None
    try:
        if not KEY:
            return _fetch_pixabay(q, w, h, tmp, idx)
        orient = 'portrait' if h >= w else 'landscape'
        url = 'https://api.pexels.com/v1/videos/search?' + urllib.parse.urlencode(
            {'query': q, 'orientation': orient, 'size': 'medium', 'per_page': 8})
        data = json.loads(_get(url).read().decode())
        best = None
        for v in data.get('videos', []):
            if v.get('duration', 0) < 4:
                continue
            for f in v.get('video_files', []):
                if f.get('file_type') != 'video/mp4' or not f.get('link'):
                    continue
                fw, fh = int(f.get('width') or 0), int(f.get('height') or 0)
                if fw < 480 or fh < 480 or fw > 1300 or fh > 2000:
                    continue
                score = abs(fw - w) + abs(fh - h) + (0 if (fh >= fw) == (h >= w) else 5000)
                if best is None or score < best[0]:
                    best = (score, f['link'])
            if best:
                break
        if not best:
            return None
        path = os.path.join(tmp, 'stock%d.mp4' % idx)
        total = 0
        with urllib.request.urlopen(urllib.request.Request(best[1], headers={'User-Agent': 'vorvia-renderer/1.0'}), timeout=30) as r, open(path, 'wb') as out:
            while True:
                b = r.read(65536)
                if not b:
                    break
                total += len(b)
                if total > MAX_BYTES:
                    return None
                out.write(b)
        return path
    except Exception:
        return None

class ClipFrames:
    """Reads a looping clip as raw RGB frames scaled/cropped to w x h."""
    def __init__(self, path, w, h, fps):
        self.w, self.h = w, h
        self.p = subprocess.Popen(
            ['ffmpeg', '-loglevel', 'error', '-stream_loop', '-1', '-i', path, '-an', '-vf',
             'fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d' % (fps, w, h, w, h),
             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.last = Image.new('RGB', (w, h), (10, 20, 30))

    def next(self):
        n = self.w * self.h * 3
        buf = self.p.stdout.read(n)
        if buf and len(buf) == n:
            self.last = Image.frombytes('RGB', (self.w, self.h), buf)
        return self.last

    def close(self):
        try:
            self.p.kill()
        except Exception:
            pass
