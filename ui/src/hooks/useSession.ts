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

export type MetricKey = 'stt' | 'llm' | 'tts' | 'e2e' | 'memR' | 'memW';

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
  whisperMode: boolean;
  setWhisperMode: (on: boolean) => void;
  sendText: (text: string) => void;
  disconnect: () => void;
}

const CUE_TAG_RE = /\[\s*(mood|gesture|pose)\s*:\s*[a-zA-Z_]+\s*\]\s*/gi;
// Orpheus inline vocal emotion tags — rendered as sounds by the TTS, must not
// appear literally in the transcript. Mirrors ORPHEUS_EMOTION_TAGS in agent.py.
const ORPHEUS_EMOTE_RE = /<\s*(laugh|sigh|chuckle|cough|sniffle|groan|yawn|gasp)\s*>\s*/gi;

// Whisper mode multiplies mic gain ~2.5× (≈+8 dB) on top of the browser's
// AGC and disables noiseSuppression (which otherwise filters whispers as
// "noise"). Below ~3.5× the AGC stays clip-safe in normal speech rooms.
const WHISPER_GAIN = 2.5;
const NORMAL_GAIN = 1.0;

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
  const [whisperMode, setWhisperModeState] = useState(false);

  const roomRef = useRef<Room | null>(null);
  const camIdRef = useRef<string | null>(null);
  const rawMicStreamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const disconnect = () => {
    const room = roomRef.current;
    if (!room) return;
    roomRef.current = null;
    try { room.disconnect(); } catch { /* ignore */ }
  };

  const sendText = (text: string) => {
    const room = roomRef.current;
    if (!room) return;
    const trimmed = text.trim();
    if (!trimmed) return;
    const payload = new TextEncoder().encode(JSON.stringify({ text: trimmed }));
    room.localParticipant.publishData(payload, {
      topic: 'user_text',
      reliable: true,
    });
    // Optimistic local user bubble — the agent doesn't echo typed input
    // back as a transcript, so we add it ourselves.
    setTranscripts((prev) => [
      ...prev,
      { id: `text-${Date.now()}`, role: 'user', text: trimmed, final: true },
    ]);
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

  const setWhisperMode = (on: boolean) => {
    setWhisperModeState(on);
    const gain = gainRef.current;
    if (gain) {
      gain.gain.setValueAtTime(
        on ? WHISPER_GAIN : NORMAL_GAIN,
        gain.context.currentTime,
      );
    }
    // Suppression filters whispers as "noise" — flip it off in whisper mode.
    const rawTrack = rawMicStreamRef.current?.getAudioTracks()[0];
    if (rawTrack) {
      rawTrack.applyConstraints({ noiseSuppression: !on }).catch(() => {
        /* not all browsers support runtime constraint changes */
      });
    }
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
    const room = new Room();
    roomRef.current = room;
    setStatus('connecting');
    setError(null);
    setTranscripts([]);
    setMetrics({});
    setRemoteAudio(null);
    setCameraPreview(null);
    setMicMutedState(false);
    setCameraOnState(false);
    setWhisperModeState(false);
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
          case 'memory':
            // Memory metric: { type:"memory", op:"read"|"write", ms:N }
            if (typeof d.ms === 'number') {
              const slot: MetricKey | null =
                d.op === 'read' ? 'memR' : d.op === 'write' ? 'memW' : null;
              if (slot) setMetrics((m) => ({ ...m, [slot]: d.ms }));
            }
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
          const cleanText = isAgent
            ? seg.text.replace(CUE_TAG_RE, '').replace(ORPHEUS_EMOTE_RE, '')
            : seg.text;
          // Skip agent segments that are pure cue/emote tags (e.g. just
          // "[mood:happy][gesture:handup] <laugh>") — they'd render as an
          // empty bubble. Audio + gestures still play; only the transcript
          // entry is suppressed.
          if (isAgent && !cleanText.trim()) continue;
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

        // Mic: get raw stream → WebAudio gain stage → publish processed track.
        // The gain node lets whisper mode multiply mic level live without a
        // republish. AGC stays on (browser-side) for normal-volume normalization;
        // gain is layered on top.
        const rawStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: args.micId ? { exact: args.micId } : undefined,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        if (cancelled) {
          rawStream.getTracks().forEach((t) => t.stop());
          return;
        }
        rawMicStreamRef.current = rawStream;

        const audioCtx = new AudioContext();
        audioCtxRef.current = audioCtx;
        const source = audioCtx.createMediaStreamSource(rawStream);
        const gain = audioCtx.createGain();
        gain.gain.value = NORMAL_GAIN;
        const dest = audioCtx.createMediaStreamDestination();
        source.connect(gain).connect(dest);
        gainRef.current = gain;

        const processedTrack = dest.stream.getAudioTracks()[0];
        await room.localParticipant.publishTrack(processedTrack, {
          source: Track.Source.Microphone,
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
      rawMicStreamRef.current?.getTracks().forEach((t) => t.stop());
      rawMicStreamRef.current = null;
      audioCtxRef.current?.close().catch(() => { /* ignore */ });
      audioCtxRef.current = null;
      gainRef.current = null;
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
    whisperMode,
    setWhisperMode,
    sendText,
    disconnect,
  };
}
