FROM gogost/gost:3.3.2 AS gost_base

FROM alpine:3.20

# Copy pinned official GOST; legacy operator input is normalized at startup.
COPY --from=gost_base /bin/gost /usr/local/bin/gost

# Install minimal runtime utilities for validation, healthcheck, and log redaction
RUN apk add --no-cache python3 netcat-openbsd ca-certificates

COPY deploy/egress/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY deploy/egress/validate_config.py /usr/local/lib/validate_config.py
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --retries=3 --start-period=2s \
    CMD nc -z 127.0.0.1 8080 || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
