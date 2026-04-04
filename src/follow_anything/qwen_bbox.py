import base64
import json
import os

import cv2
import numpy as np
from openai import OpenAI


def _rgb_to_jpeg_b64(frame):
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    _, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

    return base64.b64encode(buf.tobytes()).decode("ascii")


def get_bbox_from_qwen_frame(frame, object_name=None, api_key=None, model_name="qwen2.5-vl-72b-instruct"):
    key = api_key or os.getenv("ALIBABA_API_KEY")
    if not key:
        raise ValueError("key not available")

    prompt = (
        f"Look at this image and find the {object_name or 'most prominent object'}. "
        "Return ONLY a JSON object with format: {'name': 'object_name', 'bbox': [x1, y1, x2, y2]} "
        "where x1,y1 is the top-left and x2,y2 is the bottom-right corner of the bounding box. "
        "If not found, return None."
    )

    b64 = _rgb_to_jpeg_b64(frame)
    client = OpenAI(
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        api_key=key,
    )
    resp = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=512,
    )
    content = resp.choices[0].message.content
    if not content:
        return None
    text = content if isinstance(content, str) else str(content)
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
