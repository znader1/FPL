import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { supabase } from "@/integrations/supabase/client";

export default function AuthConfirm() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Handle hash-based tokens (#access_token=...&refresh_token=...)
    const hash = window.location.hash;
    if (hash) {
      const params = new URLSearchParams(hash.replace("#", ""));
      const access_token = params.get("access_token");
      const refresh_token = params.get("refresh_token");
      if (access_token && refresh_token) {
        supabase.auth.setSession({ access_token, refresh_token }).then(({ error }) => {
          if (error) setError(error.message);
          else navigate("/app", { replace: true });
        });
        return;
      }
    }

    // Handle query-based tokens (?token_hash=...&type=...)
    const token_hash = searchParams.get("token_hash");
    const type = searchParams.get("type");

    if (!token_hash || !type) {
      // No token at all — just redirect to login
      navigate("/auth", { replace: true });
      return;
    }

    const validTypes = ["invite", "signup", "magiclink", "recovery", "email"];
    const otp_type = validTypes.includes(type) ? type as any : "invite";

    supabase.auth.verifyOtp({ token_hash, type: otp_type }).then(({ error }) => {
      if (error) setError(error.message);
      else navigate("/app", { replace: true });
    });
  }, []);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center space-y-4 p-8 max-w-md">
          <p className="text-lg font-semibold text-foreground">Confirmation failed</p>
          <p className="text-sm text-destructive">{error}</p>
          <a href="/auth" className="inline-block mt-4 text-primary underline text-sm">
            Go to login
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center space-y-2">
        <p className="text-foreground font-medium">Confirming your account…</p>
        <p className="text-muted-foreground text-sm">You'll be redirected shortly.</p>
      </div>
    </div>
  );
}
