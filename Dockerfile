FROM python:3.14-slim-bookworm AS build

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall --yes pip

FROM ubuntu:24.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8

# Use Noble's OpenSSL 3.0 and security-maintained system libraries.
# Only the CPython installation and application wheels come from the build stage.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates netbase tzdata libbz2-1.0 libdb5.3t64 libexpat1 libffi8 \
        libgdbm-compat4t64 liblzma5 libncursesw6 libreadline8t64 \
        libsqlite3-0 libssl3t64 libstdc++6 libuuid1 libzstd1 zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/ /usr/local/
RUN ldconfig \
    && python -c "import bz2, ctypes, curses, dbm.gnu, lzma, readline, sqlite3, ssl, uuid; import argon2, compression.zstd, fastapi, psycopg, uvicorn; assert ssl.OPENSSL_VERSION_INFO[:2] == (3, 0); assert ssl.create_default_context().get_ca_certs()"

WORKDIR /app
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
