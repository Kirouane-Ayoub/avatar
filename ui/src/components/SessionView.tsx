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
import { TOOL_CATALOG } from '../data/tools';

// Friendly verb + emoji per tool — short, action-oriented so the pill
// reads naturally ("Searching the web…" not "Web search running…").
// Falls back to the catalog label for any unknown tool.
const TOOL_VERB: Record<string, { icon: string; verb: string }> = {
  online_search: { icon: '🔎', verb: 'Searching the web' },
  internal_search: { icon: '📚', verb: 'Looking through your docs' },
  set_reminder: { icon: '⏰', verb: 'Setting a reminder' },
};

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
  // Large-format vertical touch screen: full-bleed avatar + a reachable
  // control dock; the transcript becomes a toggleable sheet.
  kiosk?: boolean;
  // Persisted kiosk avatar framing (head / upper / full) — set in the editor.
  kioskView?: 'head' | 'upper' | 'full';
}

const IDLE_GESTURES = ['side', 'index', 'ok'];

const METRIC_THRESHOLDS: Record<MetricKey, [number, number]> = {
  stt: [300, 600],
  llm: [300, 800],
  tts: [200, 500],
  e2e: [800, 1500],
  // memR: a healthy session-start recall is sub-200ms (DB hit + a tiny
  // amount of embedding for search). >500ms means the embedder cold-
  // started or the DB is slow.
  memR: [200, 500],
  // memW: write includes Mem0's async LLM fact extraction (small VLM at
  // :5006). Several seconds is normal — we're cutting an LLM call to
  // distill the turn into a fact. >5s likely means the VLM is queued.
  memW: [2000, 5000],
};

const METRIC_LABEL: Record<MetricKey, string> = {
  stt: 'STT', llm: 'LLM', tts: 'TTS', e2e: 'E2E',
  memR: 'MEM R', memW: 'MEM W',
};

function metricClass(key: MetricKey, val: number) {
  const [good, ok] = METRIC_THRESHOLDS[key];
  if (val <= good) return 'good';
  if (val <= ok) return 'ok';
  return 'slow';
}


export function SessionView({ setup, avatar, connection, onExit, kiosk = false, kioskView = 'upper' }: Props) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [mood, setMood] = useState<Mood>(setup.mood);
  // Kiosk: transcript/text-input sheet open/closed (controls live on the dock).
  const [panelOpen, setPanelOpen] = useState(false);
  const { progress, error: avatarError, head } = useTalkingHead(
    container, avatar, mood, kiosk ? kioskView : 'full',
  );

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
      // Kiosk: keep the operator-chosen framing (full-body reads as a tiny
      // figure on a big vertical screen); otherwise frame to the active cue.
      const view = kiosk ? kioskView : hasPose ? 'full' : hasGesture ? 'upper' : 'head';
      try { head.setView(view); } catch { /* ignore */ }
    }, delay);
  }, [head, kiosk, kioskView]);

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
    <div className={`session${kiosk ? ' kiosk' : ''}${kiosk && panelOpen ? ' panel-open' : ''}`}>
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

        {session.activeTool && (() => {
          const verb = TOOL_VERB[session.activeTool.name];
          const fallback = TOOL_CATALOG.find((t) => t.id === session.activeTool!.name);
          const icon = verb?.icon ?? '⚙️';
          const label = verb?.verb ?? fallback?.label ?? session.activeTool.name;
          return (
            <div className="session-tool" role="status" aria-live="polite">
              <span className="session-tool-icon" aria-hidden>{icon}</span>
              <span className="session-tool-label">{label}</span>
              <span className="session-tool-dots" aria-hidden>
                <i /><i /><i />
              </span>
            </div>
          );
        })()}

        {session.cameraPreview && (
          <div className="session-cam">
            <video ref={camVideoRef} autoPlay muted playsInline />
            {/* Same overlay treatment as the wizard preview — pulsing
                "live" pill + "you" label so the user can read it as
                their own webcam feed at a glance during the call. */}
            <span className="stage-cam-live" aria-hidden>
              <span className="stage-cam-live-dot" />
              <span className="stage-cam-live-text">live</span>
            </span>
            <span className="stage-cam-label">you</span>
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

      {kiosk && (
        <div className="kiosk-dock session-dock" role="toolbar" aria-label="Call controls">
          <button
            type="button"
            className={`kiosk-mic${session.micMuted ? ' off' : ' on'}`}
            onClick={() => session.setMicMuted(!session.micMuted)}
            disabled={session.status !== 'connected'}
            aria-label={session.micMuted ? 'Unmute microphone' : 'Mute microphone'}
          >
            <MicIcon muted={session.micMuted} size={26} />
          </button>
          <button
            type="button"
            className={`kiosk-dock-icon${session.cameraOn ? ' on' : ''}`}
            onClick={() => session.setCameraOn(!session.cameraOn)}
            disabled={session.status !== 'connected'}
            aria-label={session.cameraOn ? 'Turn camera off' : 'Turn camera on'}
          >
            <CamIcon off={!session.cameraOn} size={22} />
          </button>
          <button
            type="button"
            className={`kiosk-dock-pill${session.whisperMode ? ' on' : ''}`}
            onClick={() => session.setWhisperMode(!session.whisperMode)}
            disabled={session.status !== 'connected'}
            aria-pressed={session.whisperMode}
          >
            Whisper
          </button>
          <button
            type="button"
            className="kiosk-dock-pill"
            onClick={() => setPanelOpen((v) => !v)}
            aria-expanded={panelOpen}
          >
            {panelOpen ? 'Close' : 'Transcript'}
          </button>
          <button type="button" className="kiosk-dock-leave" onClick={handleDisconnect}>
            Leave
          </button>
        </div>
      )}
      {kiosk && panelOpen && (
        <div className="kiosk-backdrop" onClick={() => setPanelOpen(false)} aria-hidden />
      )}
    </div>
  );
}
