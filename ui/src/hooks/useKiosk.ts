import { useCallback, useEffect, useState } from 'react';

// Kiosk mode for large-format vertical touch screens (e.g. a 3m portrait
// display). The browser only sees pixels, not physical size — a 3m kiosk and
// a phone can both report 1080×1920 — so kiosk mode is explicit, not
// auto-detected. Enable via the Settings toggle or a `?kiosk=1` URL (handy
// for unattended kiosk setup); the choice persists in localStorage.
//
// When on, the layout goes full-bleed avatar + a floating control dock placed
// in the reachable band (CSS keys off html[data-kiosk="1"]). The reach band
// is nudgeable (--reach-offset) because mounting height varies.

export type KioskView = 'head' | 'upper' | 'full';

const KEY = 'liva-kiosk';
const REACH_KEY = 'liva-kiosk-reach';
const VIEW_KEY = 'liva-kiosk-view';

function readView(): KioskView {
  const v = localStorage.getItem(VIEW_KEY);
  return v === 'head' || v === 'upper' || v === 'full' ? v : 'upper';
}

function readKiosk(): boolean {
  try {
    const q = new URLSearchParams(window.location.search).get('kiosk');
    if (q === '1') return true;
    if (q === '0') return false;
    return localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

function readReach(): number {
  const v = Number(localStorage.getItem(REACH_KEY));
  return Number.isFinite(v) ? Math.min(40, Math.max(-20, v)) : 0;
}

export function useKiosk() {
  const [kiosk, setKioskState] = useState(readKiosk);
  // Vertical nudge of the reach band in vh (− = lower, + = higher).
  const [reach, setReachState] = useState(readReach);
  // Avatar framing on the big screen (head / upper / full body).
  const [view, setViewState] = useState<KioskView>(readView);

  useEffect(() => {
    document.documentElement.dataset.kiosk = kiosk ? '1' : '0';
  }, [kiosk]);

  useEffect(() => {
    document.documentElement.style.setProperty('--reach-offset', `${reach}vh`);
  }, [reach]);

  const setKiosk = useCallback((v: boolean) => {
    localStorage.setItem(KEY, v ? '1' : '0');
    setKioskState(v);
  }, []);

  const nudgeReach = useCallback((delta: number) => {
    setReachState((r) => {
      const next = Math.min(40, Math.max(-20, r + delta));
      localStorage.setItem(REACH_KEY, String(next));
      return next;
    });
  }, []);

  const setView = useCallback((v: KioskView) => {
    localStorage.setItem(VIEW_KEY, v);
    setViewState(v);
  }, []);

  return { kiosk, setKiosk, reach, nudgeReach, view, setView };
}
