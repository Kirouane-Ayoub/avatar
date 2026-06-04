import { useCallback, useEffect, useState } from 'react';

// Light/dark mode + accent theme, persisted to localStorage and applied as
// data-attributes on <html> (data-theme="light|dark", data-accent="..."),
// which styles.css keys all its color tokens off. An inline boot script in
// index.html applies the same attrs before first paint to avoid a flash;
// this hook keeps them in sync as the user toggles and as the OS theme
// changes (while in "system" mode).

export type ThemeMode = 'light' | 'dark' | 'system';
export type ThemeAccent = 'indigo' | 'teal' | 'emerald' | 'sunset';

const MODE_KEY = 'liva-theme-mode';
const ACCENT_KEY = 'liva-theme-accent';

// Swatch metadata for the picker UI. `from`/`to` are literal hexes so a
// swatch previews its accent regardless of the currently-active theme.
export const ACCENT_OPTIONS: { id: ThemeAccent; label: string; from: string; to: string }[] = [
  { id: 'indigo', label: 'Indigo', from: '#6366f1', to: '#a855f7' },
  { id: 'teal', label: 'Ocean', from: '#0d9488', to: '#06b6d4' },
  { id: 'emerald', label: 'Emerald', from: '#059669', to: '#34d399' },
  { id: 'sunset', label: 'Sunset', from: '#f43f5e', to: '#f59e0b' },
];

const ACCENT_IDS = ACCENT_OPTIONS.map((a) => a.id);

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined'
    && !!window.matchMedia
    && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

export function resolveMode(mode: ThemeMode): 'light' | 'dark' {
  return mode === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : mode;
}

function readMode(): ThemeMode {
  const v = localStorage.getItem(MODE_KEY);
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
}

function readAccent(): ThemeAccent {
  const v = localStorage.getItem(ACCENT_KEY) as ThemeAccent | null;
  return v && ACCENT_IDS.includes(v) ? v : 'indigo';
}

function applyTheme(mode: ThemeMode, accent: ThemeAccent) {
  const root = document.documentElement;
  root.dataset.theme = resolveMode(mode);
  root.dataset.accent = accent;
}

export function useTheme() {
  const [mode, setModeState] = useState<ThemeMode>(readMode);
  const [accent, setAccentState] = useState<ThemeAccent>(readAccent);

  useEffect(() => {
    applyTheme(mode, accent);
  }, [mode, accent]);

  // Track OS theme changes while in "system" mode so the UI flips live.
  useEffect(() => {
    if (mode !== 'system' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => applyTheme('system', accent);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [mode, accent]);

  const setMode = useCallback((m: ThemeMode) => {
    localStorage.setItem(MODE_KEY, m);
    setModeState(m);
  }, []);

  const setAccent = useCallback((a: ThemeAccent) => {
    localStorage.setItem(ACCENT_KEY, a);
    setAccentState(a);
  }, []);

  return { mode, accent, resolved: resolveMode(mode), setMode, setAccent };
}
