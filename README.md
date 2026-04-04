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

## Notes

This module is originally integrated for DimOS in [PR #1576](https://github.com/dimensionalOS/dimos/pull/1576). It is provided here as a separate package to enable native and easy support for ardupilot/mavlink vehicles. For full context, refer to that PR.


