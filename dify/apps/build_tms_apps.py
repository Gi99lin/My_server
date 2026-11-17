"""Builds the TMS workflows in the Dify pilot (2026-11-11, step 2b of the Dify harness design).

Runs on gigglin-agents from /home/gigglin/.config/dify-pilot, reusing pilot_console.req for the console session.
Idempotent: an app that already exists by name is updated in place (re-imported), never duplicated.
Prints ids and statuses only. App API keys go to 0600 files; their values are never printed.
"""
import json
import os

import pilot_console as pc

MODEL = {
    "provider": "langgenius/openai_api_compatible/openai_api_compatible",
    "model": "cx/gpt-6.1-sol-medium",
    "model_type": "llm",
    "mode": "chat",
    "type": "model-selector",
    "completion_params": {"max_tokens": 4096},
}
MCP_PROVIDER = "tms-execution"  # server identifier: the persisted reference Dify resolves at run time


def ensure_login():
    status, _ = pc.req("/console/api/apps?page=1&limit=1")
    if status == 401:
        pc.initialize()


def start_node(variables):
    return {
        "id": "start",
        "type": "custom",
        "position": {"x": 80, "y": 280},
        "data": {"type": "start", "title": "Start", "variables": variables},
    }


def var(name, label, kind="paragraph", max_length=200000):
    return {"variable": name, "label": label, "type": kind, "required": True, "max_length": max_length, "options": []}


def end_node(source_node, source_var="text"):
    return {
        "id": "end",
        "type": "custom",
        "position": {"x": 880, "y": 280},
        "data": {
            "type": "end",
            "title": "End",
            "outputs": [{"variable": "text", "value_selector": [source_node, source_var], "value_type": "string"}],
        },
    }


def edge(src, dst):
    return {"id": f"{src}-{dst}", "source": src, "target": dst, "sourceHandle": "source", "targetHandle": "target",
            "type": "custom", "data": {"sourceType": src, "targetType": dst}}


def dsl(name, description, nodes, edges):
    return {
        "version": "0.7.0",
        "kind": "app",
        "app": {"name": name, "mode": "workflow", "icon": "🧪", "icon_type": "emoji", "icon_background": "#E0F2FE",
                "description": description, "use_icon_as_answer_icon": False},
        "dependencies": [],
        "workflow": {
            "environment_variables": [],
            "conversation_variables": [],
            "features": {},
            "graph": {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 1}},
        },
    }


def execution_tools():
    status, providers = pc.req("/console/api/workspaces/current/tool-providers?type=mcp")
    provider = next(p for p in providers if p.get("server_identifier") == MCP_PROVIDER)
    status, data = pc.req(f"/console/api/workspaces/current/tool-provider/mcp/tools/{provider['id']}")
    tools = data if isinstance(data, list) else data.get("tools", [])
    result = []
    for tool in tools:
        params = {}
        for p in tool.get("parameters", []):
            if p["name"] == "run_token":
                # Fixed to the workflow input: Dify fills it on every call and hides it from the model.
                params["run_token"] = {"auto": 0, "value": {"type": "variable", "value": ["start", "run_token"]}}
            else:
                params[p["name"]] = {"auto": 1, "value": None}
        result.append({
            "enabled": True,
            "type": "mcp",
            "provider_name": MCP_PROVIDER,
            "provider_show_name": provider.get("name"),
            "tool_name": tool["name"],
            "tool_label": tool["name"],
            "tool_description": (tool.get("description") or {}).get("en_US", ""),
            "settings": {},
            "parameters": params,
            "extra": {"description": ""},
        })
    return result


def execution_app():
    tools = execution_tools()
    agent = {
        "id": "agent",
        "type": "custom",
        "position": {"x": 480, "y": 280},
        "data": {
            "type": "agent",
            "title": "Agent",
            "agent_strategy_provider_name": "langgenius/agent/agent",
            "agent_strategy_name": "function_calling",
            "agent_strategy_label": "FunctionCalling",
            "tool_node_version": "2",
            "agent_parameters": {
                "model": {"type": "constant", "value": MODEL},
                "tools": {"type": "constant", "value": tools},
                "instruction": {"type": "mixed", "value": "{{#start.instruction#}}"},
                "query": {"type": "mixed", "value": "{{#start.task#}}"},
                "maximum_iterations": {"type": "constant", "value": 300},
            },
        },
    }
    nodes = [start_node([var("instruction", "Instruction"), var("task", "Task"),
                         var("run_token", "Run token", "text-input", 512)]), agent, end_node("agent")]
    return dsl("tms-execution", "TMS agent runs: the loop and the model only; every tool is the TMS's tms-execution-dify.",
               nodes, [edge("start", "agent"), edge("agent", "end")]), len(tools)


def authoring_app():
    llm = {
        "id": "llm",
        "type": "custom",
        "position": {"x": 480, "y": 280},
        "data": {
            "type": "llm",
            "title": "Author",
            "model": {k: MODEL[k] for k in ("provider", "mode", "completion_params")} | {"name": MODEL["model"]},
            "prompt_template": [
                {"role": "system", "text": "{{#start.instruction#}}"},
                {"role": "user", "text": "{{#start.task#}}"},
            ],
            "context": {"enabled": False, "variable_selector": []},
            "vision": {"enabled": False},
        },
    }
    nodes = [start_node([var("instruction", "Instruction"), var("task", "Task")]), llm, end_node("llm")]
    return dsl("tms-authoring", "TMS autotest authoring: one model call, no tools; the TMS checks and runs the source.",
               nodes, [edge("start", "llm"), edge("llm", "end")])


def import_app(doc):
    name = doc["app"]["name"]
    status, apps = pc.req("/console/api/apps?page=1&limit=100&name=" + name)
    existing = next((a for a in (apps or {}).get("data", []) if a["name"] == name), None)
    body = {"mode": "yaml-content", "yaml_content": json.dumps(doc, ensure_ascii=False)}
    if existing:
        body["app_id"] = existing["id"]
    status, result = pc.req("/console/api/apps/imports", body)
    if result.get("status") == "pending":
        status, result = pc.req(f"/console/api/apps/imports/{result['id']}/confirm", {})
    app_id = result.get("app_id")
    print(name, "import:", status, result.get("status"), app_id, result.get("error") or "")
    return app_id


def publish_and_key(app_id, name):
    status, result = pc.req(f"/console/api/apps/{app_id}/workflows/publish", {"marked_name": "2026-11-11", "marked_comment": "step 2b"})
    print(name, "publish:", status, (result or {}).get("result") or (result or {}).get("message"))
    path = f"/home/gigglin/.config/dify-pilot/{name}.app-key"
    if os.path.exists(path):
        print(name, "api key: kept existing file")
        return
    status, key = pc.req(f"/console/api/apps/{app_id}/api-keys", {})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(key["token"])
    print(name, "api key: written to", path)


if __name__ == "__main__":
    ensure_login()
    doc, count = execution_app()
    print("execution tools wired:", count)
    exec_id = import_app(doc)
    auth_id = import_app(authoring_app())
    for app_id, name in ((exec_id, "tms-execution"), (auth_id, "tms-authoring")):
        if app_id:
            publish_and_key(app_id, name)
    pc.save("tms-apps.json", {"tms-execution": exec_id, "tms-authoring": auth_id})
