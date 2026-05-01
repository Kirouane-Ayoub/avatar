import { useEffect, useId, useRef, useState } from 'react';

interface Props {
  open: boolean;
  title: string;
  description?: string;
  // When present, shows a "type this exact string to confirm" field.
  // Comparison is case-insensitive + trim. Typo-proof guard against
  // accidental destructive actions.
  confirmPhrase?: string;
  confirmPhraseLabel?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'danger' | 'default';
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

/**
 * Modal confirmation dialog. Replaces native window.confirm/prompt for
 * destructive actions. Backdrop click + Escape cancel; when a
 * confirmPhrase is supplied the Confirm button stays disabled until the
 * user types it back exactly.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmPhrase,
  confirmPhraseLabel,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  tone = 'default',
  busy = false,
  onConfirm,
  onCancel,
}: Props) {
  const [typed, setTyped] = useState('');
  const titleId = useId();
  const descId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    setTyped('');
    const t = window.setTimeout(() => {
      (inputRef.current ?? confirmRef.current)?.focus();
    }, 30);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener('keydown', onKey);
    };
  }, [open, busy, onCancel]);

  if (!open) return null;

  const phraseOk =
    !confirmPhrase ||
    typed.trim().toLowerCase() === confirmPhrase.toLowerCase();
  const canConfirm = phraseOk && !busy;

  return (
    <div
      className="cd-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onCancel();
      }}
    >
      <div className={`cd-card${tone === 'danger' ? ' cd-danger' : ''}`}>
        <div className="cd-icon" aria-hidden>
          {tone === 'danger' ? <WarnGlyph /> : <InfoGlyph />}
        </div>
        <h2 className="cd-title" id={titleId}>{title}</h2>
        {description && (
          <p className="cd-desc" id={descId}>{description}</p>
        )}

        {confirmPhrase && (
          <label className="cd-field">
            <span>
              {confirmPhraseLabel ?? 'Type to confirm'}{' '}
              <code>{confirmPhrase}</code>
            </span>
            <input
              ref={inputRef}
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canConfirm) {
                  e.preventDefault();
                  onConfirm();
                }
              }}
              placeholder={confirmPhrase}
            />
          </label>
        )}

        <div className="cd-actions">
          <button
            type="button"
            className="cd-btn cd-cancel"
            onClick={onCancel}
            disabled={busy}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`cd-btn cd-confirm${tone === 'danger' ? ' cd-confirm-danger' : ''}`}
            onClick={onConfirm}
            disabled={!canConfirm}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function WarnGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden>
      <path
        d="M12 3 L22 20 H2 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M12 10 V14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="17" r="1" fill="currentColor" />
    </svg>
  );
}

function InfoGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden>
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 11 V17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="8" r="1" fill="currentColor" />
    </svg>
  );
}
