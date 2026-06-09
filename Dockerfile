# ============================================================
# Stage 1 — build frontend
# ============================================================
FROM node:26-alpine AS frontend
WORKDIR /src
RUN npm install -g pnpm@11.3.0

# Dependencies layer — only invalidates when pnpm-lock.yaml or package.json changes
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json* ./
COPY frontend/package.json ./frontend/package.json
RUN pnpm install --frozen-lockfile

# Source + build — invalidates on any frontend source change, but reuses deps above
COPY frontend ./frontend
RUN pnpm --dir frontend build

# ============================================================
# Stage 2 — runtime image
# ============================================================
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System binaries (rarely change)
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/
COPY --from=cloudflare/cloudflared:latest /usr/local/bin/cloudflared /usr/local/bin/cloudflared

# Layer 1 — external dependencies (cached unless pyproject.toml or uv.lock changes)
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2 — project itself + app source (cheap re-link unless pyproject.toml/uv.lock changes)
COPY README.md ./
COPY hola ./hola
RUN uv sync --frozen --no-dev
COPY --from=frontend /src/frontend/dist ./frontend/dist

EXPOSE 9333
CMD ["uv", "run", "--no-dev", "python", "-m", "hola.main"]
