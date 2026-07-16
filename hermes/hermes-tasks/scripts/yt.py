#!/usr/bin/env python3
"""
yt.py — thin YouTrack CLI for the hermes-tasks agent.

Env: YOUTRACK_URL (e.g. http://youtrack:8080), YOUTRACK_TOKEN (perm:...)

Commands:
  yt.py create --project PROJ --summary "..." [--description "..."]
               [--state Next] [--sphere "🏗 Проекты"] [--size "M (≤2 ч)"]
               [--energy Light] [--due 2026-07-20] [--tags agent,bot-test]
               [--parent PROJ-12]
  yt.py list   [--query "#Unresolved"] [--limit 50]
  yt.py get    PROJ-12
  yt.py cmd    PROJ-12 "State Next Due 2026-07-20"   # raw YouTrack command
  yt.py comment PROJ-12 --text "..."

All field changes go through YouTrack's command API, so anything you can type
in the UI command dialog works here (e.g. "State Done", "tag agent",
"Sphere {🧠 Здоровье}", "subtask of PROJ-3").
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

URL = os.environ.get("YOUTRACK_URL", "").rstrip("/")
TOKEN = os.environ.get("YOUTRACK_TOKEN", "")

ISSUE_FIELDS = ("idReadable,summary,description,resolved,"
                "project(shortName),tags(name),"
                "customFields(name,value(name))")


def api(method, path, body=None):
    req = urllib.request.Request(f"{URL}/api/{path}", method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}",
                                          "Content-Type": "application/json",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode() or "null")


def command(issue_id, query, comment=None):
    body = {"query": query, "issues": [{"idReadable": issue_id}]}
    if comment:
        body["comment"] = comment
    api("POST", "commands", body)


def fmt(issue):
    cf = {f["name"]: (f.get("value") or {}).get("name") if isinstance(f.get("value"), dict) else None
          for f in issue.get("customFields", [])}
    tags = ",".join(t["name"] for t in issue.get("tags", []))
    parts = [issue["idReadable"], f"[{cf.get('State', '?')}]", issue["summary"]]
    extra = " ".join(x for x in [cf.get("Sphere"), cf.get("Size"), cf.get("Energy"),
                                 f"due:{cf.get('Due')}" if cf.get("Due") else None,
                                 f"#{tags}" if tags else None] if x)
    return " ".join(parts) + (f"  ({extra})" if extra else "")


def build_command_query(a):
    parts = []
    if getattr(a, "state", None):
        parts.append(f"State {{{a.state}}}")
    if getattr(a, "sphere", None):
        parts.append(f"Sphere {{{a.sphere}}}")
    if getattr(a, "size", None):
        parts.append(f"Size {{{a.size}}}")
    if getattr(a, "energy", None):
        parts.append(f"Energy {{{a.energy}}}")
    if getattr(a, "due", None):
        parts.append(f"Due {a.due}")
    if getattr(a, "tags", None):
        parts += [f"tag {t.strip()}" for t in a.tags.split(",") if t.strip()]
    if getattr(a, "parent", None):
        parts.append(f"subtask of {a.parent}")
    return " ".join(parts)


def main():
    if not URL or not TOKEN:
        sys.exit("YOUTRACK_URL / YOUTRACK_TOKEN are not set")

    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="op", required=True)

    c = sub.add_parser("create")
    c.add_argument("--project", required=True)
    c.add_argument("--summary", required=True)
    c.add_argument("--description", default="")
    for opt in ("--state", "--sphere", "--size", "--energy", "--due", "--tags", "--parent"):
        c.add_argument(opt)

    l = sub.add_parser("list")
    l.add_argument("--query", default="#Unresolved sort by: {issue id}")
    l.add_argument("--limit", type=int, default=50)

    g = sub.add_parser("get")
    g.add_argument("issue")

    r = sub.add_parser("cmd")
    r.add_argument("issue")
    r.add_argument("query")

    m = sub.add_parser("comment")
    m.add_argument("issue")
    m.add_argument("--text", required=True)

    a = p.parse_args()

    if a.op == "create":
        issue = api("POST", f"issues?fields=idReadable,id",
                    {"project": {"shortName": a.project},
                     "summary": a.summary, "description": a.description})
        q = build_command_query(a)
        if q:
            command(issue["idReadable"], q)
        print(issue["idReadable"])

    elif a.op == "list":
        q = urllib.parse.quote(a.query)
        issues = api("GET", f"issues?query={q}&$top={a.limit}&fields={ISSUE_FIELDS}")
        for i in issues:
            print(fmt(i))
        if not issues:
            print("(empty)")

    elif a.op == "get":
        i = api("GET", f"issues/{a.issue}?fields={ISSUE_FIELDS}")
        print(fmt(i))
        if i.get("description"):
            print("---\n" + i["description"])

    elif a.op == "cmd":
        command(a.issue, a.query)
        print("ok")

    elif a.op == "comment":
        command(a.issue, "comment", comment=a.text)
        print("ok")


if __name__ == "__main__":
    main()
