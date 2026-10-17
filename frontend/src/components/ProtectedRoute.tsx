import { Navigate, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth();
  const location = useLocation();

  // Rendering null here left the page blank while Supabase resolved the
  // session, and since `dark` is applied per-page the browser painted the
  // light default — a white flash on every visit to /app.
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Carry the attempted path so a deep link (e.g. /app/league) survives the
  // sign-in round trip instead of always landing on the squad page.
  if (!session) return <Navigate to="/auth" replace state={{ from: location.pathname }} />;

  return <>{children}</>;
}
