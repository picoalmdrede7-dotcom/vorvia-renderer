FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Neural voice (Piper). Default: en_GB "cori" medium, a single female UK English voice trained on LibriVox recordings,
# model card license: PUBLIC DOMAIN (safe for monetized videos). Set the PIPER_VOICE_URL env var in Render to change it,
# or set it to an empty string to fall back to the robotic ffmpeg "flite" voice. Check any other voice's license first:
# several Piper voices (ryan, hfc_female...) are CC BY-NC-SA, i.e. NOT allowed for commercial use.
ARG PIPER_VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/medium/en_GB-cori-medium.onnx"
RUN if [ -n "$PIPER_VOICE_URL" ]; then pip install --no-cache-dir piper-tts \
    && mkdir -p /voices && curl -fsSL "$PIPER_VOICE_URL" -o /voices/voice.onnx \
    && curl -fsSL "$PIPER_VOICE_URL.json" -o /voices/voice.onnx.json \
    && echo "piper installed"; fi
ENV PIPER_MODEL="" PORT=7860 OUT_DIR=/tmp/renders
COPY render.py app.py visuals.py stock.py ./
RUN useradd -m app && mkdir -p /tmp/renders && chown app /tmp/renders
USER app
EXPOSE 7860
# one worker + lock in app.py: one render at a time keeps RAM/CPU predictable on small hosts
CMD ["sh","-c","if [ -f /voices/voice.onnx ]; then export PIPER_MODEL=/voices/voice.onnx; fi; exec gunicorn -w 1 --threads 2 --timeout 300 -b 0.0.0.0:${PORT} app:app"]
