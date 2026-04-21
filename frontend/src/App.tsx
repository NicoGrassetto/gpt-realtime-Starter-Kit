import { useCallback, useEffect, useRef, useState } from "react";
import Navbar from "./components/Navbar";
import ModalityMatrix from "./components/ModalityMatrix";
import HeroText from "./components/HeroText";
import ChatInput from "./components/ChatInput";
import Transcript from "./components/Transcript";
import StatusBar from "./components/StatusBar";
import AudioOrb from "./components/AudioOrb";
import { useRealtime } from "./hooks/useRealtime";
import { createAudioCapture, type AudioCapture } from "./lib/audioCapture";
import { createAudioPlayer, type AudioPlayer } from "./lib/audioPlayer";
import "./App.css";

// Modes that show the audio orb (audio output)
const orbModes = ["voice_assistant", "push_to_talk", "vision", "text_to_speech"];
// Modes that show vision image preview
const visionModes = ["vision", "vision_text"];
// Modes whose output is text-only (no audio playback)
const textOnlyOutputModes = ["transcription", "vision_text", "text_chat"];

interface ModelInfo {
  id: string;
  model: string;
  status: string;
}

export default function App() {
  const [inputValue, setInputValue] = useState("");
  const [activeMode, setActiveMode] = useState("voice_assistant");
  const [recording, setRecording] = useState(false);
  const [aiSpeaking, setAiSpeaking] = useState(false);
  const [lastImage, setLastImage] = useState<string | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState("");

  const activeModeRef = useRef(activeMode);
  activeModeRef.current = activeMode;

  const playerRef = useRef<AudioPlayer | null>(null);
  const captureRef = useRef<AudioCapture | null>(null);

  function getPlayer() {
    if (!playerRef.current) {
      playerRef.current = createAudioPlayer(24000);
    }
    return playerRef.current;
  }

  const handleAudioChunk = useCallback((base64: string) => {
    if (textOnlyOutputModes.includes(activeModeRef.current)) return;
    setAiSpeaking(true);
    getPlayer().enqueue(base64);
  }, []);

  const handleAudioEnd = useCallback(() => {
    setAiSpeaking(false);
  }, []);

  const handleAudioInterrupted = useCallback(() => {
    setAiSpeaking(false);
    if (textOnlyOutputModes.includes(activeModeRef.current)) return;
    getPlayer().interrupt();
  }, []);

  const {
    connected,
    connecting,
    transcript,
    toolActivity,
    connect,
    disconnect,
    sendAudio,
    sendImage,
    sendText,
  } = useRealtime(handleAudioChunk, handleAudioEnd, handleAudioInterrupted);

  const sendAudioRef = useRef(sendAudio);
  sendAudioRef.current = sendAudio;

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: { models: ModelInfo[]; default: string }) => {
        setModels(data.models);
        setSelectedModel(data.default);
      })
      .catch(() => {});
  }, []);

  const handleConnect = useCallback(() => {
    connect(activeMode, activeMode, selectedModel || undefined);
  }, [connect, activeMode, selectedModel]);

  const handleDisconnect = useCallback(() => {
    if (captureRef.current?.isRecording()) {
      captureRef.current.stop();
      setRecording(false);
    }
    setAiSpeaking(false);
    getPlayer().interrupt();
    disconnect();
  }, [disconnect]);

  const handleToggleMic = useCallback(() => {
    if (captureRef.current?.isRecording()) {
      captureRef.current.stop();
      captureRef.current = null;
      setRecording(false);
    } else {
      const capture = createAudioCapture((samples) => {
        sendAudioRef.current(samples);
      });
      captureRef.current = capture;
      capture.start().then(
        () => setRecording(true),
        (err) => {
          console.error("Mic capture failed:", err);
          captureRef.current = null;
        }
      );
    }
  }, []);

  const handleSendImage = useCallback(
    (dataUrl: string, text?: string) => {
      setLastImage(dataUrl);
      sendImage(dataUrl, text);
    },
    [sendImage]
  );

  const handleSendText = useCallback(
    (text: string) => {
      sendText(text);
    },
    [sendText]
  );

  const handleModeChange = useCallback(
    (mode: string) => {
      if (connected) {
        if (captureRef.current?.isRecording()) {
          captureRef.current.stop();
          captureRef.current = null;
          setRecording(false);
        }
        setAiSpeaking(false);
        setLastImage(null);
        getPlayer().interrupt();
        disconnect();
        setActiveMode(mode);
        setTimeout(() => connect(mode, mode, selectedModel || undefined), 300);
      } else {
        setActiveMode(mode);
        setLastImage(null);
      }
    },
    [connected, disconnect, connect, selectedModel]
  );

  const showLanding = !connected && !connecting;
  const showOrb = orbModes.includes(activeMode);
  const showVisionPreview = visionModes.includes(activeMode) && !!lastImage;
  const transcriptVariant: "default" | "document" =
    activeMode === "transcription" ? "document" : "default";
  const orbState: "idle" | "listening" | "speaking" =
    aiSpeaking ? "speaking" : recording ? "listening" : "idle";

  return (
    <div className="app">
      <Navbar />
      <main
        className={`app-main${!showLanding ? ` app-main--session app-main--${activeMode}` : ""}`}
      >
        {showLanding && (
          <>
            <HeroText />
            <ModalityMatrix
              activeMode={activeMode}
              onModeChange={handleModeChange}
            />
          </>
        )}
        {!showLanding && (
          <div className="session-content">
            <StatusBar
              connected={connected}
              connecting={connecting}
              recording={recording}
              toolActivity={toolActivity}
              activeMode={activeMode}
            />

            {showOrb && <AudioOrb state={orbState} />}

            {showVisionPreview && (
              <div className="vision-preview">
                <img src={lastImage!} alt="Sent image" />
              </div>
            )}

            <Transcript
              entries={transcript}
              variant={transcriptVariant}
              compact={showOrb || showVisionPreview}
            />
          </div>
        )}
        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          connected={connected}
          recording={recording}
          activeMode={activeMode}
          models={models}
          selectedModel={selectedModel}
          onModelChange={setSelectedModel}
          onConnect={handleConnect}
          onDisconnect={handleDisconnect}
          onToggleMic={handleToggleMic}
          onSendImage={handleSendImage}
          onSendText={handleSendText}
        />
      </main>
    </div>
  );
}
