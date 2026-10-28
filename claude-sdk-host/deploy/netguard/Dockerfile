FROM alpine:3.20

# Install nftables, iproute2, and bash for atomic firewall management
RUN apk add --no-cache nftables iproute2 bash

COPY deploy/netguard/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh && mkdir -p /run/netguard

HEALTHCHECK --interval=5s --timeout=3s --retries=3 --start-period=2s \
    CMD nft list table inet netguard >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
