import { useEffect, useRef, useState } from 'react';
import {
  Room,
  RoomEvent,
  Track,
  type Participant,
  type RemoteTrack,
  type TranscriptionSegment,
} from 'livekit-client';

export interface LipsyncData {
  words: string[];
  wtimes: number[];
  wdurations: number[];
}

export type CueType = 'mood' | 'gesture' | 'pose';

export type MetricKey = 'stt' | 'llm' | 'tts' | 'e2e';

export interface TranscriptSegment {
  id: string;
  role: 'user' | 'agent';
  text: string;
  final: boolean;
}

export type SessionStatus = 'idle' | 'connecting' | 'connected' | 'error';

export interface SessionArgs {
  url: string;
  token: string;
  micId: string | null;
  camId: string | null;
  cameraWanted: boolean;
}

export interface SessionHandlers {
  onLipsync?: (data: LipsyncData) => void;
  onCue?: (type: CueType, value: string) => void;
  onAgentText?: (text: string, final: boolean) => void;
}

export interface SessionState {
  status: SessionStatus;
  error: string | null;
  transcripts: TranscriptSegment[];
  metrics: Partial<Record<MetricKey, number>>;
  remoteAudio: MediaStream | null;
  cameraPreview: MediaStream | null;
  micMuted: boolean;
  setMicMuted: (muted: boolean) => void;
  cameraOn: boolean;
  setCameraOn: (on: boolean) => Promise<void>;
  disconnect: () => void;
}

const CUE_TAG_RE = /\[\s*(mood|gesture|pose)\s*:\s*[a-zA-Z_]+\s*\]\s*/gi;

export function useSession(
  args: SessionArgs | null,
  handlers: SessionHandlers,
): SessionState {
  const [status, setStatus] = useState<SessionStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<TranscriptSegment[]>([]);
  const [metrics, setMetrics] = useState<Partial<Record<MetricKey, number>>>({});
  const [remoteAudio, setRemoteAudio] = useState<MediaStream | null>(null);
  const [cameraPreview, setCameraPreview] = useState<MediaStream | null>(null);
  const [micMuted, setMicMutedState] = useState(false);
  const [cameraOn, setCameraOnState] = useState(false);

  const roomRef = useRef<Room | null>(null);
  const camIdRef = useRef<string | null>(null);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const disconnect = () => {
    const room = roomRef.current;
    if (!room) return;
    roomRef.current = null;
    try { room.disconnect(); } catch { /* ignore */ }
  };

  const setMicMuted = (muted: boolean) => {
    const room = roomRef.current;
    if (!room) return;
    const pub = room.localParticipant.getTrackPublication(Track.Source.Microphone);
    if (!pub) return;
    if (muted) pub.mute();
    else pub.unmute();
    setMicMutedState(muted);
  };

  const setCameraOn = async (on: boolean) => {
    const room = roomRef.current;
    if (!room) return;
    try {
      if (on) {
        await room.localParticipant.setCameraEnabled(true, {
          deviceId: camIdRef.current ? { exact: camIdRef.current } : undefined,
        });
        const pub = room.localParticipant.getTrackPublication(Track.Source.Camera);
        if (pub?.track) {
          setCameraPreview(new MediaStream([pub.track.mediaStreamTrack]));
        }
        setCameraOnState(true);
      } else {
        await room.localParticipant.setCameraEnabled(false);
        setCameraPreview(null);
        setCameraOnState(false);
      }
    } catch (e) {
      console.warn('camera toggle failed:', e);
    }
  };

  useEffect(() => {
    if (!args) return;

    let cancelled = false;
    const room = new Room({
      audioCaptureDefaults: { autoGainControl: true, noiseSuppression: true },
    });
    roomRef.current = room;
    setStatus('connecting');
    setError(null);
    setTranscripts([]);
    setMetrics({});
    setRemoteAudio(null);
    setCameraPreview(null);
    setMicMutedState(false);
    setCameraOnState(false);
    camIdRef.current = args.camId;

    const attachedEls: HTMLMediaElement[] = [];

    const handleTrackSubscribed = (track: RemoteTrack) => {
      if (track.kind === Track.Kind.Audio) {
        const el = track.attach();
        el.style.display = 'none';
        document.body.appendChild(el);
        attachedEls.push(el);
        setRemoteAudio(new MediaStream([track.mediaStreamTrack]));
      }
    };

    const handleTrackUnsubscribed = (track: RemoteTrack) => {
      track.detach().forEach((el) => el.remove());
    };

    const handleData = (
      payload: Uint8Array,
      _p?: Participant,
      _k?: unknown,
      topic?: string,
    ) => {
      if (topic !== 'metrics') return;
      try {
        const d = JSON.parse(new TextDecoder().decode(payload));
        switch (d.type) {
          case 'stt':
            if (typeof d.duration_ms === 'number')
              setMetrics((m) => ({ ...m, stt: d.duration_ms }));
            break;
          case 'tts':
            if (typeof d.ttfb_ms === 'number')
              setMetrics((m) => ({ ...m, tts: d.ttfb_ms }));
            break;
          case 'lipsync':
            handlersRef.current.onLipsync?.(d as LipsyncData);
            break;
          case 'mood':
          case 'gesture':
          case 'pose':
            if (d.value) handlersRef.current.onCue?.(d.type, d.value);
            break;
          case 'pipeline':
            setMetrics((m) => ({
              ...m,
              ...(typeof d.llm_ttft_ms === 'number' && { llm: d.llm_ttft_ms }),
              ...(typeof d.tts_ttfb_ms === 'number' && { tts: d.tts_ttfb_ms }),
              ...(typeof d.e2e_ms === 'number' && { e2e: d.e2e_ms }),
              ...(typeof d.transcription_ms === 'number' && {
                stt: d.transcription_ms,
              }),
            }));
            break;
        }
      } catch { /* ignore malformed payloads */ }
    };

    const handleTranscription = (
      segments: TranscriptionSegment[],
      participant?: Participant,
    ) => {
      const isAgent = participant?.identity !== 'user';
      const role: 'user' | 'agent' = isAgent ? 'agent' : 'user';
      setTranscripts((prev) => {
        const next = [...prev];
        for (const seg of segments) {
          if (!seg.text) continue;
          const cleanText = isAgent ? seg.text.replace(CUE_TAG_RE, '') : seg.text;
          if (isAgent) handlersRef.current.onAgentText?.(cleanText, seg.final);
          const idx = next.findIndex((t) => t.id === seg.id);
          if (idx === -1) {
            next.push({ id: seg.id, role, text: cleanText, final: seg.final });
          } else {
            next[idx] = { ...next[idx], text: cleanText, final: seg.final };
          }
        }
        return next;
      });
    };

    const handleDisconnected = () => {
      if (cancelled) return;
      setStatus('idle');
      setRemoteAudio(null);
      setCameraPreview(null);
    };

    room.on(RoomEvent.TrackSubscribed, handleTrackSubscribed);
    room.on(RoomEvent.TrackUnsubscribed, handleTrackUnsubscribed);
    room.on(RoomEvent.DataReceived, handleData);
    room.on(RoomEvent.TranscriptionReceived, handleTranscription);
    room.on(RoomEvent.Disconnected, handleDisconnected);

    (async () => {
      try {
        await room.connect(args.url, args.token);
        if (cancelled) return;
        await room.localParticipant.setMicrophoneEnabled(true, {
          deviceId: args.micId ? { exact: args.micId } : undefined,
        });
        if (args.cameraWanted) {
          await room.localParticipant.setCameraEnabled(true, {
            deviceId: args.camId ? { exact: args.camId } : undefined,
          });
          const pub = room.localParticipant.getTrackPublication(Track.Source.Camera);
          if (pub?.track) {
            setCameraPreview(new MediaStream([pub.track.mediaStreamTrack]));
          }
          setCameraOnState(true);
        }
        if (!cancelled) setStatus('connected');
      } catch (e) {
        if (!cancelled) {
          setError((e as Error).message || 'Connection failed');
          setStatus('error');
        }
      }
    })();

    return () => {
      cancelled = true;
      try { room.disconnect(); } catch { /* ignore */ }
      attachedEls.forEach((el) => el.remove());
      roomRef.current = null;
    };
  }, [args]);

  return {
    status,
    error,
    transcripts,
    metrics,
    remoteAudio,
    cameraPreview,
    micMuted,
    setMicMuted,
    cameraOn,
    setCameraOn,
    disconnect,
  };
}
