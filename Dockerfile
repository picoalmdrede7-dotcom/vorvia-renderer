FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# OPTIONAL better voice (Piper). Leave PIPER_VOICE_URL empty to use the built-in ffmpeg "flite" voice (robotic but zero-setup).
# Verify the voice URL and its license on the official Piper voices page before enabling.
ARG PIPER_VOICE_URL=""
RUN if [ -n "$PIPER_VOICE_URL" ]; then pip install --no-cache-dir piper-tts \
    && mkdir -p /voices && curl -fsSL "$PIPER_VOICE_URL" -o /voices/voice.onnx \
    && curl -fsSL "$PIPER_VOICE_URL.json" -o /voices/voice.onnx.json \
    && echo "piper installed"; fi
ENV PIPER_MODEL="" PORT=7860 OUT_DIR=/tmp/renders
COPY render.py app.py ./
RUN useradd -m app && mkdir -p /tmp/renders && chown app /tmp/renders
USER app
EXPOSE 7860
# one worker + lock in app.py: one render at a time keeps RAM/CPU predictable on small hosts
CMD ["sh","-c","if [ -f /voices/voice.onnx ]; then export PIPER_MODEL=/voices/voice.onnx; fi; exec gunicorn -w 1 --threads 2 --timeout 300 -b 0.0.0.0:${PORT} app:app"]
