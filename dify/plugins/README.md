# Dify plugins of our own

## `tms-agent` — function calling that passes tool images to the model

Built on 2026-11-24 for the TMS decisions review (D1, D2; `ai-testcase-generator/docs/plans/2026-11-24-decisions-review.md`).
It is `langgenius/agent 0.0.51` with the ReAct strategy removed and five changes made by `patch_strategy.py`:

1. A tool's image blob (Dify turns an MCP `ImageContent` into one) is no longer replaced by «Generated file ...».
2. After all of a round's tool answers, one user message carries that round's images at high detail.
3. A vision model keeps every image in the history; only a model without vision gets the «[image]» placeholder.
4. The plugin is `gigglin/tms_agent`, version 0.1.0, strategy `function_calling_vision`.

### Rebuild

On gigglin-agents, from a fresh copy of the stock package (`docker cp` it out of the plugin daemon's
`/app/storage/plugin_packages/langgenius/`), with the daemon's own CLI (`docker cp dify-pilot-plugin_daemon-1:/app/commandline ./dify`):

```bash
cd ~/dify-plugins/tms-agent && python3 /path/to/patch_strategy.py
cd .. && ./dify plugin package ./tms-agent -o tms-agent-0.1.0.difypkg
./dify signature sign tms-agent-0.1.0.difypkg -p ~/.config/dify-pilot/signing/tms_plugins.private.pem
```

Install the `.signed.difypkg` through «Плагины → Установить из локального пакета» or the console API.

### Signing

Dify's own check stays on (`FORCE_VERIFYING_SIGNATURE=true`). `compose.pilot.yml` adds our public key as a third-party
key; the key file is `volumes/plugin_daemon/keys/tms_plugins.public.pem`. The private key is only on gigglin-agents in
`~/.config/dify-pilot/signing/` (mode 600) and never goes into Git.

### Switching the TMS app

`vision_app.py vision|stock [MAXITER]` re-imports `tms-execution-next` with this strategy or the stock one, keeping its
API key. As of 2026-11-24 it runs `vision` with 150 iterations. The Dify model `opencode-go/deepseek-v4.1-flash` has
`vision_support = support` and `context_size = 500000`, and OmniRoute marks it «Vision capable».
