import base64
import json
import os

import cv2
from openai import OpenAI

from mav_agent.defaults import (
    ALIBABA_BASE_URL,
    ALIBABA_QWEN_MODEL,
    DEFAULT_QWEN_MODEL,
    QWEN_API,
    QWEN_DEFAULT_API_KEY,
    QWEN_DEFAULT_BASE_URL,
)


def _rgb_to_jpeg_b64(frame):
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    _, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

    return base64.b64encode(buf.tobytes()).decode("ascii")


def _qwen_vision_chat(
    frame,
    prompt: str,
    *,
    api_key=None,
    model_name=None,
    base_url=None,
    qwen_api: str = QWEN_API,
) -> str:
    mode = qwen_api.lower()
    if mode == "remote":
        key = api_key or os.getenv("ALIBABA_API_KEY")
        if not key:
            raise ValueError("ALIBABA_API_KEY required when --qwen-api remote")
        resolved_base = base_url or ALIBABA_BASE_URL
        resolved_model = (
            model_name if model_name and model_name != DEFAULT_QWEN_MODEL else ALIBABA_QWEN_MODEL
        )
    else:
        key = api_key or QWEN_DEFAULT_API_KEY
        resolved_base = base_url or QWEN_DEFAULT_BASE_URL
        resolved_model = model_name or DEFAULT_QWEN_MODEL
    b64 = _rgb_to_jpeg_b64(frame)
    client = OpenAI(base_url=resolved_base, api_key=key)
    resp = client.chat.completions.create(
        model=resolved_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=1024,
    )
    content = resp.choices[0].message.content
    if not content:
        return ""
    return content if isinstance(content, str) else str(content)


def describe_frame_with_qwen(
    frame,
    prompt: str | None = None,
    *,
    api_key=None,
    model_name=None,
    base_url=None,
    qwen_api: str = QWEN_API,
) -> str:
    """General VLM caption / scene description for one RGB frame."""
    text = (
        prompt
        or "Describe what you see in this image. Include objects, terrain, motion, and anything "
        "relevant for drone operation. Be concise but specific."
    )
    return _qwen_vision_chat(
        frame,
        text,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        qwen_api=qwen_api,
    ).strip()


def get_bbox_from_qwen_frame(
    frame,
    object_name=None,
    api_key=None,
    model_name=None,
    base_url=None,
    qwen_api: str = QWEN_API,
):
    prompt = (
        f"Look at this image and find the {object_name or 'most prominent object'}. "
        "Return ONLY a JSON object with format: {'name': 'object_name', 'bbox': [x1, y1, x2, y2]} "
        "where x1,y1 is the top-left and x2,y2 is the bottom-right corner of the bounding box. "
        "If not found, return None."
    )
    text = _qwen_vision_chat(
        frame,
        prompt,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        qwen_api=qwen_api,
    )
    if not text:
        return None
    return _parse_bbox_json(text)


def _parse_bbox_json(response):
    try:
        start_idx = response.find("{")
        end_idx = response.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            result = json.loads(response[start_idx:end_idx])
            if "bbox" in result and len(result["bbox"]) == 4:
                bb = result["bbox"]
                return (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
    except Exception:
        pass
    return None
