import { lazy, Suspense } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "@/contexts/AuthContext";
import { isUnauthorized } from "@/lib/authFetch";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import Landing from "./pages/Landing";
import Auth from "./pages/Auth";
import Index from "./pages/Index";
import League from "./pages/League";
import Fixtures from "./pages/Fixtures";
import CaptainLab from "./pages/CaptainLab";
import NotFound from "./pages/NotFound";
import AuthConfirm from "./pages/AuthConfirm";
import Privacy from "./pages/Privacy";
import Terms from "./pages/Terms";

// Lazy + gated on import.meta.env.DEV (statically false in all production
// builds, regardless of .env) so this page drops from the bundle entirely.
// Also flag-gated on VITE_REPLAY_MODE for dev-time opt-in. Personal
// dev-only feature — see .env.example.
const Replay = /* @__PURE__ */ lazy(() => import("./pages/Replay"));

// Lazy so the picker's panels stay out of the initial bundle; loaded on
// first visit to /app/squad-picker.
const SquadPicker = lazy(() => import("./pages/SquadPicker"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Fly.io cold starts: retry twice with exponential backoff before failing.
      // An expired session is not worth retrying — it fails identically each
      // time, and the backoff would leave the user watching a spinner for ~11s
      // before the sign-in prompt appears.
      retry: (failureCount, error) => !isUnauthorized(error) && failureCount < 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
  },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <AuthProvider>
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/auth" element={<Auth />} />
              <Route path="/auth/confirm" element={<AuthConfirm />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/terms" element={<Terms />} />
              {/* Legacy redirects so old bookmarks still work */}
              <Route path="/login" element={<Auth />} />
              <Route path="/signup" element={<Auth />} />
              <Route path="/app" element={<ProtectedRoute><Index /></ProtectedRoute>} />
              <Route path="/app/captain" element={<ProtectedRoute><CaptainLab /></ProtectedRoute>} />
              <Route path="/app/league" element={<ProtectedRoute><League /></ProtectedRoute>} />
              <Route path="/app/fixtures" element={<ProtectedRoute><Fixtures /></ProtectedRoute>} />
              {import.meta.env.DEV && import.meta.env.VITE_REPLAY_MODE === "1" && (
                <Route path="/replay" element={<Suspense fallback={null}><Replay /></Suspense>} />
              )}
              <Route
                path="/app/squad-picker"
                element={
                  <ProtectedRoute>
                    <Suspense fallback={null}>
                      <SquadPicker />
                    </Suspense>
                  </ProtectedRoute>
                }
              />
              {/* Old dev bookmark */}
              {import.meta.env.DEV && import.meta.env.VITE_SQUAD_PICKER === "1" && (
                <Route path="/squad" element={<Suspense fallback={null}><SquadPicker /></Suspense>} />
              )}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </ErrorBoundary>
        </AuthProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
