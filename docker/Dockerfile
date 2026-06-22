# ── Spendify — Dockerfile ────────────────────────────────────────────────────
# Single-stage build con uv: evita problemi di symlink nei multi-stage copy.
# Build:  docker build -t spendify .
# Run:    docker run -p 8501:8501 --env-file .env spendify

# Pinned to 3.14 (matches Dependabot bump 2026-06-22; pyproject.toml upper bound
# is kept one minor ahead of the pinned image so uv sync can always find an
# interpreter — change both together when bumping).
FROM python:3.14-slim

# Pull the latest Debian security patches before installing anything else.
# The base `python:3.14-slim` image is only rebuilt every few weeks, so its
# system packages routinely lag behind upstream CVE fixes (Trivy was flagging
# HIGH severity findings on libcap2 / libsystemd0 / libldap-common despite
# Debian having published the patches already). Running `apt-get upgrade`
# at build time picks them up without waiting for the python:slim image to
# refresh.
RUN apt-get update -qq && \
    apt-get -y -qq upgrade && \
    apt-get install -y -qq --no-install-recommends gcc g++ cmake && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Installa uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Non scaricare Python separato: usa quello di sistema già presente nell'image
ENV UV_PYTHON_DOWNLOADS=0
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copia solo i file di dipendenze per sfruttare la cache Docker
COPY pyproject.toml uv.lock ./

# Installa dipendenze nella venv (senza dev/test)
RUN uv sync --frozen --no-dev --no-install-project

# Copia il codice sorgente
COPY . .

# Aggiungi la venv al PATH
ENV PATH="/app/.venv/bin:$PATH"

# Directory dove il DB e i log verranno montati come volume
VOLUME ["/app/data", "/app/logs"]

# Porta Streamlit
EXPOSE 8501

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# Entrypoint — uv run attiva automaticamente la venv e risolve il symlink Python
CMD ["uv", "run", "streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
