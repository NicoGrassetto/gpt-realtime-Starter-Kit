# GPT Realtime Starter Kit

[![Open in GitHub Codespaces](https://img.shields.io/static/v1?style=for-the-badge&label=GitHub+Codespaces&message=Open&color=brightgreen&logo=github)](https://codespaces.new/NicoGrassetto/gpt-4o-realtime-Starter-Kit)
[![Open in Dev Containers](https://img.shields.io/static/v1?style=for-the-badge&label=Dev+Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/NicoGrassetto/gpt-4o-realtime-Starter-Kit)

A starter kit for building realtime speech-to-speech applications using the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) and the GPT Realtime API on Azure AI Foundry. It uses **Bicep** infrastructure-as-code and `azd` deployment automation to provision an Azure OpenAI resource with a GA Realtime model, then connects a **FastAPI** server via WebSocket to relay audio and SDK events between the browser and Azure.

<p align="center">
  <a href="#project-structure">Project Structure</a> |
  <a href="#quick-start">Quick Start</a> |
  <a href="#manual-setup">Manual Setup</a> |
  <a href="#supported-ga-realtime-models">Supported GA Realtime Models</a> |
  <a href="#customization">Customization</a>
</p>

<p align="center">
  <!-- TODO: Add architecture diagram -->
</p>

## Project Structure

```
├── assets/                        # Static assets
├── config/
│   ├── __init__.py                # YAML config loader (modes + defaults)
│   ├── session_defaults.yaml      # Shared session baseline
│   └── modes/                     # Mode presets (voice_assistant, transcription, etc.)
├── frontend/
│   ├── index.html                 # Entry HTML
│   ├── package.json               # Frontend dependencies
│   ├── vite.config.ts             # Vite bundler config
│   └── src/                       # React app (components, hooks, lib)
├── hooks/
│   ├── postprovision.ps1          # Post-provision hook (Windows)
│   └── postprovision.sh           # Post-provision hook (Linux/Mac)
├── infra/
│   ├── main.bicep                 # Bicep orchestrator (subscription-scoped)
│   ├── main.parameters.json       # Parameter bindings for azd
│   └── core/
│       ├── ai-resource.bicep      # Azure OpenAI (Cognitive Services) account
│       ├── ai-model-deployment.bicep  # gpt-realtime-1.5 model deployment
│       └── role-assignment.bicep  # RBAC: Cognitive Services OpenAI User
├── prompts/
│   ├── __init__.py                # Prompt loader (.prompty files)
│   ├── default.prompty            # General-purpose voice assistant
│   ├── customer_support.prompty   # Domain-specific support agent
│   └── transcriber.prompty        # Transcription + translation
├── src/
│   ├── main.py                    # FastAPI server with SDK session manager
│   └── agent.py                   # RealtimeAgent factory
├── tools/
│   ├── __init__.py                # Tool exports (ALL_TOOLS list)
│   ├── weather.py                 # @function_tool: get_weather
│   └── search.py                  # @function_tool: search_knowledge_base
├── azure.yaml                     # Azure Developer CLI project config
├── LICENSE
├── README.md
└── requirements.txt
```

## Quick Start

```bash
azd auth login
azd up                  # provisions infra and writes .env via post-provision hook
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## Manual Setup

### 1. Deploy Infrastructure

```bash
azd auth login
azd up
```

You will be prompted to:
- Enter an **environment name** (e.g. `gptrealtimedev`)
- Select your **Azure subscription**
- Select a **region** (recommended: `Sweden Central` or `East US 2` for best model availability)

After provisioning completes, a `.env` file is generated at the project root with:

```
AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com/"
AZURE_OPENAI_DEPLOYMENT="gpt-realtime-1-5"
```

### 2. Install Dependencies & Run

```bash
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### 3. Tear Down

To remove all deployed Azure resources:

```bash
azd down
```

## Supported GA Realtime Models

This starter kit targets the **GA (Generally Available)** Realtime API only. Preview/beta models (`gpt-4o-realtime-preview`, `gpt-4o-mini-realtime-preview`) are **not** supported.

| Model ID | Version | Description |
|---|---|---|
| `gpt-realtime-1.5` | `2026-02-23` | Latest and best quality — **default for this kit** |
| `gpt-realtime` | `2025-08-28` | Base GA realtime model |
| `gpt-realtime-mini` | `2025-12-15` | Cost-efficient, updated mini |
| `gpt-realtime-mini` | `2025-10-06` | Cost-efficient GA model |

To use a different model, set the `AZURE_OPENAI_DEPLOYMENT` environment variable to the deployment name of any GA model above.

## Customization

### Prompts

System prompts live in [prompts/](prompts/) as `.prompty` files. Each file has a YAML frontmatter block followed by the prompt text under `system:`.

To change the assistant's personality, edit an existing file or create a new one:

```yaml
---
name: my_agent
description: My custom assistant
authors:
  - your-name
model:
  api: realtime
  configuration:
    type: azure_openai
    azure_deployment: gpt-realtime-1-5
---

system:
You are a concise technical assistant that answers in bullet points.
```

The prompt is selected at connection time via the `prompt` query parameter on the WebSocket URL (e.g. `/ws/{session_id}?prompt=my_agent`). If omitted, `default` is used. Available prompts are listed at the `GET /prompts` endpoint.

### Function Tools

Tools are Python functions decorated with `@function_tool` from the OpenAI Agents SDK. They live in [tools/](tools/) and are auto-executed by the SDK when the model calls them.

To add a new tool:

1. Create a new file under `tools/` (e.g. `tools/calculator.py`):

   ```python
   from agents import function_tool

   @function_tool
   def calculate(expression: str) -> str:
       """Evaluate a math expression and return the result."""
       return str(eval(expression))  # replace with a safe parser
   ```

2. Register it in [tools/__init__.py](tools/__init__.py):

   ```python
   from tools.calculator import calculate

   ALL_TOOLS = [get_weather, search_knowledge_base, calculate]
   ```

The agent will automatically discover and call the new tool when relevant.

### Session Settings

The file [config/session_defaults.yaml](config/session_defaults.yaml) defines the baseline session configuration sent to the Realtime API on every connection. Mode presets override these defaults.

| Setting | Default | Description |
|---|---|---|
| `voice` | `alloy` | TTS voice. Options: `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse` |
| `input_audio_format` | `pcm16` | Format of audio sent from the client (`pcm16` or `g711_ulaw`) |
| `output_audio_format` | `pcm16` | Format of audio returned to the client (`pcm16` or `g711_ulaw`) |
| `temperature` | `0.7` | Sampling temperature (0.0–1.0). Lower = more deterministic |
| `modalities` | `[text, audio]` | Output modalities. `[text]` for text-only, `[text, audio]` for speech |
| `input_audio_transcription.model` | `whisper-1` | Model used to transcribe incoming audio |
| `turn_detection.type` | `server_vad` | Turn detection strategy: `server_vad` (auto), `semantic_vad` (semantic), or `null` (manual/push-to-talk) |
| `turn_detection.threshold` | `0.5` | VAD sensitivity (0.0–1.0). Higher = requires louder speech to trigger |
| `turn_detection.prefix_padding_ms` | `300` | Audio included before detected speech starts (ms) |
| `turn_detection.silence_duration_ms` | `200` | Silence needed to end a turn (ms) |
| `turn_detection.create_response` | `true` | Automatically generate a response when a turn ends |

### Modes

Mode presets in [config/modes/](config/modes/) override specific session defaults to create purpose-built configurations. The frontend selects a mode, and the server merges it on top of `session_defaults.yaml`.

| Mode | Description |
|---|---|
| `voice_assistant` | Continuous voice conversation with server VAD |
| `push_to_talk` | Manual commit — client sends audio and explicitly triggers a response |
| `text_chat` | Text input and text output only — no audio |
| `text_to_speech` | Text input, audio + text output — type a message and hear the response |
| `transcription` | Audio in, text only out — live transcription / translation (uses `semantic_vad`) |
| `vision` | Image + audio input, audio + text output |
| `vision_text` | Image + audio input, text only output |

To create a custom mode, add a new YAML file under `config/modes/`:

```yaml
name: my_mode
description: Low-temperature text-only mode

session:
  modalities: [text]
  temperature: 0.2
  turn_detection: null
```

Only the settings you specify are overridden; everything else inherits from `session_defaults.yaml`.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
