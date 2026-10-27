#!/usr/bin/env bash
set -euo pipefail
# Explicit operator-triggered network check. No model query or auth-header logging.
CONTAINER="${CONTAINER:-claude-sdk-host}"
PROBE_URL="${PROBE_URL:-https://api.ipify.org}"
EXPECTED_EXIT_IP="${EXPECTED_EXIT_IP:-}"
docker exec -i -e "PROBE_URL=$PROBE_URL" -e "EXPECTED_EXIT_IP=$EXPECTED_EXIT_IP" "$CONTAINER" python - <<'PY'
import ipaddress,json,os,socket,sys,urllib.request
from pathlib import Path
from urllib.parse import urlsplit

def fail(code):
    print('FAIL '+code,file=sys.stderr)
    raise SystemExit(1)

config=json.loads(Path('/run/secrets/host-config.json').read_text())
probe=os.environ['PROBE_URL'];parts=urlsplit(probe)
if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:
    fail('invalid_probe_url')
try:
    proxy=urllib.request.ProxyHandler({'http':config['proxy_url'],'https':config['proxy_url']})
    with urllib.request.build_opener(proxy).open(probe,timeout=10) as response:
        observed=str(ipaddress.ip_address(response.read(1024).decode().strip()))
except Exception:
    fail('configured_proxy_exit_unavailable')
expected=os.environ.get('EXPECTED_EXIT_IP')
if expected:
    try: expected=str(ipaddress.ip_address(expected))
    except ValueError:fail('invalid_expected_exit_ip')
    if observed!=expected:fail('unexpected_proxy_exit')
print('PASS configured proxy exit: '+observed+(' (matches expected)' if expected else ' (not compared to an expected address)'))

def deny_tcp(host,port,family=socket.AF_INET):
    with socket.socket(family,socket.SOCK_STREAM) as stream:
        stream.settimeout(1)
        try:stream.connect((host,port))
        except OSError:return
    fail('direct_tcp_reachable')

for host,port in [('1.1.1.1',443),('169.254.169.254',80),('127.0.0.11',53),('8.8.8.8',53),('8.8.8.8',853)]:deny_tcp(host,port)
deny_tcp('2606:4700:4700::1111',443,socket.AF_INET6)
print('PASS direct IPv4/IPv6, metadata, TCP DNS and DoT denied')
query=b'\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03org\x00\x00\x01\x00\x01'
for host in ('127.0.0.11','8.8.8.8'):
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as stream:
        stream.settimeout(1)
        try:
            stream.sendto(query,(host,53));stream.recvfrom(1024)
        except OSError:continue
    fail('direct_udp_dns_answered')
print('PASS Docker and external UDP DNS denied')
print('PASS network probes; also verify parent outage, guard restart and actual browser routing before go-live')
PY
