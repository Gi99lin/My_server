"""Upload the signed TMS strategy package and upgrade the installed gigglin/tms_agent to it."""
import json, sys, time, uuid, urllib.request
sys.path.insert(0, "/home/gigglin/.config/dify-pilot")
import pilot_console as pc, build_tms_apps as b

path = sys.argv[1]
b.ensure_login()
st, lst = pc.req("/console/api/workspaces/current/plugin/list?page=1&page_size=50")
old = next(p["plugin_unique_identifier"] for p in lst["plugins"] if p["plugin_id"] == "gigglin/tms_agent")
pkg = open(path, "rb").read()
boundary = uuid.uuid4().hex
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"pkg\"; filename=\"tms-agent.difypkg\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n").encode() + pkg + f"\r\n--{boundary}--\r\n".encode()
headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
for c in pc.jar:
    if "csrf" in c.name:
        headers["X-CSRF-Token"] = c.value
r = urllib.request.Request(pc.BASE + "/console/api/workspaces/current/plugin/upload/pkg", data=body, headers=headers, method="POST")
with pc.opener.open(r, timeout=120) as resp:
    up = json.load(resp)
new = up["unique_identifier"]
print("old:", old, "\nnew:", new, "| verified:", (up.get("manifest") or {}).get("verified"))
st, d = pc.req("/console/api/workspaces/current/plugin/upgrade/pkg", {"original_plugin_unique_identifier": old, "new_plugin_unique_identifier": new})
print("upgrade:", st, json.dumps(d)[:200])
task = (d or {}).get("task_id")
for _ in range(30):
    if not task:
        break
    time.sleep(4)
    st, t = pc.req(f"/console/api/workspaces/current/plugin/tasks/{task}")
    status = ((t or {}).get("task") or {}).get("status")
    if status in ("success", "failed"):
        print("task:", status); break
st, lst = pc.req("/console/api/workspaces/current/plugin/list?page=1&page_size=50")
print("installed:", [(p["plugin_id"], p["version"]) for p in lst["plugins"]])
