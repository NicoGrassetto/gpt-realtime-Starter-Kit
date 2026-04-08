import asyncio
import json
import logging
import os
import pathlib
import re

import aiohttp
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("realtime-relay")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from azure.identity import DefaultAzureCredential

load_dotenv()

AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-realtime-1-5")
API_VERSION = "2025-04-01-preview"

# Read system prompt from chat.prompty
_prompty_path = pathlib.Path(__file__).parent / "chat.prompty"
_prompty_text = _prompty_path.read_text(encoding="utf-8")
_match = re.search(r"^system:\s*\n(.+?)(?:\nuser:|\Z)", _prompty_text, re.DOTALL | re.MULTILINE)
SYSTEM_PROMPT = _match.group(1).strip() if _match else "You are a helpful AI assistant."
logger.info("Loaded system prompt (%d chars): %.80s...", len(SYSTEM_PROMPT), SYSTEM_PROMPT)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_azure_token() -> str:
    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return token.token


def _build_realtime_url() -> str:
    host = AZURE_OPENAI_ENDPOINT.rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"
    return (
        f"{host}/openai/v1/realtime"
        f"?model={AZURE_OPENAI_DEPLOYMENT}"
        f"&api-version={API_VERSION}"
    )


def _session_update(mode: str = "push_to_talk") -> dict:
    """Build a session.update event. mode is 'push_to_talk' or 'continuous'."""
    session: dict = {
        "instructions": SYSTEM_PROMPT,
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "temperature": 0.7,
        "type": "realtime",
    }
    if mode == "continuous":
        session["turn_detection"] = {"type": "server_vad"}
    else:
        session["turn_detection"] = None
    return {"type": "session.update", "session": session}


FORWARD_EVENTS = frozenset([
    "session.created",
    "session.updated",
    "response.output_audio.delta",
    "response.output_audio_transcript.delta",
    "response.text.delta",
    "response.text.done",
    "response.output_audio.done",
    "response.output_audio_transcript.done",
    "response.content_part.added",
    "response.content_part.done",
    "response.output_item.added",
    "response.output_item.done",
    "response.done",
    "input_audio_buffer.speech_started",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.committed",
    "response.created",
    "error",
])


@app.get("/health")
async def health():
    """Quick check that the backend can reach Azure and get a token."""
    try:
        token = _get_azure_token()
        return JSONResponse({"status": "ok", "token_length": len(token), "endpoint": AZURE_OPENAI_ENDPOINT})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    logger.info("Browser client connected")

    try:
        token = _get_azure_token()
    except Exception as e:
        logger.exception("Failed to get Azure token")
        await ws.send_text(json.dumps({"type": "error", "error": {"message": f"Auth failed: {e}"}}))
        await ws.close()
        return

    url = _build_realtime_url()
    logger.info("Connecting to Azure Realtime API: %s", url)

    headers = {
        "Authorization": f"Bearer {token}",
        "openai-beta": "realtime=v1",
    }

    session = aiohttp.ClientSession()
    try:
        azure_ws = await session.ws_connect(
            url,
            headers=headers,
            max_msg_size=16 * 1024 * 1024,
            timeout=aiohttp.ClientWSTimeout(ws_close=10),
        )
        logger.info("Azure Realtime API connected")
    except Exception as e:
        logger.exception("Failed to connect to Azure Realtime API")
        await ws.send_text(json.dumps({"type": "error", "error": {"message": f"Azure connect failed: {e}"}}))
        await ws.close()
        await session.close()
        return

    # Send initial session config
    await azure_ws.send_str(json.dumps(_session_update("push_to_talk")))

    async def relay_client_to_azure():
        """Forward messages from the browser client to Azure."""
        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)

                if msg.get("type") == "session.update":
                    mode = msg.get("mode", "push_to_talk")
                    await azure_ws.send_str(json.dumps(_session_update(mode)))
                    continue

                await azure_ws.send_str(json.dumps(msg))
        except WebSocketDisconnect:
            logger.info("Browser client disconnected")
        except Exception as exc:
            logger.exception("client→azure error: %s", exc)
        finally:
            await azure_ws.close()

    async def relay_azure_to_client():
        """Forward messages from Azure back to the browser client."""
        try:
            async for azure_msg in azure_ws:
                if azure_msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(azure_msg.data)
                    event_type = data.get("type", "")

                    if event_type == "error":
                        logger.error("Azure error payload: %s", azure_msg.data)
                    elif event_type not in ("response.text.delta", "response.output_audio.delta"):
                        logger.info("Azure → Client: %s", event_type)

                    if event_type in FORWARD_EVENTS:
                        await ws.send_text(azure_msg.data)

                elif azure_msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.info("Azure WS closed/error: %s", azure_msg.type)
                    break
        except Exception as exc:
            logger.exception("azure→client error: %s", exc)
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    try:
        await asyncio.gather(
            relay_client_to_azure(),
            relay_azure_to_client(),
        )
    except Exception as e:
        logger.exception("Relay error: %s", e)
    finally:
        if not azure_ws.closed:
            await azure_ws.close()
        await session.close()
        logger.info("Session cleaned up")


# Serve the React production build as static files
_frontend_dist = pathlib.Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True, ws="wsproto")
