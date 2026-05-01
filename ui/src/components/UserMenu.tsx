import { useEffect, useRef, useState } from 'react';

interface Props {
  username: string;
  // All actions optional so the menu reuses cleanly across screens that
  // don't expose every action (e.g. AvatarPickerScreen has no "Switch"
  // — you're already on the picker).
  onSwitch?: () => void;
  onLogout?: () => void | Promise<void>;
  onDeleteAccount?: () => void | Promise<void>;
}

/**
 * Account dropdown — round monogram + @username trigger; menu opens
 * with icon-led actions on click. Closes on outside-click or Escape.
 *
 * Visual: glass-morphism panel, 16px corners, multi-layer shadow,
 * tight icon+label rows. Destructive action visually separated.
 */
export function UserMenu({ username, onSwitch, onLogout, onDeleteAccount }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const click = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', click);
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('mousedown', click);
      document.removeEventListener('keydown', key);
    };
  }, [open]);

  const close = () => setOpen(false);
  const handleDelete = async () => { close(); if (onDeleteAccount) await onDeleteAccount(); };

  const monogram = (username[0] || '?').toUpperCase();

  return (
    <div className="user-menu" ref={wrapRef}>
      <button
        type="button"
        className={`user-menu-trigger ${open ? 'open' : ''}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="user-menu-monogram">{monogram}</span>
        <span className="user-menu-username">@{username}</span>
        <ChevronDown />
      </button>

      {open && (
        <div className="user-menu-pop" role="menu">
          {onSwitch && (
            <button
              type="button"
              role="menuitem"
              className="user-menu-item"
              onClick={() => { close(); onSwitch(); }}
            >
              <SwitchIcon /> <span>Switch companion</span>
            </button>
          )}
          {onLogout && (
            <button
              type="button"
              role="menuitem"
              className="user-menu-item"
              onClick={() => { close(); void onLogout(); }}
            >
              <SignOutIcon /> <span>Sign out</span>
            </button>
          )}
          {onDeleteAccount && (
            <>
              <div className="user-menu-sep" role="separator" />
              <button
                type="button"
                role="menuitem"
                className="user-menu-item user-menu-item-danger"
                onClick={() => { void handleDelete(); }}
              >
                <TrashIcon /> <span>Delete account</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Inline icons (Lucide-style: 16px, 1.6 stroke, round caps). Kept inline
// rather than in components/icons.tsx to keep the menu self-contained.
function ChevronDown() {
  return (
    <svg className="user-menu-caret" width="14" height="14" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
function SwitchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 3l4 4-4 4" /><path d="M20 7H8a4 4 0 0 0-4 4" />
      <path d="M8 21l-4-4 4-4" /><path d="M4 17h12a4 4 0 0 0 4-4" />
    </svg>
  );
}
function SignOutIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}
function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" /><path d="M14 11v6" />
      <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  );
}
