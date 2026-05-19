"""HTTP server for MCP (POST /mcp) and GET /health."""

from __future__ import annotations

import logging
import threading

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from follow_anything.mcp.protocol import handle_jsonrpc, parse_json_body
from follow_anything.session import DroneSession

logger = logging.getLogger(__name__)


def create_app(session: DroneSession) -> FastAPI:
    lock = threading.Lock()
    app = FastAPI(title="follow-anything MCP")
    app.state.session = session
    app.state.lock = lock

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> Response:
        raw = await request.body()
        body, err = parse_json_body(raw)
        if body is None:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {err}"},
                },
                status_code=400,
            )

        sess: DroneSession = app.state.session
        lk: threading.Lock = app.state.lock
        result = handle_jsonrpc(body, sess, lk)
        if result is None:
            return Response(status_code=204)
        return JSONResponse(result)

    return app


def run_mcp_blocking(session: DroneSession, *, host: str, port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    app = create_app(session)
    logger.info("Starting MCP server host=%s port=%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
