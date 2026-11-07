FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/jab
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils texlive-luatex texlive-latex-extra texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*
# Vendor only the needed fonts so builds do not depend on a CTAN mirror.
COPY docker/fonts/ /usr/local/share/texmf/fonts/opentype/public/
RUN mktexlsr
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN groupadd --gid 10001 jab && useradd --uid 10001 --gid jab --create-home jab \
    && mkdir /app/data && chown jab:jab /app/data
COPY backend/ ./backend/
COPY reference/resume-template.tex reference/cover-letter-template.tex ./reference/
COPY --from=frontend /build/dist ./frontend/dist/
# Debian's Lua font loader needs access to its installed data under /usr.
# The non-root runtime cannot write there; application data stays under /app.
ENV TEXMFOUTPUT=/usr
USER jab
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
