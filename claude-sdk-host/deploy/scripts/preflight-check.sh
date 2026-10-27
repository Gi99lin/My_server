#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."
command -v docker >/dev/null
command -v python3 >/dev/null
# Compose validates required paths/variables; only its network projection is printed.
# Never print the complete operator configuration or a proxy credential URL.
docker compose config --format json | python3 -c '
import ipaddress,json,subprocess,sys
cfg=json.load(sys.stdin)
planned={v.get("name",k):[ipaddress.ip_network(p["subnet"]) for p in v.get("ipam",{}).get("config",[]) if "subnet" in p] for k,v in cfg["networks"].items()}
ids=subprocess.check_output(["docker","network","ls","-q"],text=True).split()
existing=json.loads(subprocess.check_output(["docker","network","inspect",*ids],text=True)) if ids else []
conflicts=[]
for item in existing:
 for record in item.get("IPAM",{}).get("Config",[]) or []:
  if not record.get("Subnet"):continue
  current=ipaddress.ip_network(record["Subnet"])
  for name,ranges in planned.items():
   for network in ranges:
    if network.version==current.version and network.overlaps(current):
     if item["Name"]!=name or current!=network:conflicts.append(f"Docker {item["Name"]}: {current} overlaps {name}: {network}")
# Linux host routes are meaningful for deployment. Ignore the default route.
try:
 routes=json.loads(subprocess.check_output(["ip","-j","route","show"],text=True))
except (OSError,subprocess.CalledProcessError):
 routes=[]
 print("Host route overlap check unavailable; inspect deployment host routes before go-live.")
for route in routes:
 dst=route.get("dst", "default")
 if dst=="default" or route.get("protocol")=="kernel" and route.get("dev", "").startswith(("br-","docker")):continue
 try:current=ipaddress.ip_network(dst,strict=False)
 except ValueError:continue
 for name,ranges in planned.items():
  for network in ranges:
   if network.version==current.version and network.overlaps(current):conflicts.append(f"Host route {current} overlaps {name}: {network}")
if conflicts:
 print("\n".join(conflicts),file=sys.stderr);sys.exit(1)
print("PASS Compose and subnet overlap check; live authentication and upstream exit remain separate gates.")
'
