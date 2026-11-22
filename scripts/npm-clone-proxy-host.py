#!/usr/bin/env python3
"""Clone an Nginx Proxy Manager proxy host to a new domain and backend address.

Usage (run it yourself; it asks for the NPM login and never stores or prints it):
    python3 npm-clone-proxy-host.py <source host id> <new domain> <old backend ip> <new backend ip> [...more triples]

Example (the tms-next copy on gigglin-dev, 2026-11-21):
    python3 npm-clone-proxy-host.py 26 tms-next.gigglin.tech 10.10.30.10 10.10.40.10 \
                                    27 tms-next-files.gigglin.tech 10.10.30.10 10.10.40.10

Copies forward scheme/port, websocket/HTTP2/block-exploits flags, custom locations and advanced config, swaps the
backend address, and requests a new Let's Encrypt certificate with the source certificate's e-mail (the domain must
already resolve to the edge). Talks to the NPM API with curl through the HomeLab SOCKS proxy (127.0.0.1:1081) unless NPM_API is set
to a directly reachable URL. The token and request bodies go to curl on stdin, never on its command line.
"""
import getpass
import json
import os
import sys
import subprocess

API = os.environ.get("NPM_API", "http://10.10.10.10:81/api")
PROXY = os.environ.get("NPM_SOCKS", "127.0.0.1:1081")


def call(method, path, token=None, body=None):
    """One NPM API call through curl (SOCKS proxy unless NPM_API is set); secrets go via stdin, not argv."""
    cfg = [f'url = "{API}{path}"', f'request = "{method}"', 'silent', 'show-error', 'max-time = 180',
           'header = "Content-Type: application/json"', 'write-out = "\\n%{http_code}"']
    if not os.environ.get("NPM_API"):
        cfg.append(f'proxy = "socks5h://{PROXY}"')
    if token:
        cfg.append(f'header = "Authorization: Bearer {token}"')
    if body is not None:
        cfg.append("data = " + json.dumps(json.dumps(body)))
    out = subprocess.run(["curl", "--config", "-"], input="\n".join(cfg), capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"{method} {path}: curl failed: {out.stderr.strip()[:300]}")
    payload, _, code = out.stdout.rpartition("\n")
    if not code.startswith("2"):
        sys.exit(f"{method} {path} -> {code}: {payload[:400]}")
    return json.loads(payload or "null")


def main(argv):
    if len(argv) < 4 or len(argv) % 4:
        sys.exit(__doc__)
    email = input("NPM e-mail: ").strip()
    secret = getpass.getpass("NPM password: ")
    token = call("POST", "/tokens", body={"identity": email, "secret": secret})["token"]
    del secret
    for i in range(0, len(argv), 4):
        src_id, domain, old_ip, new_ip = argv[i:i + 4]
        src = call("GET", f"/nginx/proxy-hosts/{src_id}?expand=certificate", token)
        existing = [h for h in call("GET", "/nginx/proxy-hosts", token) if domain in h["domain_names"]]
        if existing:
            print(f"{domain}: already exists as host {existing[0]['id']}, skipped")
            continue
        cert = src.get("certificate") or {}
        le_email = (cert.get("meta") or {}).get("letsencrypt_email") or email
        locations = []
        for loc in src.get("locations") or []:
            loc = {k: v for k, v in loc.items() if k in (
                "path", "forward_scheme", "forward_host", "forward_port", "advanced_config")}
            loc["forward_host"] = loc["forward_host"].replace(old_ip, new_ip)
            locations.append(loc)
        body = {
            "domain_names": [domain],
            "forward_scheme": src["forward_scheme"],
            "forward_host": src["forward_host"].replace(old_ip, new_ip),
            "forward_port": src["forward_port"],
            "access_list_id": src.get("access_list_id") or 0,
            "certificate_id": "new",
            "ssl_forced": True,
            "http2_support": bool(src.get("http2_support")),
            "hsts_enabled": bool(src.get("hsts_enabled")),
            "hsts_subdomains": bool(src.get("hsts_subdomains")),
            "block_exploits": bool(src.get("block_exploits")),
            "caching_enabled": bool(src.get("caching_enabled")),
            "allow_websocket_upgrade": bool(src.get("allow_websocket_upgrade")),
            "advanced_config": (src.get("advanced_config") or "").replace(old_ip, new_ip),
            "locations": locations,
            "meta": {"letsencrypt_email": le_email, "letsencrypt_agree": True, "dns_challenge": False},
        }
        created = call("POST", "/nginx/proxy-hosts", token, body)
        print(f"{domain}: created host {created['id']} -> {body['forward_scheme']}://{body['forward_host']}:"
              f"{body['forward_port']}, locations {[l['path'] for l in locations]}, certificate {created.get('certificate_id')}")


if __name__ == "__main__":
    main(sys.argv[1:])
