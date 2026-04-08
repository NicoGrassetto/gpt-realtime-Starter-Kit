/**
 * React hook for managing WebSocket connection to the FastAPI backend.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface ServerEvent {
  type: string;
  [key: string]: unknown;
}

export interface TranscriptEntry {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  timestamp: number;
}

export interface ToolActivity {
  tool: string;
  status: "running" | "done";
  output?: string;
}

export interface UseRealtimeReturn {
  connected: boolean;
  connecting: boolean;
  transcript: TranscriptEntry[];
  toolActivity: ToolActivity | null;
  connect: (mode: string, prompt?: string, model?: string) => void;
  disconnect: () => void;
  sendAudio: (samples: number[]) => void;
  sendImage: (dataUrl: string, text?: string) => void;
  sendCommitAudio: () => void;
  sendInterrupt: () => void;
  sendText: (text: string) => void;
}

let nextId = 1;

export function useRealtime(
  onAudioChunk?: (base64: string) => void,
  onAudioEnd?: () => void,
  onAudioInterrupted?: () => void
): UseRealtimeReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [toolActivity, setToolActivity] = useState<ToolActivity | null>(null);
  const sessionIdRef = useRef<string>("");

  // Stable refs for callbacks
  const onAudioChunkRef = useRef(onAudioChunk);
  onAudioChunkRef.current = onAudioChunk;
  const onAudioEndRef = useRef(onAudioEnd);
  onAudioEndRef.current = onAudioEnd;
  const onAudioInterruptedRef = useRef(onAudioInterrupted);
  onAudioInterruptedRef.current = onAudioInterrupted;

  // Extract text from a single history item's content parts
  const extractText = useCallback(
    (content: Array<Record<string, unknown>>): string => {
      let text = "";
      for (const part of content) {
        if (part.type === "text" && typeof part.text === "string") {
          text += part.text;
        } else if (
          part.type === "audio" &&
          typeof part.transcript === "string"
        ) {
          text += part.transcript;
        } else if (
          part.type === "input_text" &&
          typeof part.text === "string"
        ) {
          text += part.text;
        } else if (
          part.type === "input_audio" &&
          typeof part.transcript === "string"
        ) {
          text += part.transcript;
        }
      }
      return text.trim();
    },
    []
  );

  const handleMessage = useCallback((data: ServerEvent) => {
    switch (data.type) {
      case "audio":
        onAudioChunkRef.current?.(data.audio as string);
        break;

      case "audio_end":
        onAudioEndRef.current?.();
        break;

      case "audio_interrupted":
        onAudioInterruptedRef.current?.();
        break;

      case "history_updated": {
        // Full history replacement — rebuild transcript from all items
        const history = data.history as Array<Record<string, unknown>> | undefined;
        if (!history || !Array.isArray(history)) break;

        const entries: TranscriptEntry[] = [];
        for (const item of history) {
          const role = item.role as string;
          const content = item.content as Array<Record<string, unknown>> | undefined;
          if (!content || !Array.isArray(content)) continue;
          const text = extractText(content);
          if (text) {
            entries.push({
              id: String(nextId++),
              role: role === "assistant" ? "assistant" : "user",
              text,
              timestamp: Date.now(),
            });
          }
        }
        if (entries.length > 0) {
          setTranscript(entries);
        }
        break;
      }

      case "history_added": {
        const item = data.item as Record<string, unknown> | null;
        if (!item) break;
        const role = item.role as string;
        const content = item.content as
          | Array<Record<string, unknown>>
          | undefined;
        if (!content || !Array.isArray(content)) break;
        const text = extractText(content);
        if (text) {
          setTranscript((prev) => [
            ...prev,
            {
              id: String(nextId++),
              role: role === "assistant" ? "assistant" : "user",
              text,
              timestamp: Date.now(),
            },
          ]);
        }
        break;
      }

      case "tool_start":
        setToolActivity({
          tool: data.tool as string,
          status: "running",
        });
        break;

      case "tool_end":
        setToolActivity({
          tool: data.tool as string,
          status: "done",
          output: data.output as string,
        });
        // Clear after a short delay
        setTimeout(() => setToolActivity(null), 2000);
        break;

      case "error":
        setTranscript((prev) => [
          ...prev,
          {
            id: String(nextId++),
            role: "system",
            text: `Error: ${data.error}`,
            timestamp: Date.now(),
          },
        ]);
        break;
    }
  }, [extractText]);

  const connect = useCallback(
    (mode: string, prompt = "default", model?: string) => {
      // Disconnect existing
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      setConnecting(true);
      setTranscript([]);
      setToolActivity(null);

      const sid = `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      sessionIdRef.current = sid;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      let url = `${protocol}//${host}/ws/${sid}?mode=${encodeURIComponent(mode)}&prompt=${encodeURIComponent(prompt)}`;
      if (model) {
        url += `&model=${encodeURIComponent(model)}`;
      }

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setConnecting(false);
      };

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data as string) as ServerEvent;
          handleMessage(event);
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        setConnected(false);
        setConnecting(false);
      };

      ws.onerror = (e) => {
        console.error("WebSocket error:", e);
        setConnected(false);
        setConnecting(false);
        setTranscript((prev) => [
          ...prev,
          {
            id: String(nextId++),
            role: "system",
            text: "Connection failed. Is the backend running on port 8000?",
            timestamp: Date.now(),
          },
        ]);
      };
    },
    [handleMessage]
  );

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  const sendAudio = useCallback((samples: number[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "audio", data: samples }));
    }
  }, []);

  const sendImage = useCallback((dataUrl: string, text?: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ type: "image", data_url: dataUrl, text })
      );
    }
  }, []);

  const sendCommitAudio = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "commit_audio" }));
    }
  }, []);

  const sendInterrupt = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "interrupt" }));
    }
  }, []);

  const sendText = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "text", text }));
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  return {
    connected,
    connecting,
    transcript,
    toolActivity,
    connect,
    disconnect,
    sendAudio,
    sendImage,
    sendCommitAudio,
    sendInterrupt,
    sendText,
  };
}
