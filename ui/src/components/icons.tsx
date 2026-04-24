export function MicIcon({ muted = false, size = 14 }: { muted?: boolean; size?: number }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} aria-hidden>
      <rect x="6" y="2" width="4" height="7" rx="2" fill="currentColor" />
      <path
        d="M4 8 V9 a4 4 0 0 0 8 0 V8 M8 13 V15 M5.5 15 H10.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      {muted && (
        <line
          x1="2.5" y1="2.5" x2="13.5" y2="13.5"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      )}
    </svg>
  );
}

export function CamIcon({ off = false, size = 14 }: { off?: boolean; size?: number }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} aria-hidden>
      <rect x="1.5" y="4" width="9" height="8" rx="1.6" fill="currentColor" />
      <path d="M11 7 L14.5 5 V11 L11 9 Z" fill="currentColor" />
      {off && (
        <line
          x1="2" y1="2.5" x2="14" y2="13.5"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      )}
    </svg>
  );
}
