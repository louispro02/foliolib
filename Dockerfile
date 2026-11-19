# FolioLib has no third-party dependency: the image only needs Python and the application code.
FROM python:3.13-slim

WORKDIR /app
COPY app/ /app/

# /data is created and owned by the unprivileged user, so a fresh volume is writable with no extra step.
RUN mkdir /data && chown 1000:1000 /data

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    FOLIOLIB_DATA=/data \
    FOLIOLIB_PORT=8080

# Never run as root. The root filesystem can be read-only (see docker-compose.yml): only /data (and /tmp) need to be writable.
USER 1000:1000
VOLUME /data
EXPOSE 8080

# No curl in the image: the check uses Python's standard library.
HEALTHCHECK --interval=60s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('FOLIOLIB_PORT', '8080'), timeout=3).status == 200 else 1)"]

CMD ["python", "main.py", "serve"]
