import { useState, type FormEvent } from 'react';
import type { AuthState } from '../hooks/useAuth';

type Mode = 'login' | 'signup';

interface Props {
  auth: AuthState;
}

/**
 * Minimal login + signup form. Toggles between the two modes with a link.
 *
 * Uses useAuth's `signup` / `login` directly — they update auth state
 * on success, which makes App.tsx unmount this and render the wizard.
 */
export function LoginScreen({ auth }: Props) {
  const [mode, setMode] = useState<Mode>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    setSubmitting(true);
    try {
      // Display name defaults to the username server-side (auth.signup
      // in src/auth.py); user can edit it later in the wizard.
      if (mode === 'signup') {
        await auth.signup(username.trim(), password);
      } else {
        await auth.login(username.trim(), password);
      }
      // Success — useAuth updates state, App swaps us out for the wizard.
    } catch (e) {
      setLocalError((e as Error).message || 'Something went wrong');
    } finally {
      setSubmitting(false);
    }
  };

  const swap = () => {
    setMode((m) => (m === 'login' ? 'signup' : 'login'));
    setLocalError(null);
  };

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <h1 className="login-title">{mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
        <p className="login-sub">
          {mode === 'login'
            ? 'Sign in to talk to your avatar.'
            : 'A username and password is all you need.'}
        </p>

        <label className="login-field">
          <span>Username</span>
          <input
            type="text"
            autoComplete="username"
            autoFocus
            required
            minLength={3}
            maxLength={32}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="lowercase, no spaces"
          />
        </label>

        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === 'signup' ? 'at least 8 characters' : ''}
          />
        </label>

        {localError && <div className="login-error">{localError}</div>}

        <button type="submit" className="login-submit" disabled={submitting}>
          {submitting ? '…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>

        <div className="login-swap">
          {mode === 'login' ? "Don't have an account?" : 'Already have an account?'}{' '}
          <button type="button" className="link" onClick={swap}>
            {mode === 'login' ? 'Sign up' : 'Sign in'}
          </button>
        </div>
      </form>
    </div>
  );
}
