# follow-anything

Visual tracking and following for mavlink supported vehicles (tested on ardupilot).

## Flow
1. Qwen-VL generated an initial bbox from a text query
2. CSRT tracks it and using a simple gain controller, send body-frame velocities.

## Setup

```bash
pip install -e .
```

- Set `ALIBABA_API_KEY` for Qwen

## Example

```bash
python test_track.py --rtsp 'rtsp://127.0.0.1:8554/stream' --connection udp:0.0.0.0:14550 --query person
```

## Interactive CLI (skills)

After `pip install -e .`, run the Textual TUI:

```bash
mav-cli --connection udp:0.0.0.0:14550 --rtsp 'rtsp://127.0.0.1:8554/stream'
# or
python -m follow_anything.cli
```

Type `help` for commands (`connect`, `rtsp`, `follow`, `stop`, `status`). See [AGENTS.md](AGENTS.md).

### OpenAI agent (LangGraph)

Set `OPENAI_API_KEY`. Optional: `FOLLOW_ANYTHING_OPENAI_MODEL` (default `gpt-4o-mini`).

```bash
export OPENAI_API_KEY=sk-...
mav-cli --agent --connection udp:0.0.0.0:14550 --rtsp 'rtsp://127.0.0.1:8554/stream'
```

Describe goals in natural language; the model uses `create_react_agent` with checkpointed thread state and selects skills. Use `!command` for direct skills (e.g. `!status`).

### MCP server (external agents: OpenClaw, Claude, Cursor)

Do **not** use `--agent` or the TUI together with MCP in one process. Run MCP only:

```bash
mav-cli --mcp --connection udp:0.0.0.0:14550 --rtsp 'rtsp://127.0.0.1:8554/stream'
```

Defaults: bind `127.0.0.1`, port **8765**. JSON-RPC POST **`/mcp`** (methods `initialize`, `tools/list`, `tools/call`). **`GET /health`** for a quick check.

Override with **`--mcp-host`**, **`--mcp-port`**, or env **`FOLLOW_ANYTHING_MCP_HOST`** / **`FOLLOW_ANYTHING_MCP_PORT`**.

Point your MCP client at `http://127.0.0.1:8765/mcp`.

## To-DO
- [ ] Add depth estimatiion and PCL handling to extract and estimate distance to the tracked objects
- [ ] Add spatio-temporal memory module

## Notes

This module is originally integrated for DimOS in [PR #1576](https://github.com/dimensionalOS/dimos/pull/1576). It is provided here as a separate package to enable native and easy support for ardupilot/mavlink vehicles. For full context, refer to that PR.


