# mav-agent

Agentic control for ArduPilot / MAVLink vehicles: typed skills, MCP, LangGraph agent, and visual follow (Qwen-VL + CSRT).

## Flow (visual follow)

1. Qwen-VL generates an initial bbox from a text query
2. CSRT tracks it; a gain controller sends body-frame velocities

## Setup

```bash
pip install -e .
```

- Set `ALIBABA_API_KEY` for Qwen (remote) or run a local OpenAI-compatible Qwen server

## Example

```bash
python test_track.py --rtsp 'rtsp://127.0.0.1:8554/stream' --connection udp:0.0.0.0:14550 --query person
```

## Runtime modes

Default is **LangGraph agent TUI**. Pass **`--mcp`** for the HTTP MCP server only.

```bash
mav-cli --connection udp:0.0.0.0:14550 --image-source rtsp --rtsp 'rtsp://127.0.0.1:8554/stream'
```

### Gazebo camera (UDP port 5600, not RTSP)

ArduPilot Gazebo sends **RTP/H264 on UDP 5600**, not an RTSP URL:

```bash
mav-cli --connection udp:0.0.0.0:14550 --image-source udp --video-port 5600
```

Requires `gst-launch-1.0` and plugins (`gstreamer1.0-plugins-good`, `gstreamer1.0-libav`).

**Do not** run a separate `gst-launch udpsrc port=5600 ...` while mav-cli is using `--video-port 5600`.

### Backends (MAVLink vs ROS2)

Default is direct MAVLink:

```bash
mav-cli --backend mavlink --connection udp:0.0.0.0:14550 --image-source rtsp --rtsp 'rtsp://127.0.0.1:8554/stream'
```

When ArduPilot DDS is running:

```bash
source /opt/ros/humble/setup.bash
source ~/ngps_ws/install/setup.bash   # ardupilot_msgs
pip install -e ".[ros]"
mav-cli --backend ros2 --ros-image-topic /camera/image_raw
```

Skills are the same; `session.get_control()` uses pymavlink or ROS2 `/ap/*` topics.

### OpenAI agent (LangGraph)

Set `OPENAI_API_KEY` (model is `DEFAULT_OPENAI_MODEL` in code, currently `gpt-4o-mini`).

```bash
export OPENAI_API_KEY=sk-...
mav-cli --connection udp:0.0.0.0:14550 --image-source rtsp --rtsp 'rtsp://127.0.0.1:8554/stream'
```

Use `!command` for direct skills (e.g. `!status`).

### MCP server (Cursor, Claude Desktop, OpenClaw)

Run MCP only (no TUI / `--agent` in the same process):

```bash
mav-cli --mcp --connection udp:0.0.0.0:14550 --rtsp 'rtsp://127.0.0.1:8554/stream'
```

Defaults: `127.0.0.1:8765`. POST **`/mcp`**, GET **`/health`**. Override with `--mcp-host` / `--mcp-port`.

## Environment variables

Only API keys use env vars. Everything else is CLI flags or code defaults.

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required for agent TUI (LangGraph) |
| `ALIBABA_API_KEY` | Required when `--qwen-api remote` (Alibaba DashScope) |

## CLI defaults (no env)

| Flag | Default |
|------|---------|
| `--connection` | `udp:0.0.0.0:14550` |
| `--backend` | `mavlink` |
| `--image-source` | `udp` (default) or `rtsp` |
| `--video-port` | `5600` (default, udp video) |
| `--ros-image-topic` | `/camera/image_raw` (ros2 backend) |
| `--qwen-api` | `local` |
| `--qwen-base-url` | see `defaults.py` |
| `--mcp-host` / `--mcp-port` | `127.0.0.1` / `8765` |

## Notes

#### Humanly request :)
The **TUI** interface and **ruff** setup are fully developed by my AI coding agent, so bugs in those areas or errors in those may need a little extra care :)

Originally integrated for DimOS in [PR #1576](https://github.com/dimensionalOS/dimos/pull/1576). Renamed from `follow-anything` to **mav-agent** as scope expanded beyond visual follow.
