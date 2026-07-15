FROM python:3.12-slim-bookworm

ARG APT_MIRROR
ARG PIP_INDEX_URL

RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    fonts-noto-core \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-writer \
    tini \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    fastapi==0.139.0 \
    pillow==12.2.0 \
    pypdfium2==5.11.0 \
    uvicorn==0.50.0

RUN useradd --create-home --home-dir /home/renderer --shell /usr/sbin/nologin renderer

WORKDIR /app
COPY --chown=renderer:renderer app.py .

ENV HOME=/tmp/renderer-home
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8
ENV PYTHONDONTWRITEBYTECODE=1

USER renderer
EXPOSE 8003

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "1", "--no-access-log"]
