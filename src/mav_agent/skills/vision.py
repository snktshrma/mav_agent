from __future__ import annotations

from mav_agent.qwen_bbox import describe_frame_with_qwen
from mav_agent.session import DroneSession
from mav_agent.skills.helpers import query_from_args
from mav_agent.skills.registry import register_skill


def _rtsp(session: DroneSession, args: dict[str, str]) -> str:
    url = (args.get("url") or args.get("_positional") or "").strip()
    if not url:
        return "Usage: rtsp url=<rtsp_url>"
    return session.start_rtsp(url)


def _describe(session: DroneSession, args: dict[str, str]) -> str:
    prompt = (args.get("prompt") or args.get("q") or args.get("_positional") or "").strip()
    if not prompt:
        prompt = None
    frame = session.capture_frame(timeout=12.0)
    if frame is None:
        return (
            "No video frame available. Use --video-port 5600 (do not run a separate gst-launch "
            "on the same port), ensure Gazebo/SITL camera is streaming, wait a few seconds, retry."
        )
    try:
        vision = session.vision_config
        text = describe_frame_with_qwen(
            frame,
            prompt,
            api_key=vision.api_key,
            model_name=vision.model,
            base_url=vision.base_url,
            qwen_api=vision.qwen_api,
        )
    except Exception as e:
        return f"Vision inference failed: {e}"
    if not text:
        return "Vision model returned an empty response."
    return text


def _follow(session: DroneSession, args: dict[str, str]) -> str:
    query = query_from_args(args, "person")
    duration_s = args.get("duration", "0")
    try:
        duration = float(duration_s)
    except ValueError:
        return "Invalid duration (expected a number)."
    return session.get_tracker().track(query=query, duration=duration)


def register_vision_skills() -> None:
    register_skill(
        "rtsp",
        "Start RTSP video stream before follow or tracking",
        _rtsp,
        for_openai={"url": "RTSP URL (e.g. rtsp://host:8554/stream)"},
    )
    register_skill(
        "describe",
        "Capture one camera frame and describe the scene with Qwen-VL (what the drone sees)",
        _describe,
        for_openai={
            "prompt": "Optional question about the image (default: general scene description)",
        },
    )
    register_skill(
        "follow",
        "Start visual follow: Qwen bbox + CSRT + velocity commands",
        _follow,
        for_openai={
            "query": "What to detect and track (e.g. person, car)",
            "duration": "Seconds to run; 0 means until stop",
        },
    )
    register_skill(
        "stop",
        "Stop visual tracking",
        lambda session, args: session.get_tracker().stop(),
    )
