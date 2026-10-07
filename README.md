# Vorvia Renderer (v1)

Small HTTP service that turns the Video Agent's RENDER_SPEC into a real MP4: colored text cards + spoken voice-over.
**No music is ever added. No external images/audio/video are fetched** (nothing to license).

## Contract (matches MyBecoAi "Video Render Gateway")
`POST /render`  header `Authorization: Bearer <RENDER_TOKEN>`
body: `{ "jobId": "...", "renderSpec": <object | JSON string | LLM text containing a ```json block> }`

RENDER_SPEC schema:
```json
{"width":720,"height":1280,"fps":24,"brand":"Vorvia Media",
 "scenes":[{"text":"on-screen text","voiceover":"spoken words","duration":4}]}
```
Limits: <=15 scenes, <=120 s total, 240..1080 x 240..1920, 10..30 fps.

Response on success: `status:"COMPLETED", verified:true, renderId, durationSec, bytes, sha256, downloadUrl, tts, music:false`.
`verified` is true only after ffprobe confirms a video AND an audio stream and a real duration.
`GET /files/<renderId>.mp4` (same Bearer token). Files are deleted after 6 hours.

## Environment
- `RENDER_TOKEN` (required, long random string; the service refuses all requests without it)
- `PUBLIC_BASE_URL` (e.g. https://your-host) so downloadUrl is correct behind a proxy
- `BRAND` (optional footer text)
- `PIPER_MODEL` (optional, set automatically by the Dockerfile if a voice was baked in)

## Run
```
docker build -t vorvia-renderer .
docker run -p 7860:7860 -e RENDER_TOKEN=change-me -e PUBLIC_BASE_URL=http://localhost:7860 vorvia-renderer
curl localhost:7860/health
```
Tests: `python3 test_render.py` (needs ffmpeg + pillow + flask).

## Honest limits
- English voice only in v1 (flite/Piper English). Arabic narration and Arabic on-screen text need an Arabic TTS voice and a font with text shaping: not included.
- Visuals are plain cards. Stock footage/images need a licensed source added later.
- One render at a time (free hosts are small). A 60 s video may take ~1-2 min on a free CPU; the n8n node timeout is 120 s.
- This service does NOT publish anywhere.
