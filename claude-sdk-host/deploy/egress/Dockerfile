FROM ginuerzh/gost:2.11.5 AS gost_base

FROM alpine:3.20

# Copy official GOST binary (v2 schema compatible)
COPY --from=gost_base /bin/gost /usr/local/bin/gost

# Install minimal runtime utilities for validation, healthcheck, and log redaction
RUN apk add --no-cache bash jq netcat-openbsd sed

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --retries=3 --start-period=2s \
    CMD nc -z 127.0.0.1 8080 || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
