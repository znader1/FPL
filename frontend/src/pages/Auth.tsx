import { useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { AlertCircle, CheckCircle2, Loader2, ArrowLeft } from "lucide-react";

function GoogleButton({ loading, onClick }: { loading: boolean; onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="outline"
      onClick={onClick}
      disabled={loading}
      className="w-full border-white/15 bg-white/[0.06] text-white hover:bg-white/[0.12] h-10"
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <>
          <svg className="h-4 w-4 mr-2 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05" />
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
          </svg>
          Continue with Google
        </>
      )}
    </Button>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive px-3 py-2.5 text-sm mb-4">
      <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
      {message}
    </div>
  );
}

/* ── Login tab ─────────────────────────────────────────────────────────────── */
function LoginForm() {
  const navigate = useNavigate();
  const location = useLocation() as { state?: { from?: string } };
  const destination = location.state?.from ?? "/app";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [resetNotice, setResetNotice] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) setError(error.message);
    else navigate(destination);
  };

  // /auth/confirm already accepts the "recovery" OTP type, so the emailed link
  // completes the round trip and signs the user back in.
  const handleForgot = async () => {
    setError(null);
    setResetNotice(null);
    if (!email) {
      setError("Enter your email address first, then choose Forgot.");
      return;
    }
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/confirm`,
    });
    if (error) setError(error.message);
    else setResetNotice(`Password reset link sent to ${email}.`);
  };

  const handleGoogle = async () => {
    setGoogleLoading(true);
    setError(null);
    // On success the browser navigates away, so this only matters when the
    // call fails (popup blocked, provider misconfigured) — without it the
    // button spins forever with no explanation.
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/app` },
    });
    if (error) {
      setGoogleLoading(false);
      setError(error.message);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {error && <ErrorBanner message={error} />}
      {resetNotice && (
        <div className="flex items-start gap-2 rounded-lg bg-accent/10 border border-accent/30 text-accent px-3 py-2.5 text-sm">
          <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
          {resetNotice}
        </div>
      )}

      <GoogleButton loading={googleLoading} onClick={handleGoogle} />

      <div className="flex items-center gap-3">
        <Separator className="flex-1 bg-white/10" />
        <span className="text-xs text-white/30">or</span>
        <Separator className="flex-1 bg-white/10" />
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="login-email" className="text-white/70 text-sm">Email</Label>
          <Input
            id="login-email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="!bg-white/10 border-white/20 text-white placeholder:text-white/25 focus-visible:ring-primary"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="login-password" className="text-white/70 text-sm">Password</Label>
            <button
              type="button"
              onClick={handleForgot}
              className="text-xs text-primary hover:text-primary/80 transition-colors"
            >
              Forgot?
            </button>
          </div>
          <Input
            id="login-password"
            type="password"
            autoComplete="current-password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="!bg-white/10 border-white/20 text-white placeholder:text-white/25 focus-visible:ring-primary"
          />
        </div>

        <Button
          type="submit"
          disabled={loading}
          className="w-full bg-primary hover:bg-primary/90 text-white font-bold h-10 mt-1"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Log in"}
        </Button>
      </form>
    </div>
  );
}

/* ── Signup tab ────────────────────────────────────────────────────────────── */
function SignupForm() {
  const navigate = useNavigate();
  const location = useLocation() as { state?: { from?: string } };
  const destination = location.state?.from ?? "/app";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 6) { setError("Password must be at least 6 characters."); return; }
    setLoading(true);
    const { error, data } = await supabase.auth.signUp({ email, password });
    setLoading(false);
    if (error) { setError(error.message); return; }
    if (data.session) navigate(destination);
    else setSuccess(true);
  };

  const handleGoogle = async () => {
    setGoogleLoading(true);
    setError(null);
    // On success the browser navigates away, so this only matters when the
    // call fails (popup blocked, provider misconfigured) — without it the
    // button spins forever with no explanation.
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/app` },
    });
    if (error) {
      setGoogleLoading(false);
      setError(error.message);
    }
  };

  if (success) {
    return (
      <div className="flex flex-col items-center text-center gap-3 py-4">
        <CheckCircle2 className="h-10 w-10 text-accent" />
        <p className="font-semibold text-white">Check your inbox</p>
        <p className="text-sm text-white/50">
          Confirmation link sent to <span className="text-white">{email}</span>.
          Click it to activate your account.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <ErrorBanner message={error} />}

      <GoogleButton loading={googleLoading} onClick={handleGoogle} />

      <div className="flex items-center gap-3">
        <Separator className="flex-1 bg-white/10" />
        <span className="text-xs text-white/30">or</span>
        <Separator className="flex-1 bg-white/10" />
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-email" className="text-white/70 text-sm">Email</Label>
          <Input
            id="signup-email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="!bg-white/10 border-white/20 text-white placeholder:text-white/25 focus-visible:ring-primary"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="signup-password" className="text-white/70 text-sm">Password</Label>
          <Input
            id="signup-password"
            type="password"
            autoComplete="new-password"
            placeholder="Min. 6 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="!bg-white/10 border-white/20 text-white placeholder:text-white/25 focus-visible:ring-primary"
          />
        </div>

        <Button
          type="submit"
          disabled={loading}
          className="w-full bg-primary hover:bg-primary/90 text-white font-bold h-10 mt-1"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create account"}
        </Button>
      </form>

      <p className="text-xs text-white/25 text-center">
        By signing up you agree to our{" "}
        <Link to="/terms" className="underline hover:text-white/50">Terms</Link> &amp;{" "}
        <Link to="/privacy" className="underline hover:text-white/50">Privacy</Link>.
      </p>
    </div>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────────── */
export default function Auth() {
  const [searchParams] = useSearchParams();
  const defaultTab = searchParams.get("tab") === "login" ? "login" : "signup";

  return (
    <div className="min-h-screen bg-[hsl(248_20%_8%)] flex flex-col items-center justify-center px-4">
      {/* Logo */}
      <Link to="/" className="flex items-center gap-2 font-bold text-white mb-8">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-xs font-black text-white">
          FPL
        </span>
        <span className="text-lg">FPLedge</span>
      </Link>

      <div className="w-full max-w-sm">
        <Tabs defaultValue={defaultTab} className="w-full">
          <TabsList className="w-full mb-6 bg-white/[0.06] border border-white/10 p-1 rounded-xl">
            <TabsTrigger
              value="signup"
              className="flex-1 rounded-lg text-white/50 data-[state=active]:bg-primary data-[state=active]:text-white font-semibold transition-all"
            >
              Sign up
            </TabsTrigger>
            <TabsTrigger
              value="login"
              className="flex-1 rounded-lg text-white/50 data-[state=active]:bg-white/10 data-[state=active]:text-white font-semibold transition-all"
            >
              Log in
            </TabsTrigger>
          </TabsList>

          <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-6">
            <TabsContent value="signup" className="mt-0">
              <SignupForm />
            </TabsContent>
            <TabsContent value="login" className="mt-0">
              <LoginForm />
            </TabsContent>
          </div>
        </Tabs>

        {/* No anonymous mode: /app is behind ProtectedRoute and the API now
            requires a signed-in session, so the old "Continue without account"
            link bounced straight back here. Offer the way out that works. */}
        <Link
          to="/"
          className="mt-5 flex items-center justify-center gap-1.5 text-sm text-white/35 hover:text-white/60 transition-colors group"
        >
          <ArrowLeft className="h-3.5 w-3.5 group-hover:-translate-x-0.5 transition-transform" />
          Back to home
        </Link>
      </div>
    </div>
  );
}
