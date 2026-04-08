import asyncio
import base64
import json
import logging
import os
import struct
import sys
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing_extensions import assert_never

from azure.identity import DefaultAzureCredential

from agents.realtime import RealtimeRunner, RealtimeSession, RealtimeSessionEvent
from agents.realtime.config import RealtimeUserInputMessage
from agents.realtime.items import RealtimeItem
from agents.realtime.model import RealtimeModelConfig
from agents.realtime.model_inputs import RealtimeModelSendRawMessage

# Allow imports from project root (config/, prompts/, tools/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import load_session_config, list_modes
from prompts import list_prompts
from src.agent import get_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("realtime-relay")

load_dotenv()

AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-realtime-1-5")

app = FastAPI(title="GPT Realtime Starter Kit")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_credential = DefaultAzureCredential()


def _get_azure_token() -> str:
    token = _credential.get_token("https://cognitiveservices.azure.com/.default")
    return token.token


def _build_realtime_url(deployment: str | None = None) -> str:
    dep = deployment or AZURE_OPENAI_DEPLOYMENT
    host = AZURE_OPENAI_ENDPOINT.rstrip("/")
    # Ensure wss:// scheme (required by the Agents SDK websockets transport)
    host = host.replace("https://", "wss://").replace("http://", "ws://")
    if not host.startswith("ws"):
        host = f"wss://{host}"
    return f"{host}/openai/v1/realtime?model={dep}"


def _build_model_settings(mode: str, deployment: str | None = None) -> dict[str, Any]:
    """Translate YAML config into SDK RealtimeSessionModelSettings."""
    cfg = load_session_config(mode)

    model_name = deployment or AZURE_OPENAI_DEPLOYMENT
    settings: dict[str, Any] = {"model_name": model_name}

    # Output modalities
    modalities = cfg.get("modalities", ["text", "audio"])
    if "audio" in modalities:
        settings["output_modalities"] = ["audio"]
    else:
        settings["output_modalities"] = ["text"]

    # Audio nested structure (preferred by SDK)
    audio_input: dict[str, Any] = {}
    audio_output: dict[str, Any] = {}

    # Input format
    in_fmt = cfg.get("input_audio_format", "pcm16")
    audio_input["format"] = in_fmt

    # Turn detection
    td = cfg.get("turn_detection")
    if td is None:
        audio_input["turn_detection"] = None
    elif isinstance(td, dict):
        td_type = td.get("type", "server_vad")
        if td_type == "semantic_vad":
            clean_td: dict[str, Any] = {"type": "semantic_vad"}
            if "eagerness" in td:
                clean_td["eagerness"] = td["eagerness"]
        else:
            clean_td = {k: v for k, v in td.items() if k in (
                "type", "threshold", "prefix_padding_ms",
                "silence_duration_ms", "create_response", "interrupt_response",
            )}
        audio_input["turn_detection"] = clean_td

    # Input transcription
    transcription = cfg.get("input_audio_transcription")
    if transcription:
        audio_input["transcription"] = transcription

    # Output format
    out_fmt = cfg.get("output_audio_format", "pcm16")
    audio_output["format"] = out_fmt

    # Voice
    voice = cfg.get("voice")
    if voice:
        audio_output["voice"] = voice

    settings["audio"] = {}
    if audio_input:
        settings["audio"]["input"] = audio_input
    if audio_output:
        settings["audio"]["output"] = audio_output

    return settings


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------


class RealtimeWebSocketManager:
    """Manages SDK RealtimeSessions for connected browser clients."""

    def __init__(self) -> None:
        self.active_sessions: dict[str, RealtimeSession] = {}
        self.session_contexts: dict[str, Any] = {}
        self.websockets: dict[str, WebSocket] = {}

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str,
        mode: str = "voice_assistant",
        prompt: str = "default",
        model: str | None = None,
    ) -> None:
        await websocket.accept()
        self.websockets[session_id] = websocket

        agent = get_agent(prompt)
        runner = RealtimeRunner(agent)

        token = _get_azure_token()
        model_config: RealtimeModelConfig = {
            "url": _build_realtime_url(model),
            "headers": {"authorization": f"Bearer {token}"},
            "initial_model_settings": _build_model_settings(mode, model),
        }

        session_context = await runner.run(model_config=model_config)
        session = await session_context.__aenter__()
        self.active_sessions[session_id] = session
        self.session_contexts[session_id] = session_context

        asyncio.create_task(self._process_events(session_id))

    async def disconnect(self, session_id: str) -> None:
        if session_id in self.session_contexts:
            await self.session_contexts[session_id].__aexit__(None, None, None)
            del self.session_contexts[session_id]
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
        if session_id in self.websockets:
            del self.websockets[session_id]

    async def send_audio(self, session_id: str, audio_bytes: bytes) -> None:
        if session_id in self.active_sessions:
            await self.active_sessions[session_id].send_audio(audio_bytes)

    async def send_client_event(self, session_id: str, event: dict[str, Any]) -> None:
        session = self.active_sessions.get(session_id)
        if not session:
            return
        await session.model.send_event(
            RealtimeModelSendRawMessage(
                message={
                    "type": event["type"],
                    **{k: v for k, v in event.items() if k != "type"},
                }
            )
        )

    async def send_user_message(
        self, session_id: str, message: RealtimeUserInputMessage
    ) -> None:
        session = self.active_sessions.get(session_id)
        if not session:
            return
        await session.send_message(message)

    async def interrupt(self, session_id: str) -> None:
        session = self.active_sessions.get(session_id)
        if not session:
            return
        await session.interrupt()

    # -- Event processing --------------------------------------------------

    def _sanitize_history_item(self, item: RealtimeItem) -> dict[str, Any]:
        item_dict = item.model_dump()
        content = item_dict.get("content")
        if isinstance(content, list):
            sanitized: list[Any] = []
            for part in content:
                if isinstance(part, dict):
                    p = part.copy()
                    if p.get("type") in ("audio", "input_audio"):
                        p.pop("audio", None)
                    sanitized.append(p)
                else:
                    sanitized.append(part)
            item_dict["content"] = sanitized
        return item_dict

    async def _serialize_event(self, event: RealtimeSessionEvent) -> dict[str, Any]:
        base: dict[str, Any] = {"type": event.type}

        if event.type == "agent_start":
            base["agent"] = event.agent.name
        elif event.type == "agent_end":
            base["agent"] = event.agent.name
        elif event.type == "handoff":
            base["from"] = event.from_agent.name
            base["to"] = event.to_agent.name
        elif event.type == "tool_start":
            base["tool"] = event.tool.name
        elif event.type == "tool_end":
            base["tool"] = event.tool.name
            base["output"] = str(event.output)
        elif event.type == "tool_approval_required":
            base["tool"] = event.tool.name
            base["call_id"] = event.call_id
            base["arguments"] = event.arguments
            base["agent"] = event.agent.name
        elif event.type == "audio":
            base["audio"] = base64.b64encode(event.audio.data).decode("utf-8")
        elif event.type in ("audio_interrupted", "audio_end"):
            pass
        elif event.type == "history_updated":
            base["history"] = [
                self._sanitize_history_item(item) for item in event.history
            ]
        elif event.type == "history_added":
            try:
                base["item"] = self._sanitize_history_item(event.item)
            except Exception:
                base["item"] = None
        elif event.type == "guardrail_tripped":
            base["guardrail_results"] = [
                {"name": r.guardrail.name} for r in event.guardrail_results
            ]
        elif event.type == "raw_model_event":
            base["raw_model_event"] = {"type": event.data.type}
        elif event.type == "error":
            base["error"] = str(event.error) if hasattr(event, "error") else "Unknown"
        elif event.type == "input_audio_timeout_triggered":
            pass
        else:
            assert_never(event)

        return base

    async def _process_events(self, session_id: str) -> None:
        try:
            session = self.active_sessions[session_id]
            websocket = self.websockets[session_id]

            async for event in session:
                event_data = await self._serialize_event(event)
                await websocket.send_text(json.dumps(event_data))
        except Exception as e:
            logger.error("Error processing events for %s: %s", session_id, e)


manager = RealtimeWebSocketManager()


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    try:
        token = _get_azure_token()
        return JSONResponse({
            "status": "ok",
            "token_length": len(token),
            "endpoint": AZURE_OPENAI_ENDPOINT,
            "deployment": AZURE_OPENAI_DEPLOYMENT,
        })
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


@app.get("/api/modes")
async def get_modes():
    return JSONResponse({"modes": list_modes()})


@app.get("/api/prompts")
async def get_prompts():
    return JSONResponse({"prompts": list_prompts()})


@app.get("/api/models")
async def get_models():
    """List available Azure OpenAI deployments."""
    try:
        token = _get_azure_token()
        endpoint = AZURE_OPENAI_ENDPOINT.rstrip("/")
        url = f"{endpoint}/openai/deployments?api-version=2024-10-21"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

        models = []
        for dep in data.get("data", []):
            models.append({
                "id": dep.get("id", ""),
                "model": dep.get("model", ""),
                "status": dep.get("status", ""),
            })

        # Put the current default first
        models.sort(key=lambda m: (0 if m["id"] == AZURE_OPENAI_DEPLOYMENT else 1, m["id"]))

        return JSONResponse({"models": models, "default": AZURE_OPENAI_DEPLOYMENT})
    except Exception as e:
        logger.exception("Failed to list models")
        return JSONResponse({
            "models": [{
                "id": AZURE_OPENAI_DEPLOYMENT,
                "model": AZURE_OPENAI_DEPLOYMENT,
                "status": "unknown",
            }],
            "default": AZURE_OPENAI_DEPLOYMENT,
            "error": str(e),
        })


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    mode: str = "voice_assistant",
    prompt: str = "default",
    model: str | None = None,
):
    logger.info("Client connecting — session=%s, mode=%s, prompt=%s, model=%s", session_id, mode, prompt, model or "default")

    try:
        await manager.connect(websocket, session_id, mode, prompt, model)
    except FileNotFoundError as e:
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "error": str(e)}))
        await websocket.close()
        return
    except Exception as e:
        logger.exception("Failed to connect session %s", session_id)
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "error": str(e)}))
        await websocket.close()
        return

    logger.info("Session %s connected", session_id)

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message["type"] == "audio":
                int16_data = message["data"]
                audio_bytes = struct.pack(f"{len(int16_data)}h", *int16_data)
                await manager.send_audio(session_id, audio_bytes)

            elif message["type"] == "image":
                data_url = message.get("data_url")
                prompt_text = message.get("text") or "Please describe this image."
                if data_url:
                    user_msg: RealtimeUserInputMessage = {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_image", "image_url": data_url, "detail": "high"},
                            {"type": "input_text", "text": prompt_text},
                        ],
                    }
                    await manager.send_user_message(session_id, user_msg)

            elif message["type"] == "commit_audio":
                await manager.send_client_event(
                    session_id, {"type": "input_audio_buffer.commit"}
                )

            elif message["type"] == "interrupt":
                await manager.interrupt(session_id)

            elif message["type"] == "text":
                text = message.get("text", "")
                if text:
                    user_msg = {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": text},
                        ],
                    }
                    await manager.send_user_message(session_id, user_msg)

    except WebSocketDisconnect:
        logger.info("Client disconnected — session=%s", session_id)
    except Exception as e:
        logger.exception("WebSocket error for session %s: %s", session_id, e)
    finally:
        await manager.disconnect(session_id)
        logger.info("Session %s cleaned up", session_id)


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
