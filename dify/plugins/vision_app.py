"""Re-import tms-execution-next with a chosen agent strategy (E4): python3 vision_app.py vision|stock [MAXITER]

vision = gigglin/tms_agent function_calling_vision (tool images reach the model); stock = langgenius/agent function_calling.
The model stays DeepSeek flash with max_tokens 16000; every tms-execution-next tool is wired; the app's API key is kept.
"""
import sys
import build_tms_apps as b, pilot_console as pc

STRATEGIES = {
    "vision": ("gigglin/tms_agent/tms_agent", "function_calling_vision", "FunctionCalling (vision)"),
    "stock": ("langgenius/agent/agent", "function_calling", "FunctionCalling"),
}
which = sys.argv[1]
maxiter = int(sys.argv[2]) if len(sys.argv) > 2 else 150
provider, name, label = STRATEGIES[which]
b.ensure_login()
status, providers = pc.req("/console/api/workspaces/current/tool-providers?type=mcp")
prov = next(p for p in providers if p.get("server_identifier") == "tms-execution-next")
status, _ = pc.req("/console/api/workspaces/current/tool-provider/mcp/update/" + prov["id"])
print("tools refresh:", status)
b.MODEL = dict(b.MODEL, model="opencode-go/deepseek-v4.1-flash", completion_params={"max_tokens": 16000})
b.MCP_PROVIDER = "tms-execution-next"
doc, count = b.execution_app()
agent = next(n for n in doc["workflow"]["graph"]["nodes"] if n["id"] == "agent")
agent["data"].update(agent_strategy_provider_name=provider, agent_strategy_name=name, agent_strategy_label=label)
params = agent["data"]["agent_parameters"]
params["tools"]["value"] = [t for t in params["tools"]["value"] if t["tool_name"] != "next_point"]
params["maximum_iterations"]["value"] = maxiter
print("strategy", provider, name, "| maxiter", maxiter, "| tools", len(params["tools"]["value"]))
doc["app"]["name"] = "tms-execution-next"
doc["app"]["description"] = f"TMS next: agent runs and stand checks ({which} strategy, E4 2026-11-24)."
app_id = b.import_app(doc)
if app_id:
    b.publish_and_key(app_id, "tms-execution-next")
