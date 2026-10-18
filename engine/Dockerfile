# Browser engine: headful Chromium on Xvfb with DevTools on :9222, plus x11vnc + websockify and the
# pinned noVNC 1.3.0 mobile handoff viewer. Build from the repo root:
#   docker buildx build --platform linux/amd64,linux/arm64 -f engine/Dockerfile .

# ---- viewer: stock noVNC 1.3.0 (checksum-pinned) + the phone controls -------------------------------
FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4 AS viewer
ARG NOVNC_VERSION=1.3.0
ARG NOVNC_SHA256=ee8f91514c9ce9f4054d132f5f97167ee87d9faa6630379267e569d789290336
COPY viewer/ /src/viewer/
RUN wget -q -O /tmp/novnc.tar.gz "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz" \
 && echo "${NOVNC_SHA256}  /tmp/novnc.tar.gz" | sha256sum -c - \
 && mkdir /tmp/novnc && tar -xzf /tmp/novnc.tar.gz -C /tmp/novnc --strip-components=1 \
 && python3 /src/viewer/build_viewer.py /tmp/novnc /out

# ---- engine -----------------------------------------------------------------------------------------
FROM debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      chromium xvfb x11vnc python3 python3-websockify \
      fonts-liberation fonts-dejavu-core fonts-noto-color-emoji ca-certificates \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/* \
 && useradd --uid 1000 --user-group --home-dir /tmp --no-create-home --shell /usr/sbin/nologin browser
COPY --from=viewer /out /opt/viewer
COPY engine/engine.py /opt/engine/engine.py
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VIEWER_ROOT=/opt/viewer
USER 1000:1000
EXPOSE 9222 6080 6081
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:6081/health',timeout=3)"
ENTRYPOINT ["python3", "/opt/engine/engine.py"]
