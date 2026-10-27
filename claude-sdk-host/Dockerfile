# Pinned Playwright Python image based on Ubuntu 24.04 (noble) with Python 3.12
# Matching coordinator dependency pin: playwright==1.64.1
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

# Prevent interactive prompts and configure Python environment
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CLAUDE_CONFIG_DIR=/var/lib/claude-auth \
    CONFIG_PATH=/run/secrets/host-config.json

# Pre-create required directory layout with explicit non-root ownership (pwuser UID:GID 1000:1000)
# - /var/lib/claude-auth: Official Claude authentication persistence volume
# - /var/lib/claude-host: SQLite journal and durable accounting database
# - /tmp/claude-host: Bounded per-session temporary workspace
# - /app: Application code root
RUN mkdir -p /var/lib/claude-auth /var/lib/claude-host /tmp/claude-host /app && \
    chown -R pwuser:pwuser /var/lib/claude-auth /var/lib/claude-host /tmp/claude-host /app && \
    chmod 700 /var/lib/claude-auth /var/lib/claude-host && \
    chmod 1777 /tmp/claude-host

WORKDIR /app

# Copy application package source (src/claude_host and coordinator pyproject.toml)
COPY --chown=pwuser:pwuser pyproject.toml /app/
COPY --chown=pwuser:pwuser src /app/src

# Build and install package at build time. No runtime network installations or updates permitted.
# Official Claude Code CLI is bundled inside claude-agent-sdk wheel; do not install another global CLI.
RUN pip install --no-cache-dir .

# Switch to unprivileged non-root user
USER pwuser

# Expose internal API port (not published externally; accessible on internal network)
EXPOSE 8080

# Volumes for durable state and official auth credentials
VOLUME ["/var/lib/claude-auth", "/var/lib/claude-host"]

# Entrypoint invokes module directly; default subcommand is 'serve'
ENTRYPOINT ["python", "-m", "claude_host"]
CMD ["serve"]
