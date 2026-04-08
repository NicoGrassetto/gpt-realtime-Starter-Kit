import { useRef } from "react";
import {
  ArrowRight,
  Mic,
  MicOff,
  Camera,
  Plug,
  Unplug,
} from "lucide-react";
import "./ChatInput.css";

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  connected: boolean;
  recording: boolean;
  activeMode: string;
  models: Array<{ id: string; model: string; status: string }>;
  selectedModel: string;
  onModelChange: (model: string) => void;
  onConnect: () => void;
  onDisconnect: () => void;
  onToggleMic: () => void;
  onSendImage: (dataUrl: string, text?: string) => void;
  onSendText: (text: string) => void;
}

// Modes that accept audio input
const micModes = ["voice_assistant", "push_to_talk", "transcription", "vision", "vision_text"];
// Modes that show camera button
const cameraModes = ["vision", "vision_text"];
// Modes where text send is the primary input
const textInputModes = ["text_to_speech", "text_chat"];

export default function ChatInput({
  value,
  onChange,
  connected,
  recording,
  activeMode,
  models,
  selectedModel,
  onModelChange,
  onConnect,
  onDisconnect,
  onToggleMic,
  onSendImage,
  onSendText,
}: ChatInputProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const showMic = micModes.includes(activeMode);
  const showCamera = cameraModes.includes(activeMode);
  const isTextPrimary = textInputModes.includes(activeMode);

  const placeholder = isTextPrimary
    ? "Type your message…"
    : "How can I help you today?";

  function handleSend() {
    if (!value.trim()) return;
    onSendText(value.trim());
    onChange("");
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleImageCapture() {
    fileInputRef.current?.click();
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      onSendImage(dataUrl, value || undefined);
      onChange("");
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  }

  return (
    <div className="chat-input-wrapper">
      <div className="chat-input">
        <textarea
          rows={1}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={(e) => {
            const target = e.target as HTMLTextAreaElement;
            target.style.height = "auto";
            target.style.height = target.scrollHeight + "px";
          }}
        />
        <div className="chat-input-toolbar">
          <select
            className="chat-input-model"
            value={selectedModel}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={connected}
          >
            {models.length === 0 && (
              <option value="">Loading…</option>
            )}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </select>

          <div className="chat-input-actions">
            {/* Connect / Disconnect */}
            {connected ? (
              <button
                className="chat-input-btn chat-input-btn--connected"
                onClick={onDisconnect}
                aria-label="Disconnect"
                title="Disconnect"
              >
                <Unplug size={18} />
              </button>
            ) : (
              <button
                className="chat-input-btn"
                onClick={onConnect}
                aria-label="Connect"
                title="Connect"
              >
                <Plug size={18} />
              </button>
            )}

            {/* Mic toggle */}
            {showMic && connected && (
              <button
                className={`chat-input-btn${recording ? " chat-input-btn--recording" : ""}`}
                onClick={onToggleMic}
                aria-label={recording ? "Stop recording" : "Start recording"}
                title={recording ? "Stop recording" : "Start recording"}
              >
                {recording ? <MicOff size={18} /> : <Mic size={18} />}
              </button>
            )}

            {/* Camera (Vision mode) */}
            {showCamera && connected && (
              <button
                className="chat-input-btn"
                onClick={handleImageCapture}
                aria-label="Capture image"
                title="Send image"
              >
                <Camera size={18} />
              </button>
            )}

            {/* Send text */}
            <button
              className="chat-input-send"
              onClick={handleSend}
              aria-label="Send"
              disabled={!value.trim()}
            >
              <ArrowRight size={18} />
            </button>
          </div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />
      </div>
    </div>
  );
}
