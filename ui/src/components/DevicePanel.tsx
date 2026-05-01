import { useEffect, useRef, useState } from 'react';
import { CamIcon, MicIcon } from './icons';

interface Props {
  cameraOn: boolean;
  onCameraChange: (on: boolean) => void;
  micId: string;
  onMicChange: (id: string) => void;
  camId: string;
  onCamChange: (id: string) => void;
}

export function DevicePanel({
  cameraOn, onCameraChange, micId, onMicChange, camId, onCamChange,
}: Props) {
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [cams, setCams] = useState<MediaDeviceInfo[]>([]);
  const [previewStream, setPreviewStream] = useState<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
        s.getTracks().forEach((t) => t.stop());
      } catch {
        try {
          const s = await navigator.mediaDevices.getUserMedia({ audio: true });
          s.getTracks().forEach((t) => t.stop());
        } catch {
          // both denied
        }
      }
      if (cancelled) return;
      const list = await navigator.mediaDevices.enumerateDevices();
      setMics(list.filter((d) => d.kind === 'audioinput'));
      setCams(list.filter((d) => d.kind === 'videoinput'));
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!cameraOn) {
      previewStream?.getTracks().forEach((t) => t.stop());
      setPreviewStream(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: camId ? { deviceId: { exact: camId } } : true,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        setPreviewStream((prev) => {
          prev?.getTracks().forEach((t) => t.stop());
          return stream;
        });
      } catch {
        if (!cancelled) onCameraChange(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cameraOn, camId, onCameraChange]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = previewStream;
  }, [previewStream]);

  useEffect(() => {
    return () => {
      previewStream?.getTracks().forEach((t) => t.stop());
    };
  }, [previewStream]);

  return (
    <>
      <div className="stage-devices">
        <label className="sd-item">
          <span className="sd-icon"><MicIcon /></span>
          <select
            value={micId}
            onChange={(e) => onMicChange(e.target.value)}
            aria-label="Microphone"
          >
            {mics.length === 0 && <option value="">(no input)</option>}
            {mics.map((m, i) => (
              <option key={m.deviceId || i} value={m.deviceId}>
                {m.label || `Microphone ${i + 1}`}
              </option>
            ))}
          </select>
        </label>

        <label className={`sd-item${cameraOn ? ' on' : ''}`}>
          <span className="sd-icon"><CamIcon off={!cameraOn} /></span>
          <button
            type="button"
            className={`sd-pill${cameraOn ? ' on' : ''}`}
            onClick={() => onCameraChange(!cameraOn)}
            aria-pressed={cameraOn}
          >
            {cameraOn ? 'On' : 'Off'}
          </button>
          <select
            value={camId}
            onChange={(e) => onCamChange(e.target.value)}
            disabled={!cameraOn}
            aria-label="Camera"
          >
            {cams.length === 0 && <option value="">(no camera)</option>}
            {cams.map((c, i) => (
              <option key={c.deviceId || i} value={c.deviceId}>
                {c.label || `Camera ${i + 1}`}
              </option>
            ))}
          </select>
        </label>
      </div>

      {cameraOn && (
        <div className="stage-cam-bubble">
          <video ref={videoRef} autoPlay muted playsInline />
          {/* Overlays — small, low-contrast so they don't fight the
              avatar canvas behind them. The "live" dot pulses to make
              it obvious this is real-time, not a thumbnail. */}
          <span className="stage-cam-live" aria-hidden>
            <span className="stage-cam-live-dot" />
            <span className="stage-cam-live-text">live</span>
          </span>
          <span className="stage-cam-label">you</span>
        </div>
      )}
    </>
  );
}
