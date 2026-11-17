"""Operator regression for the complete published Agent API cancellation path.

Run on gigglin-agents. Credentials are read from server-only files, never
printed. Only a disposable pilot conversation and uniquely named files are used.
"""

import json
import os
import shlex
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path


PRIVATE = Path(os.environ.get("DIFY_PILOT_PRIVATE_DIR", "/home/gigglin/.config/dify-pilot"))
BASE = "http://127.0.0.1:18080/v1"
BACKEND = "dify-pilot-agent_backend-1"
API = "dify-pilot-api-1"
SANDBOX = "dify-pilot-local_sandbox-1"


def save(name, value):
    fd = os.open(PRIVATE / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle)


def container_json(container, program):
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-"],
        input=program, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def run_records(run_id=None):
    return container_json(BACKEND, f"""
import asyncio,json
from redis.asyncio import Redis
from dify_agent.server.settings import ServerSettings
async def main():
 s=ServerSettings(); r=Redis.from_url(s.redis_url); result=[]
 async for key in r.scan_iter(match=s.redis_prefix+':runs:*:record'):
  raw=await r.get(key)
  if not raw:continue
  d=json.loads(raw)
  if {run_id!r} is not None and d.get('run_id')!={run_id!r}:continue
  item={{k:d.get(k) for k in ('run_id','status','created_at','updated_at')}}
  if {run_id!r} is not None:
   for _,fields in await r.xrange(s.redis_prefix+':runs:'+d['run_id']+':events'):
    event=json.loads(fields[b'payload'])
    if event.get('type')=='run_cancelled':item['cleanup_completed_at']=event['created_at']
  result.append(item)
 await r.aclose(); print(json.dumps(result))
asyncio.run(main())
""")


def heartbeat_observation(run_id):
    return container_json(API, f"""
import os,time,json,httpx2
base=os.environ.get('AGENT_BACKEND_BASE_URL','http://agent_backend:5050')
token=os.environ.get('AGENT_BACKEND_API_TOKEN') or os.environ['DIFY_AGENT_API_TOKEN']
times=[]; pending=''
with httpx2.Client(timeout=3,headers={{'Authorization':'Bearer '+token}}) as c:
 with c.stream('GET',base+'/runs/'+{run_id!r}+'/events/sse',params={{'after':'0-0'}}) as response:
  response.raise_for_status()
  for text in response.iter_text():
   pending+=text
   while '\\n' in pending:
    line,pending=pending.split('\\n',1)
    if line.strip()==': keepalive':times.append(time.monotonic())
   if len(times)>=3:break
print(json.dumps({{'comments':len(times),'interval_seconds':[round(b-a,3) for a,b in zip(times,times[1:])]}}))
""")


def workspace_file(name):
    return subprocess.check_output([
        "docker", "exec", SANDBOX, "find", "/workspace", "-maxdepth", "6",
        "-name", name, "-type", "f", "-print",
    ], text=True).strip()


def epoch(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def main():
    assert not [r for r in run_records() if r["status"] == "running"], "Pilot has active runs"
    token = json.loads((PRIVATE / "agent-api-key.json").read_text())["token"]
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
    nonce = uuid.uuid4().hex[:12]
    ready, marker = f"cancel-proof-{nonce}-ready.txt", f"cancel-proof-{nonce}-late.txt"
    child = (
        f"import time; from pathlib import Path; Path({ready!r}).write_text('READY'); "
        f"time.sleep(12); Path({marker!r}).write_text('UNEXPECTED')"
    )
    program = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
    )
    script = "python3 -c " + shlex.quote(program)
    query = (
        "Call shell_run with timeout exactly 25 seconds. Run exactly this command:\n```sh\n"
        + script + "\n```\nDo not run other commands or access the network."
    )
    user = "cancel-proof-" + nonce
    request = urllib.request.Request(BASE + "/chat-messages", data=json.dumps({
        "inputs": {}, "query": query, "response_mode": "streaming", "user": user,
    }).encode(), headers=headers)
    events, result, task_id = [], {}, None

    def stop():
        stop_request = urllib.request.Request(
            BASE + "/chat-messages/" + task_id + "/stop",
            data=json.dumps({"user": user}).encode(), headers=headers,
        )
        result["stop_request_epoch"] = time.time()
        with urllib.request.urlopen(stop_request, timeout=30) as response:
            result.update(stop_status=response.status, stop_result=json.load(response))

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            for line in response:
                if not line.startswith(b"data:"):
                    continue
                event = json.loads(line[5:].strip())
                events.append(event)
                task_id = event.get("task_id") or task_id
                if not result.get("stop_status") and event.get("event") == "agent_thought" and "shell_run" in str(event.get("tool", "")):
                    deadline = time.monotonic() + 5
                    while not workspace_file(ready) and time.monotonic() < deadline:
                        time.sleep(0.05)
                    assert workspace_file(ready), "Command did not independently confirm startup"
                    args = event.get("tool_input", {})
                    args = json.loads(args) if isinstance(args, str) else args
                    assert args.get("timeout") == 25
                    assert "subprocess.Popen" in args.get("script", "")
                    active = [r for r in run_records() if r["status"] == "running"]
                    assert len(active) == 1, "Cannot safely attribute the backend run"
                    result["backend_run_id"] = active[0]["run_id"]
                    result["heartbeat"] = heartbeat_observation(active[0]["run_id"])
                    assert result["heartbeat"]["comments"] >= 3
                    assert all(0.1 < n < 2 for n in result["heartbeat"]["interval_seconds"])
                    result["command_started_before_stop"] = True
                    result["descendant_ready_before_stop"] = True
                    stop()
                    print("stop_ack", json.dumps(result), flush=True)
                if event.get("event") in ("message_end", "error"):
                    break
        save("cancel-fix-published-events.json", events)
        assert result.get("stop_status") == 200
        time.sleep(13)
        result["delayed_side_effect_absent"] = not workspace_file(marker)
        records = run_records(result["backend_run_id"])
        assert len(records) == 1
        result["backend"] = records[0]
        logs = subprocess.run(
            ["docker", "logs", "--timestamps", BACKEND], capture_output=True, text=True, check=True,
        )
        cancel_path = "/runs/" + result["backend_run_id"] + "/cancel"
        receipts = [l.split()[0] for l in (logs.stdout + logs.stderr).splitlines() if cancel_path in l and '"POST ' in l]
        result["backend_cancel_receipts"] = receipts
        assert receipts, "Backend cancellation receipt was not observed"
        result["receipt_after_stop_seconds"] = round(epoch(receipts[-1]) - result["stop_request_epoch"], 3)
        assert result["backend"]["status"] == "cancelled"
        result["cleanup_after_stop_seconds"] = round(epoch(result["backend"]["cleanup_completed_at"]) - result["stop_request_epoch"], 3)
        assert 0 <= result["receipt_after_stop_seconds"] < 2
        assert 0 <= result["cleanup_after_stop_seconds"] < 5
        assert result["delayed_side_effect_absent"], "Canceled command still performed its delayed write"
        result["passed"] = True
    except Exception as error:
        result["passed"] = False
        result["error_type"] = type(error).__name__
        if task_id and not result.get("stop_status"):
            stop()
        raise
    finally:
        save("cancel-fix-published-result.json", result)
        print("published_api_result", json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
