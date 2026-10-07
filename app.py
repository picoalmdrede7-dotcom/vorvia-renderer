import os, time, threading, glob, hmac
from flask import Flask, request, jsonify, send_file, abort
import render as R

app = Flask(__name__)
TOKEN = os.environ.get('RENDER_TOKEN', '')
OUT = os.environ.get('OUT_DIR', '/tmp/renders')
BASE = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
LOCK = threading.Lock()  # one render at a time: keeps CPU/RAM predictable on small free hosts

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

@app.post('/render')
def render():
    if not authed():
        abort(401)
    body = request.get_json(silent=True) or {}
    if not LOCK.acquire(timeout=5):
        return jsonify(success=False, status='BUSY', error='another render is running; retry shortly'), 429
    try:
        cleanup()
        res = R.render(body.get('renderSpec'), OUT, brand=os.environ.get('BRAND', ''))
        base = BASE or request.host_url.rstrip('/')
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
