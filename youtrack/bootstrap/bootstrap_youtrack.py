#!/usr/bin/env python3
"""
Bootstrap the "Mission Control" YouTrack preset.

Creates (idempotently — safe to re-run):
  * Projects:      WORK (Работа), LIFE (Жизнь), PROJ (Проекты)
  * State bundle:  Backlog / Next / In Progress / Waiting / Someday / Done / Dropped
  * Enum fields:   Sphere (сферы Компаса), Size, Energy
  * Date field:    Due
  * Tags:          agent, needle-mover, bot-test
  * Agile board:   "Mission Control" over all three projects
  * Seed issues:   from seed_tasks.json (exported from the Obsidian kanbans)

Usage:
  YT_URL=https://tracker.gigglin.tech YT_TOKEN=perm:... python3 bootstrap_youtrack.py
  (or put YT_URL / YT_TOKEN into ../.env)

Stdlib only — no pip dependencies.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# ── Preset definition ──────────────────────────────────────────────

PROJECTS = [
    {"shortName": "WORK", "name": "Работа"},
    {"shortName": "LIFE", "name": "Жизнь"},
    {"shortName": "PROJ", "name": "Проекты"},
]

STATE_BUNDLE = {
    "name": "Mission Control States",
    "values": [
        {"name": "Backlog",     "isResolved": False},
        {"name": "Next",        "isResolved": False},
        {"name": "In Progress", "isResolved": False},
        {"name": "Waiting",     "isResolved": False},
        {"name": "Someday",     "isResolved": False},
        {"name": "Done",        "isResolved": True},
        {"name": "Dropped",     "isResolved": True},
    ],
}

ENUM_FIELDS = {
    # field name -> bundle values
    "Sphere": ["🏗 Проекты", "💰 Финансы", "🧠 Здоровье", "❤️ Отношения", "💼 Карьера", "🔧 Быт"],
    "Size":   ["S (≤30 мин)", "M (≤2 ч)", "L (полдня+)", "XL (декомпозировать)"],
    "Energy": ["Deep", "Light", "Errand"],
}

DATE_FIELDS = ["Due"]

TAGS = ["agent", "needle-mover", "bot-test"]

BOARD_NAME = "Mission Control"

# ── Tiny REST client ───────────────────────────────────────────────

YT_URL = os.environ.get("YT_URL", "").rstrip("/")
YT_TOKEN = os.environ.get("YT_TOKEN", "")


def load_dotenv():
    """Fall back to ../.env for YT_URL / YT_TOKEN."""
    global YT_URL, YT_TOKEN
    path = os.path.join(HERE, "..", ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k == "YT_URL" and not YT_URL:
                YT_URL = v.strip().rstrip("/")
            if k == "YT_TOKEN" and not YT_TOKEN:
                YT_TOKEN = v.strip()


def api(method, path, body=None, fields=None):
    url = f"{YT_URL}/api/{path}"
    if fields:
        sep = "&" if "?" in url else "?"
        url += f"{sep}fields={urllib.parse.quote(fields)}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {YT_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        raise RuntimeError(f"{method} {url} -> {e.code}: {detail}") from None


def get(path, fields):
    return api("GET", path, fields=fields)


def post(path, body, fields="id,name"):
    return api("POST", path, body=body, fields=fields)


# ── Idempotent helpers ─────────────────────────────────────────────

def ensure_project(spec, me_id):
    existing = get("admin/projects", "id,shortName,name")
    for p in existing:
        if p["shortName"] == spec["shortName"]:
            print(f"  = project {spec['shortName']} exists")
            return p
    p = post("admin/projects", {
        "name": spec["name"],
        "shortName": spec["shortName"],
        "leader": {"id": me_id},
    }, fields="id,shortName,name")
    print(f"  + project {spec['shortName']} created")
    return p


def ensure_enum_bundle(name, values):
    for b in get("admin/customFieldSettings/bundles/enum", "id,name"):
        if b["name"] == name:
            print(f"  = enum bundle '{name}' exists")
            return b
    b = post("admin/customFieldSettings/bundles/enum",
             {"name": name, "values": [{"name": v} for v in values]})
    print(f"  + enum bundle '{name}' created")
    return b


def ensure_state_bundle():
    for b in get("admin/customFieldSettings/bundles/state", "id,name"):
        if b["name"] == STATE_BUNDLE["name"]:
            print(f"  = state bundle exists")
            return b
    b = post("admin/customFieldSettings/bundles/state", {
        "name": STATE_BUNDLE["name"],
        "values": [{"name": v["name"], "isResolved": v["isResolved"]}
                   for v in STATE_BUNDLE["values"]],
    })
    print(f"  + state bundle created")
    return b


def ensure_field_prototype(name, field_type):
    for f in get("admin/customFieldSettings/customFields", "id,name,fieldType(id)"):
        if f["name"] == name:
            print(f"  = field '{name}' exists")
            return f
    f = post("admin/customFieldSettings/customFields",
             {"name": name, "fieldType": {"id": field_type}})
    print(f"  + field '{name}' ({field_type}) created")
    return f


def attach_field(project, payload, label):
    attached = get(f"admin/projects/{project['id']}/customFields", "id,field(id,name)")
    if any(a["field"]["name"] == label for a in attached):
        print(f"    = {project['shortName']}: '{label}' attached")
        return
    post(f"admin/projects/{project['id']}/customFields", payload, fields="id")
    print(f"    + {project['shortName']}: '{label}' attached")


def ensure_tags():
    existing = {t["name"] for t in get("tags", "id,name")}
    for t in TAGS:
        if t in existing:
            print(f"  = tag '{t}' exists")
        else:
            post("tags", {"name": t})
            print(f"  + tag '{t}' created")


def ensure_board(projects, state_proto):
    for a in get("agiles", "id,name"):
        if a["name"] == BOARD_NAME:
            print(f"  = board '{BOARD_NAME}' exists")
            return
    try:
        post("agiles", {
            "name": BOARD_NAME,
            "projects": [{"id": p["id"]} for p in projects],
            "columnSettings": {"field": {"id": state_proto["id"]}},
        }, fields="id,name")
        print(f"  + board '{BOARD_NAME}' created (set swimlanes to 'Sphere' in board settings)")
    except RuntimeError as e:
        print(f"  ! board creation failed, create it manually in the UI: {e}")


def seed_issues(projects_by_short):
    path = os.path.join(HERE, "seed_tasks.json")
    if not os.path.exists(path):
        print("  (no seed_tasks.json — skipping import)")
        return
    tags_by_name = {t["name"]: t for t in get("tags", "id,name")}
    with open(path) as f:
        tasks = json.load(f)
    # Don't duplicate on re-run: match by summary within the project.
    existing = {(i["project"]["shortName"], i["summary"])
                for i in get("issues?query=" + urllib.parse.quote("created by: me"),
                             "summary,project(shortName)")}
    for t in tasks:
        key = (t["project"], t["summary"])
        if key in existing:
            print(f"  = [{t['project']}] {t['summary'][:50]}…")
            continue
        custom = [{"name": "State", "$type": "StateIssueCustomField",
                   "value": {"name": t.get("state", "Backlog")}}]
        if t.get("sphere"):
            custom.append({"name": "Sphere", "$type": "SingleEnumIssueCustomField",
                           "value": {"name": t["sphere"]}})
        issue = post("issues", {
            "project": {"id": projects_by_short[t["project"]]["id"]},
            "summary": t["summary"],
            "description": t.get("description", ""),
            "customFields": custom,
        }, fields="id,idReadable")
        for tag in t.get("tags", []):
            if tag in tags_by_name:
                post(f"issues/{issue['id']}/tags", {"id": tags_by_name[tag]["id"]}, fields="id")
        print(f"  + {issue['idReadable']}: {t['summary'][:60]}")


# ── Main ───────────────────────────────────────────────────────────

def main():
    load_dotenv()
    if not YT_URL or not YT_TOKEN:
        sys.exit("Set YT_URL and YT_TOKEN (env or youtrack/.env)")

    me = get("users/me", "id,login")
    print(f"Authenticated as {me['login']} at {YT_URL}\n")

    print("Projects:")
    projects = [ensure_project(p, me["id"]) for p in PROJECTS]
    projects_by_short = {p["shortName"]: p for p in projects}

    print("Bundles & fields:")
    state_bundle = ensure_state_bundle()
    state_proto = ensure_field_prototype("State", "state[1]")
    enum_protos = {}
    enum_bundles = {}
    for fname, values in ENUM_FIELDS.items():
        enum_bundles[fname] = ensure_enum_bundle(fname, values)
        enum_protos[fname] = ensure_field_prototype(fname, "enum[1]")
    date_protos = {n: ensure_field_prototype(n, "date") for n in DATE_FIELDS}

    print("Attaching fields to projects:")
    for p in projects:
        attach_field(p, {
            "$type": "StateProjectCustomField",
            "field": {"id": state_proto["id"]},
            "bundle": {"id": state_bundle["id"], "$type": "StateBundle"},
            "canBeEmpty": False,
        }, "State")
        for fname in ENUM_FIELDS:
            attach_field(p, {
                "$type": "EnumProjectCustomField",
                "field": {"id": enum_protos[fname]["id"]},
                "bundle": {"id": enum_bundles[fname]["id"], "$type": "EnumBundle"},
                "canBeEmpty": True,
                "emptyFieldText": "—",
            }, fname)
        for dname in DATE_FIELDS:
            attach_field(p, {
                "$type": "SimpleProjectCustomField",
                "field": {"id": date_protos[dname]["id"]},
                "canBeEmpty": True,
                "emptyFieldText": "—",
            }, dname)

    print("Tags:")
    ensure_tags()

    print("Agile board:")
    ensure_board(projects, state_proto)

    print("Seed issues:")
    seed_issues(projects_by_short)

    print("\nDone. Open the board and set swimlanes = Sphere, WIP limit 3 on 'In Progress'.")


if __name__ == "__main__":
    main()
