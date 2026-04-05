# Using GPT Realtime API for Audio Transcription

This tutorial walks through how to use the **GPT Realtime API** (`gpt-4o-realtime`) for multilingual speech-to-text transcription over a persistent WebSocket connection. It is based on the approach used in this project for real-time European Parliament session transcription.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Architecture at a Glance](#architecture-at-a-glance)
4. [Step 1 — Connect to the Realtime API](#step-1--connect-to-the-realtime-api)
5. [Step 2 — Configure the Session](#step-2--configure-the-session)
6. [Step 3 — Stream Audio In](#step-3--stream-audio-in)
7. [Step 4 — Read Transcription Results](#step-4--read-transcription-results)
8. [Putting It All Together](#putting-it-all-together)
9. [Voice Activity Detection (VAD)](#voice-activity-detection-vad)
10. [Tips & Pitfalls](#tips--pitfalls)

---

## Overview

The GPT Realtime API is a **WebSocket-based** streaming interface for GPT models. Unlike the REST Chat Completions API (send a complete request, get a response), this is a **bidirectional, event-driven** connection where you push audio frames and receive events asynchronously.

For transcription, the flow is:

1. Open a WebSocket connection to the GPT Realtime endpoint.
2. Configure a session with text-only output and transcription instructions.
3. Stream raw audio chunks into the connection.
4. Receive streamed transcription text back as events.

The model natively handles **multilingual audio** — it detects the spoken language and transcribes it verbatim, without needing separate language-detection or ASR services.

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Azure OpenAI resource** | With a `gpt-4o-realtime` (or equivalent) model deployed |
| **Python 3.10+** | With `asyncio` support |
| **Python packages** | `websockets`, `azure-identity`, `pydub` (for audio conversion) |
| **Authentication** | Azure Entra ID credentials (e.g. `AzureDeveloperCliCredential`) |
| **Audio format** | 24 kHz, 16-bit mono PCM (the API's expected format) |

Install the dependencies:

```bash
pip install websockets azure-identity pydub
```

---

## Architecture at a Glance

```
┌─────────────┐       WebSocket (wss://)        ┌──────────────────┐
│  Your App   │ ──── audio chunks (base64) ────► │  GPT Realtime    │
│  (Python)   │ ◄─── text events (JSON)  ─────── │  API             │
└─────────────┘                                  └──────────────────┘
```

The protocol is **event-driven**: you send JSON messages, the server sends JSON messages back.

```
CLIENT                                    SERVER
  |                                         |
  |  ← session.created                      |  (automatic on connect)
  |                                         |
  |  session.update →                       |  (configure session)
  |  ← session.updated                      |
  |                                         |
  |  input_audio_buffer.append →            |  (send audio chunks)
  |  input_audio_buffer.append →            |  (keep sending...)
  |                                         |
  |  ← response.text.delta                  |  (streaming text tokens)
  |  ← response.text.delta                  |
  |  ← response.done                        |  (response complete)
```

---

## Step 1 — Connect to the Realtime API

The endpoint URL follows this pattern:

```
wss://{your-resource}.openai.azure.com/openai/realtime?api-version=2025-04-01-preview&deployment={deployment-name}
```

Authentication is via a Bearer token in the WebSocket headers.

```python
import websockets
from azure.identity import AzureDeveloperCliCredential

ENDPOINT = "https://your-resource.openai.azure.com"
DEPLOYMENT = "gpt-realtime"

# Get a token for Azure Cognitive Services
credential = AzureDeveloperCliCredential(process_timeout=30)
token = credential.get_token("https://cognitiveservices.azure.com/.default")

# Build the WSS URL
host = ENDPOINT.replace("https://", "")
ws_url = f"wss://{host}/openai/realtime?api-version=2025-04-01-preview&deployment={DEPLOYMENT}"

# Connect
async with websockets.connect(
    ws_url,
    additional_headers={"Authorization": f"Bearer {token.token}"},
) as ws:
    # The server immediately sends a session.created event
    msg = json.loads(await ws.recv())
    assert msg["type"] == "session.created"
    print("Connected! Session created.")
```

> **Tip:** Use `AzureDeveloperCliCredential` directly rather than `DefaultAzureCredential`. The latter probes IMDS (Instance Metadata Service) first, which adds ~60 seconds of delay on a local dev machine.

---

## Step 2 — Configure the Session

After connecting, send a `session.update` event to tell the model what to do. For transcription, the key settings are:

| Setting | Value | Why |
|---|---|---|
| `modalities` | `["text"]` | We only want text output, not audio |
| `instructions` | *(system prompt)* | Tell the model to transcribe verbatim |
| `input_audio_format` | `"pcm16"` | Raw 24 kHz 16-bit mono PCM |
| `input_audio_transcription` | `{"model": "whisper-1"}` | Also runs Whisper on the input (optional, for comparison) |
| `turn_detection` | `server_vad`, `semantic_vad`, or `null` | How to segment speech (see [VAD section](#voice-activity-detection-vad)) |

```python
import json

await ws.send(json.dumps({
    "type": "session.update",
    "session": {
        "modalities": ["text"],
        "instructions": (
            "You are a multilingual transcription assistant. "
            "You will hear speech in various languages.\n"
            "For each speech segment, respond with ONLY the BCP-47 "
            "language code and the verbatim transcription, in this "
            "exact format:\n"
            "[language_code]: transcribed text\n\n"
            "Examples:\n"
            "[fr-FR]: Bonjour, je suis le representant de la France.\n"
            "[de-DE]: Guten Tag, ich bin der Vertreter Deutschlands.\n"
            "[en-GB]: Good morning, I am the representative.\n\n"
            "Rules:\n"
            "- Use the most specific BCP-47 code (e.g. pt-PT not just pt)\n"
            "- Transcribe verbatim — do not paraphrase, translate, or summarise\n"
            "- Do not add commentary, greetings, or questions\n"
            "- Each response must be exactly one line in the format above\n"
            "- If the segment contains multiple sentences, output one line per sentence"
        ),
        "input_audio_format": "pcm16",
        "input_audio_transcription": {"model": "whisper-1"},
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
        },
    },
}))

# Wait for confirmation
while True:
    msg = json.loads(await ws.recv())
    if msg["type"] == "session.updated":
        print("Session configured!")
        break
    if msg["type"] == "error":
        raise RuntimeError(f"Config error: {msg.get('error')}")
```

### The System Prompt Matters

The `instructions` field acts as a system prompt. By telling the model to respond in a strict `[lang_code]: text` format, you get structured, parseable output. The model will:

- Detect the spoken language automatically
- Transcribe verbatim (not translate or summarise)
- Output one line per sentence

---

## Step 3 — Stream Audio In

Audio must be sent as **base64-encoded PCM16** (24 kHz, mono, 16-bit) in `input_audio_buffer.append` events.

### Converting Audio to the Right Format

If your source audio isn't already 24 kHz mono PCM16, use `pydub` to convert:

```python
from pydub import AudioSegment

audio = AudioSegment.from_file("recording.mp3")
audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
raw_bytes = audio.raw_data  # PCM16 bytes
```

### Sending Chunks

Send audio in small frames. A good default is **4800 bytes per frame** (= 100 ms of 24 kHz mono PCM16):

```python
import base64

CHUNK_SIZE = 4800  # 100 ms of audio per frame

async def feed_audio(ws, raw_audio_bytes: bytes):
    for i in range(0, len(raw_audio_bytes), CHUNK_SIZE):
        chunk = raw_audio_bytes[i : i + CHUNK_SIZE]
        await ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(chunk).decode("ascii"),
        }))
```

> **Math:** 24,000 samples/s × 2 bytes/sample = 48,000 bytes/s. So 4,800 bytes = 100 ms.

### For Live Microphone Input

When capturing from a microphone, simply forward each audio buffer as it arrives:

```python
async def stream_from_mic(ws, audio_queue: asyncio.Queue[bytes]):
    while True:
        chunk = await audio_queue.get()
        for i in range(0, len(chunk), CHUNK_SIZE):
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(chunk[i:i+CHUNK_SIZE]).decode("ascii"),
            }))
```

---

## Step 4 — Read Transcription Results

The server sends results as a stream of events. The key ones for transcription are:

| Event | What it contains |
|---|---|
| `response.text.delta` | A streaming fragment of text (may be partial) |
| `response.done` | The response is complete — contains the full output |

### Streaming Approach (Low Latency)

Process `response.text.delta` events as they arrive. Since the model streams token by token, accumulate text in a buffer and emit complete lines:

```python
async def read_transcriptions(ws):
    text_buf = ""

    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        event_type = msg["type"]

        if event_type == "response.text.delta":
            text_buf += msg.get("delta", "")

            # Emit complete lines as they arrive
            while "\n" in text_buf:
                line, text_buf = text_buf.split("\n", 1)
                line = line.strip()
                if line:
                    segment = parse_transcription(line)
                    print(f"[{segment['language']}] {segment['text']}")

        elif event_type == "response.done":
            # Flush any remaining text
            for line in text_buf.strip().splitlines():
                line = line.strip()
                if line:
                    segment = parse_transcription(line)
                    print(f"[{segment['language']}] {segment['text']}")
            text_buf = ""

        elif event_type == "error":
            print(f"Error: {msg.get('error')}")
```

### Parsing the Output

The model outputs lines in `[lang_code]: text` format. Parse them like this:

```python
def parse_transcription(text: str) -> dict:
    """Parse '[lang_code]: transcription' into {language, text}."""
    if text.startswith("[") and "]: " in text:
        close = text.index("]")
        return {
            "language": text[1:close],
            "text": text[close + 3:],
        }
    return {"language": "unknown", "text": text}
```

---

## Putting It All Together

Here is a minimal end-to-end example that transcribes a live audio stream:

```python
import asyncio
import base64
import json

import websockets
from azure.identity import AzureDeveloperCliCredential

ENDPOINT = "https://your-resource.openai.azure.com"
DEPLOYMENT = "gpt-realtime"
CHUNK_SIZE = 4800


def get_token() -> str:
    cred = AzureDeveloperCliCredential(process_timeout=30)
    return cred.get_token("https://cognitiveservices.azure.com/.default").token


def parse_transcription(text: str) -> dict:
    if text.startswith("[") and "]: " in text:
        close = text.index("]")
        return {"language": text[1:close], "text": text[close + 3:]}
    return {"language": "unknown", "text": text}


async def transcribe(audio_queue: asyncio.Queue[bytes]):
    token = get_token()
    host = ENDPOINT.replace("https://", "")
    url = f"wss://{host}/openai/realtime?api-version=2025-04-01-preview&deployment={DEPLOYMENT}"

    async with websockets.connect(
        url, additional_headers={"Authorization": f"Bearer {token}"}
    ) as ws:
        # 1. Wait for session.created
        msg = json.loads(await ws.recv())
        assert msg["type"] == "session.created"

        # 2. Configure session
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "instructions": (
                    "You are a transcription assistant. For each speech segment, "
                    "respond with: [language_code]: transcribed text"
                ),
                "input_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "silence_duration_ms": 500,
                },
            },
        }))
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == "session.updated":
                break

        # 3. Run two concurrent loops: feed audio in, read results out
        async def feed_audio():
            while True:
                chunk = await audio_queue.get()
                if chunk is None:  # sentinel to stop
                    break
                for i in range(0, len(chunk), CHUNK_SIZE):
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk[i:i+CHUNK_SIZE]).decode(),
                    }))

        async def read_responses():
            text_buf = ""
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg["type"] == "response.text.delta":
                    text_buf += msg.get("delta", "")
                    while "\n" in text_buf:
                        line, text_buf = text_buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            seg = parse_transcription(line)
                            print(f"[{seg['language']}] {seg['text']}")
                elif msg["type"] == "response.done":
                    for line in text_buf.strip().splitlines():
                        line = line.strip()
                        if line:
                            seg = parse_transcription(line)
                            print(f"[{seg['language']}] {seg['text']}")
                    text_buf = ""

        await asyncio.gather(feed_audio(), read_responses())
```

---

## Voice Activity Detection (VAD)

VAD determines **when someone is speaking vs. when there's silence**. It segments continuous audio into discrete utterances. The GPT Realtime API supports three modes:

| Mode | How It Works | Best For |
|---|---|---|
| `server_vad` | Energy/threshold-based detection. Configure `threshold` (0–1), `silence_duration_ms`, and `prefix_padding_ms`. Fast but simple — it just detects sound vs. silence. | Live microphone input at real-time speed |
| `semantic_vad` | Uses the model's understanding of speech to detect turn boundaries. Considers meaning, not just silence — knows a brief pause mid-sentence isn't a turn end. Smarter but higher latency. | Conversational turn-taking |
| `null` (disabled) | No automatic detection. You manually call `input_audio_buffer.commit` + `response.create` to mark segment boundaries. | Pre-recorded audio, batch processing |

### `server_vad` Configuration

```json
{
    "type": "server_vad",
    "threshold": 0.5,
    "prefix_padding_ms": 300,
    "silence_duration_ms": 500
}
```

- **`threshold`** (0–1): Sensitivity. Higher = requires louder speech to trigger. Start with 0.5.
- **`silence_duration_ms`**: How many milliseconds of silence mark the end of a turn. 500 ms is a good default.
- **`prefix_padding_ms`**: How much audio before the detected speech onset to include (catches the first word).

When `server_vad` is active, the server automatically:
1. Fires `input_audio_buffer.speech_started` when speech begins
2. Fires `input_audio_buffer.speech_stopped` when silence is detected
3. Commits the buffer and generates a response

### Manual Mode (`null`) — For Pre-Recorded Audio

When processing pre-recorded audio (sent faster than real-time), VAD modes break down because each new `speech_started` event **cancels the in-progress response** before the model finishes generating output. The fix is to disable VAD and manually control segment boundaries:

```python
# Configure with no VAD
"turn_detection": None

# Then for each segment of audio:
# 1. Send all audio chunks
for chunk in audio_segments:
    await ws.send(json.dumps({
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(chunk).decode(),
    }))

# 2. Commit the buffer (marks a complete turn)
await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

# 3. Ask the model to respond
await ws.send(json.dumps({"type": "response.create"}))

# 4. Wait for response.done before sending the next segment
```

---

## Tips & Pitfalls

### Audio Format

- The API expects **24 kHz, 16-bit, mono PCM** (`pcm16`). Other supported formats are `g711_ulaw` and `g711_alaw`.
- Always convert before sending. With `pydub`: `.set_frame_rate(24000).set_channels(1).set_sample_width(2)`.
- 4,800 bytes = 100 ms of audio. This is a good frame size to balance latency and overhead.

### Authentication

- Use `AzureDeveloperCliCredential(process_timeout=30)` for local development — it's much faster than `DefaultAzureCredential` which probes IMDS first (~60s delay).
- Token scope: `https://cognitiveservices.azure.com/.default`.
- Cache tokens and refresh before expiry. Tokens last ~1 hour.

### Use the Preview Endpoint

The endpoint **must** use the preview API version:

```
wss://{host}/openai/realtime?api-version=2025-04-01-preview&deployment={name}
```

The GA endpoint (`/openai/v1/realtime`) requires undocumented session fields and rejects standard parameters.

### System Prompt Engineering

The quality of transcription depends heavily on the `instructions` (system prompt):

- **Be explicit about output format** — e.g., `[fr-FR]: text`. This makes parsing trivial.
- **Say "verbatim"** — prevents the model from paraphrasing or summarising.
- **Provide examples** — the model follows the demonstrated pattern closely.
- **Specify BCP-47 codes** — e.g., `pt-PT` not just `pt`, `en-GB` not just `en`.

### Multi-Line Responses

With `modalities: ["text"]`, the model can output multiple lines per response. Split on newlines to extract individual transcription segments. This is why the streaming approach accumulates text in a buffer and emits on `\n`.

### Performance

In this project, the GPT Realtime API transcribed **5 minutes of multilingual audio** (French, English, Portuguese, Spanish) into **36 segments** in approximately **45 seconds** using the manual commit approach — roughly 6.5× real-time speed.

### Error Handling

Always handle these server events:

- `error` — log and decide whether to retry or abort.
- `response.done` with `status=cancelled` — the response was interrupted (common when VAD misfires). Check `output_count` in the response.

---

## Further Reading

- [GPT Realtime API Reference](GPT_REALTIME_API_REFERENCE.md) — detailed event reference and VAD documentation for this project
- [Audio-to-Translations Sequence](audio-to-translations-sequence.md) — full pipeline sequence diagram
