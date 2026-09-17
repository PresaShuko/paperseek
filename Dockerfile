# syntax=docker/dockerfile:1

FROM node:22.14.0-alpine AS web-build

WORKDIR /build/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build


FROM python:3.12.13-slim AS wheel-build

ENV PIP_NO_CACHE_DIR=1
ARG PAPERSEEK_BUILD_COMMIT=unknown
ARG PAPERSEEK_BUILD_DIRTY=false
ENV PAPERSEEK_BUILD_COMMIT=${PAPERSEEK_BUILD_COMMIT} \
    PAPERSEEK_BUILD_DIRTY=${PAPERSEEK_BUILD_DIRTY}

WORKDIR /build/backend

COPY backend/pyproject.toml backend/uv.lock backend/README.md backend/LICENSE backend/THIRD_PARTY_NOTICES.md ./
COPY backend/setup.py ./
COPY backend/src ./src
COPY --from=web-build /build/web/dist ./src/paperseek_community/static
COPY --from=web-build /build/web/src /build/web/src
COPY --from=web-build /build/web/public /build/web/public
COPY --from=web-build /build/web/package.json /build/web/package-lock.json /build/web/

RUN python -m pip wheel --wheel-dir /wheels --no-deps .


FROM python:3.12.13-slim AS runtime

LABEL org.opencontainers.image.title="PaperSeek Community" \
      org.opencontainers.image.version="0.3.0" \
      org.opencontainers.image.source="https://github.com/MingfengHong/paperseek" \
      org.opencontainers.image.ref.name="ghcr.io/mingfenghong/paperseek:0.3.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PAPERSEEK_DATABASE=/var/lib/paperseek/paperseek.db \
    PORT=8765

RUN useradd --create-home --shell /bin/sh paperseek \
    && install -d -o paperseek -g paperseek /var/lib/paperseek

COPY --from=wheel-build /wheels /wheels
RUN python -m pip install /wheels/paperseek-*.whl \
    && rm -rf /wheels

USER paperseek

VOLUME ["/var/lib/paperseek"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ['PORT']; urllib.request.urlopen('http://127.0.0.1:' + port + '/health', timeout=3).read()" || exit 1

ENTRYPOINT ["paperseek"]
CMD ["serve", "--database", "/var/lib/paperseek/paperseek.db", "--host", "0.0.0.0", "--port", "8765"]
