"""Replace the installed gigglin/tms_agent with a signed package: upload, uninstall the old version, install the new.

This Dify version has no upgrade from a local package. Usage: python3 reinstall_plugin.py PATH.signed.difypkg
"""
import json, sys, time, uuid, urllib.request
sys.path.insert(0, "/home/gigglin/.config/dify-pilot")
import pilot_console as pc, build_tms_apps as b

b.ensure_login()
pkg = open(sys.argv[1], "rb").read()
boundary = uuid.uuid4().hex
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"pkg\"; filename=\"tms-agent.difypkg\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n").encode() + pkg + f"\r\n--{boundary}--\r\n".encode()
headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
for c in pc.jar:
    if "csrf" in c.name:
        headers["X-CSRF-Token"] = c.value
request = urllib.request.Request(pc.BASE + "/console/api/workspaces/current/plugin/upload/pkg", data=body, headers=headers, method="POST")
with pc.opener.open(request, timeout=120) as reply:
    uploaded = json.load(reply)
new = uploaded["unique_identifier"]
print("uploaded", new, "| verified", (uploaded.get("manifest") or {}).get("verified"))
status, listing = pc.req("/console/api/workspaces/current/plugin/list?page=1&page_size=50")
old = next((p for p in listing["plugins"] if p["plugin_id"] == "gigglin/tms_agent"), None)
if old is not None:
    status, _ = pc.req("/console/api/workspaces/current/plugin/uninstall", {"plugin_installation_id": old["installation_id"]})
    print("uninstalled", old["version"], status)
status, started = pc.req("/console/api/workspaces/current/plugin/install/pkg", {"plugin_unique_identifiers": [new]})
task_id = started.get("task_id")
for _ in range(30):
    if not task_id:
        break
    time.sleep(4)
    status, task = pc.req(f"/console/api/workspaces/current/plugin/tasks/{task_id}")
    state = ((task or {}).get("task") or {}).get("status")
    if state in ("success", "failed"):
        print("install", state)
        break
status, listing = pc.req("/console/api/workspaces/current/plugin/list?page=1&page_size=50")
print("installed:", [(p["plugin_id"], p["version"]) for p in listing["plugins"]])
