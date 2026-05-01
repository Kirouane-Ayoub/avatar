import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AvatarMeta, Mood, SessionSetup } from '../types';
import { POSE_SET } from '../data/cues';
import { languageFromVoice } from '../data/voice_lang';
import { useTalkingHead } from '../hooks/useTalkingHead';
import {
  useSession,
  type CueType,
  type LipsyncData,
  type MetricKey,
} from '../hooks/useSession';
import { useLipsyncDriver } from '../hooks/useLipsyncDriver';
import { detectGesture, detectMood } from '../data/detect';
import { CamIcon, MicIcon } from './icons';

export interface ConnectionInfo {
  token: string;
  url: string;
  micId: string | null;
  camId: string | null;
}

interface Props {
  setup: SessionSetup;
  avatar: AvatarMeta;
  connection: ConnectionInfo;
  onExit: () => void;
}

const IDLE_GESTURES = ['side', 'index', 'ok'];

const METRIC_THRESHOLDS: Record<MetricKey, [number, number]> = {
  stt: [300, 600],
  llm: [300, 800],
  tts: [200, 500],
  e2e: [800, 1500],
};

const METRIC_LABEL: Record<MetricKey, string> = {
  stt: 'STT', llm: 'LLM', tts: 'TTS', e2e: 'E2E',
};

function metricClass(key: MetricKey, val: number) {
  const [good, ok] = METRIC_THRESHOLDS[key];
  if (val <= good) return 'good';
  if (val <= ok) return 'ok';
  return 'slow';
}


export function SessionView({ setup, avatar, connection, onExit }: Props) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [mood, setMood] = useState<Mood>(setup.mood);
  const { progress, error: avatarError, head } = useTalkingHead(container, avatar, mood);

  const sessionArgs = useMemo(
    () => ({
      url: connection.url,
      token: connection.token,
      micId: connection.micId,
      camId: connection.camId,
      cameraWanted: setup.camera,
    }),
    [connection, setup.camera],
  );

  const lipsyncQueueRef = useRef<LipsyncData[]>([]);
  const cueArrivedRef = useRef(false);
  const lastAgentTextAtRef = useRef(0);
  const turnCuesRef = useRef({ hasGesture: false, hasPose: false });
  const viewTimerRef = useRef<number | null>(null);

  const scheduleViewUpdate = useCallback(() => {
    if (!head) return;
    if (viewTimerRef.current) window.clearTimeout(viewTimerRef.current);
    // Pose tween is 2000 ms (setPoseFromTemplate). If we re-frame at the
    // 250 ms cue-coalescing mark we frame the still-standing avatar; the
    // pose then drops it out of view (especially sitting/kneel/oneknee).
    // Wait past the tween when a pose is in play.
    const { hasPose } = turnCuesRef.current;
    const delay = hasPose ? 2200 : 250;
    viewTimerRef.current = window.setTimeout(() => {
      const { hasGesture, hasPose } = turnCuesRef.current;
      const view = hasPose ? 'full' : hasGesture ? 'upper' : 'head';
      try { head.setView(view); } catch { /* ignore */ }
    }, delay);
  }, [head]);

  useEffect(() => {
    return () => {
      if (viewTimerRef.current) window.clearTimeout(viewTimerRef.current);
    };
  }, []);

  const handleLipsync = useCallback((data: LipsyncData) => {
    lipsyncQueueRef.current.push(data);
  }, []);

  const handleCue = useCallback(
    (type: CueType, value: string) => {
      console.log('[cue]', type, value, 'head?', !!head);
      if (!head) return;
      cueArrivedRef.current = true;
      try {
        if (type === 'mood') {
          // Mood is the first cue of every reply — treat as turn boundary.
          turnCuesRef.current = { hasGesture: false, hasPose: false };
          setMood(value as Mood);
        } else if (type === 'gesture') {
          turnCuesRef.current.hasGesture = true;
          head.playGesture(value, 3, false, 1000);
        } else if (type === 'pose') {
          if (!POSE_SET.has(value)) return;
          const tpl = head.poseTemplates?.[value];
          if (tpl && head.setPoseFromTemplate) {
            head.setPoseFromTemplate(tpl, 2000);
          }
          turnCuesRef.current.hasPose = true;
        }
      } catch { /* ignore */ }
      scheduleViewUpdate();
    },
    [head, scheduleViewUpdate],
  );

  const handleAgentText = useCallback(
    (text: string, final: boolean) => {
      lastAgentTextAtRef.current = Date.now();
      if (head && !cueArrivedRef.current) {
        const m = detectMood(text);
        if (m) setMood(m as Mood);
        const g = detectGesture(text);
        if (g) {
          try { head.playGesture(g, 3, false, 1000); } catch { /* ignore */ }
        }
      }
      if (final) cueArrivedRef.current = false;
    },
    [head],
  );

  const session = useSession(sessionArgs, {
    onLipsync: handleLipsync,
    onCue: handleCue,
    onAgentText: handleAgentText,
  });

  // Language fully follows the picked voice; defaults to English when no
  // voice was picked. Any avatar pairs with any voice.
  const lipsyncLanguage = languageFromVoice(setup.voice, 'en');

  useLipsyncDriver(
    head,
    session.remoteAudio,
    avatar,
    lipsyncLanguage,
    lipsyncQueueRef,
    session.status === 'connected',
  );

  // Idle micro-gestures so the avatar doesn't feel frozen between turns.
  useEffect(() => {
    if (session.status !== 'connected' || !head) return;
    const id = window.setInterval(() => {
      const silentFor = Date.now() - lastAgentTextAtRef.current;
      if (silentFor < 6000) return;
      if (Math.random() > 0.25) return;
      const g = IDLE_GESTURES[Math.floor(Math.random() * IDLE_GESTURES.length)];
      try { head.playGesture(g, 1.5, false, 800); } catch { /* ignore */ }
    }, 4000);
    return () => window.clearInterval(id);
  }, [session.status, head]);

  // Camera preview mirror.
  const camVideoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (camVideoRef.current) {
      camVideoRef.current.srcObject = session.cameraPreview;
    }
  }, [session.cameraPreview]);

  const [textInput, setTextInput] = useState('');
  const handleSendText = () => {
    const v = textInput.trim();
    if (!v || session.status !== 'connected') return;
    session.sendText(v);
    setTextInput('');
  };

  // Auto-scroll transcript to latest.
  const transcriptRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [session.transcripts]);

  const handleDisconnect = useCallback(() => {
    session.disconnect();
    onExit();
  }, [session, onExit]);

  return (
    <div className="session">
      <div className="session-stage">
        <div ref={setContainer} className="th-stage" />

        {progress !== null && (
          <span className="th-status">Loading {progress}%</span>
        )}
        {avatarError && <span className="th-status error">{avatarError}</span>}

        <div className="session-badge">
          <span className={`session-dot ${session.status}`} />
          {session.status === 'connecting' && 'Connecting…'}
          {session.status === 'connected' &&
            (setup.camera
              ? `${setup.name} can see and hear you`
              : `Speak to ${setup.name}`)}
          {session.status === 'error' && (session.error || 'Connection failed')}
          {session.status === 'idle' && 'Disconnected'}
        </div>

        <div className="session-metrics">
          {(Object.keys(METRIC_LABEL) as MetricKey[]).map((k) => {
            const v = session.metrics[k];
            return (
              <div key={k} className="metric">
                <span className="metric-label">{METRIC_LABEL[k]}</span>
                <span
                  className={`metric-value ${v != null ? metricClass(k, v) : 'idle'}`}
                >
                  {v != null ? `${v}ms` : '—'}
                </span>
              </div>
            );
          })}
        </div>

        {session.cameraPreview && (
          <div className="session-cam">
            <video ref={camVideoRef} autoPlay muted playsInline />
          </div>
        )}

      </div>

      <aside className="session-side">
        <header className="side-header">
          <div className="side-id">
            <div className="side-title">{setup.name}</div>
            <div className="side-sub">{avatar.label}</div>
          </div>
          <div className="side-actions">
            <button
              type="button"
              className={`whisper-pill${session.whisperMode ? ' on' : ''}`}
              onClick={() => session.setWhisperMode(!session.whisperMode)}
              disabled={session.status !== 'connected'}
              title={session.whisperMode
                ? 'Whisper mode on — mic gain ×2.5, suppression off'
                : 'Whisper mode'}
              aria-pressed={session.whisperMode}
            >
              Whisper
            </button>
            <button
              type="button"
              className={`icon-btn${session.micMuted ? ' off' : ' on'}`}
              onClick={() => session.setMicMuted(!session.micMuted)}
              disabled={session.status !== 'connected'}
              aria-label={session.micMuted ? 'Unmute microphone' : 'Mute microphone'}
              title={session.micMuted ? 'Unmute' : 'Mute'}
            >
              <MicIcon muted={session.micMuted} />
            </button>
            <button
              type="button"
              className={`icon-btn${session.cameraOn ? ' on' : ''}`}
              onClick={() => session.setCameraOn(!session.cameraOn)}
              disabled={session.status !== 'connected'}
              aria-label={session.cameraOn ? 'Turn camera off' : 'Turn camera on'}
              title={session.cameraOn ? 'Camera on' : 'Camera off'}
            >
              <CamIcon off={!session.cameraOn} />
            </button>
            <button type="button" className="hangup" onClick={handleDisconnect}>
              Leave
            </button>
          </div>
        </header>

        <div className="transcript" ref={transcriptRef}>
          {session.transcripts.length === 0 && (
            <div className="transcript-empty">
              {session.status === 'connected'
                ? 'Say something — she\'s listening.'
                : 'Waiting for connection…'}
            </div>
          )}
          {session.transcripts.map((t) => (
            <div key={t.id} className={`msg ${t.role}`}>
              <span className="av">
                {t.role === 'user' ? 'U' : setup.name[0].toUpperCase()}
              </span>
              <div className={`bubble${t.final ? '' : ' partial'}`}>{t.text}</div>
            </div>
          ))}
        </div>

        <form
          className="text-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            handleSendText();
          }}
        >
          <input
            type="text"
            className="text-input"
            placeholder="Type a message…"
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            disabled={session.status !== 'connected'}
            maxLength={500}
          />
          <button
            type="submit"
            className="text-send"
            disabled={!textInput.trim() || session.status !== 'connected'}
            aria-label="Send"
          >
            Send
          </button>
        </form>
      </aside>
    </div>
  );
}
