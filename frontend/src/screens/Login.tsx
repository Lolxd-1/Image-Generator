/// screens/Login.tsx — credential login, then (per the task brief covering
/// SPEC.md §6 auth routes) a second step to add/replace the signed-in user's
/// own Gemini API key before entering the app.
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  useDeleteGeminiKey,
  useLogin,
  useMe,
  useSetGeminiKey,
} from "../api/hooks";
import { Button } from "../components/Button";
import { Card, CardHeader, CardTitle } from "../components/Card";
import { Input } from "../components/Input";
import { Spinner } from "../components/Spinner";

export default function Login() {
  const { data: me, isLoading: meLoading } = useMe();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const login = useLogin();

  const [geminiKey, setGeminiKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const setKey = useSetGeminiKey();
  const deleteKey = useDeleteGeminiKey();

  async function onLoginSubmit(e: FormEvent) {
    e.preventDefault();
    setLoginError(null);
    try {
      await login.mutateAsync({ username, password });
    } catch (err) {
      setLoginError(err instanceof ApiError ? err.message : "Could not sign in.");
    }
  }

  async function onKeySubmit(e: FormEvent) {
    e.preventDefault();
    setKeyError(null);
    try {
      await setKey.mutateAsync({ key: geminiKey });
      setGeminiKey("");
      setReplacing(false);
    } catch (err) {
      setKeyError(err instanceof ApiError ? err.message : "Could not save that key.");
    }
  }

  async function onRemoveKey() {
    const count = me?.key_count ?? 0;
    if (!window.confirm(`Remove all ${count} Gemini key(s)? This cannot be undone.`)) return;
    await deleteKey.mutateAsync();
  }

  if (meLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-base-950">
        <Spinner size={24} />
      </div>
    );
  }

  const authenticated = Boolean(me);

  return (
    <div className="flex min-h-screen items-center justify-center bg-base-950 px-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-center text-lg font-semibold text-base-100">
          Menu Catalog Automation
        </h1>

        {!authenticated ? (
          <Card>
            <CardHeader>
              <CardTitle>Sign in</CardTitle>
            </CardHeader>
            <form className="flex flex-col gap-3" onSubmit={onLoginSubmit}>
              <Input
                label="Username"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
              <Input
                label="Password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              {loginError && <p className="text-xs text-danger-400">{loginError}</p>}
              <Button type="submit" loading={login.isPending} className="mt-1">
                Sign in
              </Button>
            </form>
          </Card>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Your Gemini API key</CardTitle>
            </CardHeader>

            {me?.has_gemini_key && !replacing ? (
              <div className="flex flex-col gap-3">
                <p className="text-xs text-base-400">
                  Key on file, ending in{" "}
                  <span className="font-mono text-base-200">
                    {me.gemini_key_hint ?? "····"}
                  </span>
                  .
                </p>
                <div className="flex gap-2">
                  <Button variant="secondary" size="sm" onClick={() => setReplacing(true)}>
                    Replace key
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    loading={deleteKey.isPending}
                    onClick={onRemoveKey}
                  >
                    Remove all keys
                  </Button>
                </div>
                <Link to="/settings" className="text-xs text-base-400 hover:underline">
                  Manage the key pool in Settings
                </Link>
                <Button className="mt-2" onClick={() => navigate("/")}>
                  Continue
                </Button>
              </div>
            ) : (
              <form className="flex flex-col gap-3" onSubmit={onKeySubmit}>
                <p className="text-xs leading-relaxed text-base-400">
                  This key is yours: it is stored encrypted, every job you run
                  uses your own Gemini quota, and you can remove it at any
                  time. Express-mode keys start with{" "}
                  <span className="font-mono text-base-300">AQ.</span>.
                </p>
                <Input
                  label="Gemini API key"
                  name="geminiKey"
                  type="password"
                  placeholder="AQ...."
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  required
                />
                {keyError && <p className="text-xs text-danger-400">{keyError}</p>}
                <div className="flex gap-2">
                  <Button type="submit" loading={setKey.isPending} disabled={!geminiKey.trim()}>
                    Save key
                  </Button>
                  {me?.has_gemini_key && (
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        setReplacing(false);
                        setKeyError(null);
                      }}
                    >
                      Cancel
                    </Button>
                  )}
                  <Button type="button" variant="ghost" onClick={() => navigate("/")}>
                    Skip for now
                  </Button>
                </div>
              </form>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
