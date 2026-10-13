import os, time, threading, glob, hmac, json, urllib.request, urllib.parse
from flask import Flask, request, jsonify, send_file, abort
import render as R

app = Flask(__name__)
TOKEN = os.environ.get('RENDER_TOKEN', '')
OUT = os.environ.get('OUT_DIR', '/tmp/renders')
BASE = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
LOCK = threading.Lock()  # one render at a time: keeps CPU/RAM predictable on small free hosts
PROGRESS = {}            # jobId -> {'done': n, 'total': n, 'state': 'queued|rendering|finished', 'since': ts}

def authed():
    h = request.headers.get('Authorization', '')
    return bool(TOKEN) and hmac.compare_digest(h, 'Bearer ' + TOKEN)

def cleanup():
    for f in glob.glob(os.path.join(OUT, '*.mp4')):
        if time.time() - os.path.getmtime(f) > 6 * 3600:
            try: os.remove(f)
            except OSError: pass

@app.get('/health')
def health():
    return jsonify(ok=True, tokenConfigured=bool(TOKEN), piper=bool(os.environ.get('PIPER_MODEL')))

CB_HOSTS = [h.strip().lower() for h in os.environ.get('ALLOWED_CALLBACK_HOSTS', '.app.n8n.cloud').split(',') if h.strip()]

def callback_ok(url):
    """Only https callbacks to an allow-listed host suffix (prevents the service being used to call arbitrary URLs)."""
    try:
        u = urllib.parse.urlparse(url)
    except Exception:
        return False
    host = (u.hostname or '').lower()
    return u.scheme == 'https' and any(host == h.lstrip('.') or host.endswith(h) for h in CB_HOSTS)

def post_callback(url, payload):
    data = json.dumps(payload).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, method='POST', headers={
                'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN})
            urllib.request.urlopen(req, timeout=30).read()
            return True
        except Exception:
            time.sleep(3 * (attempt + 1))
    return False

def keepalive(base, stop):
    """Free hosts sleep after ~15 min without incoming requests; a long render must not be cut off, so ping ourselves."""
    url = base.replace('http://', 'https://') + '/health' if 'localhost' not in base and '127.0.0.1' not in base else base + '/health'
    while not stop.wait(240):
        try:
            urllib.request.urlopen(url, timeout=20).read()
        except Exception:
            pass

def background_render(body, cb, base):
    jid = str(body.get('jobId', ''))
    out = {'jobId': body.get('jobId', ''), 'ownerChatId': str(body.get('ownerChatId', ''))}
    PROGRESS[jid] = {'done': 0, 'total': 0, 'state': 'queued', 'since': time.time()}
    stop = threading.Event()
    threading.Thread(target=keepalive, args=(base, stop), daemon=True).start()   # also covers the wait for the lock
    def prog(done, total):
        PROGRESS[jid] = {'done': done, 'total': total, 'state': 'rendering', 'since': PROGRESS[jid]['since']}
    with LOCK:
        try:
            cleanup()
            res = R.render(body.get('renderSpec'), OUT, brand=os.environ.get('BRAND', ''), progress=prog)
            res['downloadUrl'] = '%s/files/%s.mp4' % (base, res['renderId'])
            res.pop('file')
            out.update(res)
            out.update(success=bool(res['verified']), status='COMPLETED' if res['verified'] else 'UNVERIFIED')
        except R.SpecError as e:
            out.update(success=False, status='FAILED', error='invalid spec: %s' % e)
        except Exception as e:
            out.update(success=False, status='FAILED', error=str(e)[:300])
    stop.set()
    PROGRESS[jid] = dict(PROGRESS.get(jid, {}), state='finished')
    post_callback(cb, out)

@app.get('/status')
def status():
    if not authed():
        abort(401)
    return jsonify(jobs=PROGRESS)

@app.post('/render')
def render():
    if not authed():
        abort(401)
    body = request.get_json(silent=True) or {}
    base = BASE or request.host_url.rstrip('/')
    cb = str(body.get('callbackUrl') or '')
    if cb:
        # Async mode: validate the spec now, render in the background, deliver the result by callback.
        if not callback_ok(cb):
            return jsonify(success=False, status='FAILED', error='callbackUrl host not allowed'), 422
        try:
            R.validate(R.extract_spec(body.get('renderSpec')))
        except R.SpecError as e:
            return jsonify(success=False, status='FAILED', error='invalid spec: %s' % e), 422
        except Exception as e:
            return jsonify(success=False, status='FAILED', error=str(e)[:300]), 422
        threading.Thread(target=background_render, args=(body, cb, base), daemon=True).start()
        return jsonify(status='QUEUED', jobId=body.get('jobId', ''), note='render started; result will be delivered by callback'), 202
    if not LOCK.acquire(timeout=5):
        return jsonify(success=False, status='BUSY', error='another render is running; retry shortly'), 429
    try:
        cleanup()
        res = R.render(body.get('renderSpec'), OUT, brand=os.environ.get('BRAND', ''))
        res['downloadUrl'] = '%s/files/%s.mp4' % (base, res['renderId'])
        res.pop('file')
        return jsonify(success=res['verified'], status='COMPLETED' if res['verified'] else 'UNVERIFIED',
                       jobId=body.get('jobId', ''), **res)
    except R.SpecError as e:
        return jsonify(success=False, status='FAILED', error='invalid spec: %s' % e), 422
    except Exception as e:
        return jsonify(success=False, status='FAILED', error=str(e)[:300]), 500
    finally:
        LOCK.release()

@app.get('/files/<rid>.mp4')
def files(rid):
    if not authed():
        abort(401)
    if not rid.isalnum():
        abort(404)
    p = os.path.join(OUT, rid + '.mp4')
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype='video/mp4')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 7860)))
