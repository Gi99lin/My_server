# ---- Build from upstream telegram-mcp ----
FROM python:3.13-alpine AS base

WORKDIR /app

# System deps (git for cloning upstream)
RUN apk add --no-cache git curl

# Clone upstream telegram-mcp
RUN git clone --depth 1 https://github.com/chigwell/telegram-mcp.git /tmp/telegram-mcp

# Install Python deps from upstream + uvicorn for SSE transport
COPY requirements-extra.txt /tmp/requirements-extra.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/telegram-mcp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements-extra.txt

# Copy upstream source
RUN cp /tmp/telegram-mcp/main.py /app/main.py

# Copy our SSE entrypoint
COPY sse_entrypoint.py /app/sse_entrypoint.py

# Cleanup
RUN rm -rf /tmp/telegram-mcp

# Non-root user
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
USER appuser

# Runtime env defaults
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MCP_SSE_HOST=0.0.0.0
ENV MCP_SSE_PORT=8932

EXPOSE 8932

# Healthcheck: verify SSE endpoint is reachable
HEALTHCHECK --interval=5s --timeout=3s --retries=5 --start-period=15s \
    CMD curl -fsS http://localhost:8932/health > /dev/null 2>&1 || exit 1

CMD ["python", "sse_entrypoint.py"]
