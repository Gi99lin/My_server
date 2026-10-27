#!/usr/bin/env bash
set -euo pipefail
# Public endpoint names/IPs only. Never resolve external names with Docker DNS.
python3 - "${1:-config.example.json}" "${2:-deploy/hosts}" "${3:-}" <<'PY'
import ipaddress,json,os,re,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit
config,output,mapping_file=sys.argv[1:]
cfg=json.loads(Path(config).read_text())
mapping=json.loads(Path(mapping_file).read_text()) if mapping_file else {}
mapping.setdefault('claude-sdk-host',os.getenv('NETGUARD_CLIENTS_IP','10.253.240.2'))
mapping.setdefault('sdk-egress',os.getenv('EGRESS_PROXY_IP','10.253.240.35'))
urls=[cfg['proxy_url']]+[u for a in cfg['applications'] for u in a.get('mcp_endpoints',[])]+[p['url'] for p in cfg.get('credential_providers',{}).values()]
required=set(cfg.get('proxy_bypass',[]))|{urlsplit(cfg['proxy_url']).hostname}
for url in urls:
 host=urlsplit(url).hostname
 if host in required:
  try:ipaddress.ip_address(host)
  except ValueError:
   if host not in mapping and host!='localhost':raise SystemExit('Missing explicit static mapping for internal hostname: '+host)
lines=['# Static internal peer mappings; external names are resolved by the parent proxy.','127.0.0.1 localhost','::1 localhost ip6-localhost ip6-loopback']
for host,address in sorted(mapping.items()):
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}',host):raise SystemExit('Invalid internal hostname mapping')
 ip=ipaddress.ip_address(address)
 if ip.version!=4 or ip.is_loopback or ip.is_unspecified or ip.is_multicast:raise SystemExit('Internal peers require explicit non-loopback IPv4 addresses')
 lines.append(f'{ip} {host}')
text='\n'.join(lines)+'\n'
if output:
 target=Path(output);target.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(dir=target.parent,prefix='.hosts-')
 with os.fdopen(fd,'w') as file:file.write(text)
 os.chmod(name,0o644);os.replace(name,target)
 print('Wrote static internal peer mappings to '+str(target))
else:print(text,end='')
PY
