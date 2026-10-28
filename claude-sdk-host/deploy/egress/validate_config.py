"""Validate the deliberately narrow GOST v2 parent/group configuration without logging its values."""

import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def parent(address):
    host, separator, port = address.partition(":")
    ip = ipaddress.IPv4Address(host)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        raise ValueError
    if not separator or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError
    return str(ip), int(port)


def validate(path):
    config = json.loads(Path(path).read_text())
    if set(config) != {"Debug", "Retries", "ServeNodes", "ChainNodes"} or config["Debug"] is not False:
        raise ValueError
    retries = config["Retries"]
    if type(retries) is not int or not 1 <= retries <= 3 or config["ServeNodes"] != ["http://:8080"]:
        raise ValueError
    if not isinstance(config["ChainNodes"], list) or len(config["ChainNodes"]) != 1:
        raise ValueError
    node = urlsplit(config["ChainNodes"][0])
    if node.scheme not in {"http", "https", "socks5"} or node.path or node.fragment or not node.hostname:
        raise ValueError
    base = parent(f"{node.hostname}:{node.port}")
    if (node.username is None) != (node.password is None):
        raise ValueError
    options = parse_qs(node.query, keep_blank_values=True, strict_parsing=True) if node.query else {}
    if options:
        if set(options) != {"ip", "strategy", "max_fails", "fail_timeout"} or any(
            len(v) != 1 for v in options.values()
        ):
            raise ValueError
        if options["strategy"] != ["fifo"] or options["max_fails"] != ["1"] or options["fail_timeout"] != ["30s"]:
            raise ValueError
        peers = [parent(item) for item in options["ip"][0].split(",")]
        if len(peers) != 2 or len(set(peers)) != 2 or peers[0] != base or retries < 2:
            raise ValueError
    else:
        peers = [base]
    allowed_ips = {str(ipaddress.IPv4Address(x.strip())) for x in os.environ["UPSTREAM_IPS"].split(",")}
    allowed_ports = {int(x.strip()) for x in os.environ["UPSTREAM_PORTS"].split(",")}
    if {p[0] for p in peers} != allowed_ips or {p[1] for p in peers} != allowed_ports:
        raise ValueError
    chains = []
    references = []
    for index, (host, port) in enumerate(peers):
        name = f"parent-{index + 1}"
        connector = {"type": "socks5" if node.scheme == "socks5" else "http"}
        if node.username is not None:
            connector["auth"] = {"username": unquote(node.username), "password": unquote(node.password)}
        dialer = {"type": "tls" if node.scheme == "https" else "tcp"}
        chains.append(
            {
                "name": name,
                "hops": [
                    {
                        "name": name,
                        "nodes": [{"name": name, "addr": f"{host}:{port}", "connector": connector, "dialer": dialer}],
                    }
                ],
            }
        )
        reference = {"chain": name}
        if len(peers) == 2:
            reference["probe"] = {"type": "tcp", "addr": "api.anthropic.com:443", "interval": "5s", "timeout": "3s"}
        references.append(reference)
    runtime = {
        "log": {"level": "fatal", "output": "stderr"},
        "services": [
            {
                "name": "private-sdk-egress",
                "addr": ":8080",
                "listener": {"type": "tcp"},
                "handler": {
                    "type": "http",
                    "retries": retries,
                    "metadata": {"httpTunnel": True},
                    "chainGroup": {
                        "chains": references,
                        "selector": {"strategy": "fifo", "maxFails": 1, "failTimeout": "30s"},
                    },
                },
            }
        ],
        "chains": chains,
    }
    return len(peers), runtime


if __name__ == "__main__":
    try:
        count, runtime = validate(sys.argv[1])
        if len(sys.argv) == 3:
            fd = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as output:
                json.dump(runtime, output)
    except Exception:
        raise SystemExit("invalid_parent_proxy_configuration") from None
    print(f"parent_proxy_configuration_valid peers={count}")
