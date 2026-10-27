# Official Python multi-platform base, fixed by digest. Install only the browser
# this service uses rather than a complete Chromium/Firefox/WebKit image.
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    CLAUDE_CONFIG_DIR=/var/lib/claude-auth \
    CLAUDE_HOST_CONFIG=/run/secrets/host-config.json

WORKDIR /app
COPY pyproject.toml /app/
RUN python -c 'import tomllib,pathlib; d=tomllib.loads(pathlib.Path("pyproject.toml").read_text()); pathlib.Path("/tmp/requirements.txt").write_text("\n".join(d["project"]["dependencies"]))' \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 pwuser \
    && useradd --uid 1000 --gid 1000 --create-home pwuser \
    && mkdir -p /var/lib/claude-auth /var/lib/claude-host /tmp/claude-host \
    && chown -R 1000:1000 /var/lib/claude-auth /var/lib/claude-host /tmp/claude-host \
    && chmod 700 /var/lib/claude-auth /var/lib/claude-host \
    && chmod -R a+rX /ms-playwright
COPY src /app/src
RUN pip install --no-cache-dir --no-deps .
USER 1000:1000
EXPOSE 8080
VOLUME ["/var/lib/claude-auth", "/var/lib/claude-host"]
ENTRYPOINT ["python", "-m", "claude_host"]
CMD ["serve"]
