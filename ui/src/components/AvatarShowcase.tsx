import { KIND_LABEL, type ShowcaseState } from '../hooks/useAvatarShowcase';

/**
 * "Preview all moves" control for the avatar stage (non-kiosk editor). Thin
 * presentational wrapper over {@link useAvatarShowcase}: shows a trigger
 * button when idle, and a live status card (current move + progress + Stop)
 * while running. The sequencing logic lives in the hook so kiosk mode can
 * reuse it with a different layout.
 */
export function AvatarShowcase({ current, start, stop }: ShowcaseState) {
  return (
    <div className="showcase">
      {!current ? (
        <button
          type="button"
          className="showcase-btn"
          onClick={start}
          title="Preview every mood, gesture, and pose this avatar can do"
        >
          ▶ Preview all moves
        </button>
      ) : (
        <div className="showcase-running" role="status" aria-live="polite">
          <div className="showcase-now">
            <span className="showcase-kind">{KIND_LABEL[current.step.kind]}</span>
            <span className="showcase-value">{current.label}</span>
          </div>
          <div className="showcase-meta">
            <span className="showcase-count">{current.index} / {current.total}</span>
            <button type="button" className="showcase-stop" onClick={stop}>Stop</button>
          </div>
        </div>
      )}
    </div>
  );
}
