import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { DeadlineCountdown } from "./DeadlineCountdown";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";
import { LogOut, Menu } from "lucide-react";

const landingLinks = [
  { label: "Features", href: "/#features" },
  { label: "Pricing", href: "/#pricing" },
];

const appLinks = [
  { label: "Squad", to: "/app" },
  { label: "Captain", to: "/app/captain" },
  { label: "Planner", to: "/app/fixtures" },
  { label: "Mini-league", to: "/app/league" },
  // Secondary route: off the strip below lg (five tabs + pill + Sign out don't fit at md).
  { label: "Draft squad", to: "/app/squad-picker", secondary: true },
];

export interface PlanStatus {
  /** Things the user would have to change in the FPL app. */
  changes: number;
  /** The plan is saved. */
  locked: boolean;
}

interface NavbarProps {
  /** Page-specific stats shown left of the deadline pill on app routes (e.g. Bank · FT). */
  extras?: ReactNode;
  /** v2 flow: "No changes yet" / "n unsaved changes" / "Plan saved". Shown at every width. */
  planStatus?: PlanStatus;
}

/** Which tab a path lights. Plan steps live under /app/plan/:step and belong to
 *  Squad, except the captain step, which the Captain tab owns. */
export const activeTabFor = (pathname: string): string => {
  if (pathname === "/app/plan/captain") return "/app/captain";
  if (pathname.startsWith("/app/plan")) return "/app";
  return pathname;
};

function PlanStatusPill({ status }: { status: PlanStatus }) {
  const tone = status.locked ? "saved" : status.changes > 0 ? "warning" : "muted";
  const long = status.locked ? "Plan saved" : status.changes > 0 ? `${status.changes} unsaved change${status.changes === 1 ? "" : "s"}` : "No changes yet";
  const short = status.locked ? "Saved" : status.changes > 0 ? `${status.changes} unsaved` : "No changes";
  return (
    <span
      data-testid="plan-status"
      data-tone={tone}
      className={cn(
        "whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] font-semibold sm:text-xs",
        tone === "saved" && "border-accent/45 bg-accent/10 text-accent",
        tone === "warning" && "border-warning/45 bg-warning/[0.08] text-warning",
        tone === "muted" && "border-border text-muted-foreground",
      )}
    >
      <span className="hidden md:inline">{long}</span>
      <span className="md:hidden">{short}</span>
    </span>
  );
}

export function Navbar({ extras, planStatus }: NavbarProps = {}) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const isApp = pathname.startsWith("/app");
  const activeTab = activeTabFor(pathname);

  const handleSignOut = async () => {
    await signOut();
    navigate("/");
  };

  return (
    <header className="fixed top-0 inset-x-0 z-50 border-b border-white/10 bg-[hsl(248_20%_8%/0.85)] backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        {/* Logo */}
        <Link to="/" className="flex items-center gap-2 font-bold text-white tracking-tight">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-xs font-black text-white">
            FPL
          </span>
          <span className="hidden sm:inline">FPLedge</span>
        </Link>

        {/* Nav links — only on landing */}
        {!isApp && (
          <nav className="hidden md:flex items-center gap-6 text-sm text-white/70">
            {landingLinks.map((l) => (
              <a
                key={l.label}
                href={l.href}
                className="hover:text-white transition-colors"
              >
                {l.label}
              </a>
            ))}
          </nav>
        )}

        {/* Right side */}
        <div className="flex items-center gap-2">
          {user ? (
            // Logged-in state
            <>
              {!isApp && (
                <Link to="/app">
                  <Button size="sm" className="bg-primary hover:bg-primary/90 text-white font-semibold">
                    Open squad
                  </Button>
                </Link>
              )}
              {isApp && (
                // The active page stays visible and lit instead of being filtered
                // out — the handoff's tab strip, and the only cue for which hub you're in.
                <nav data-testid="app-tabs" className="hidden md:flex items-center gap-1">
                  {appLinks.map((l) => {
                    const active = l.to === activeTab;
                    return (
                      <Link
                        key={l.to}
                        to={l.to}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "rounded-lg px-2.5 py-1.5 text-[13px] font-semibold transition-colors",
                          l.secondary ? "hidden lg:inline-flex" : "inline-flex",
                          active ? "bg-white/[0.06] text-white" : "text-white/55 hover:text-white",
                        )}
                      >
                        {l.label}
                      </Link>
                    );
                  })}
                </nav>
              )}
              {isApp && planStatus && <PlanStatusPill status={planStatus} />}
              {isApp && (
                // Stats need the room only lg+ has; at md the tab strip plus the
                // pill plus Sign out already fill the 56px row. Phones get neither
                // — the drawer and the GW bar carry the same facts.
                <div className="hidden md:flex items-center gap-4 text-xs text-muted-foreground">
                  <div className="hidden lg:flex items-center gap-4">{extras}</div>
                  <DeadlineCountdown />
                </div>
              )}
              {isApp && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="md:hidden text-white/70 hover:text-white"
                      aria-label="Open navigation menu"
                    >
                      <Menu className="h-5 w-5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {appLinks
                      .filter((l) => l.to !== activeTab)
                      .map((l) => (
                        <DropdownMenuItem key={l.to} asChild>
                          <Link to={l.to}>{l.label}</Link>
                        </DropdownMenuItem>
                      ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={handleSignOut}
                className="text-white/50 hover:text-white gap-1.5"
              >
                <LogOut className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Sign out</span>
              </Button>
            </>
          ) : (
            // Logged-out state
            <>
              <Link to="/auth?tab=login">
                <Button variant="ghost" size="sm" className="text-white/70 hover:text-white">
                  Log in
                </Button>
              </Link>
              <Link to="/auth">
                <Button
                  size="sm"
                  className={cn("bg-primary text-white hover:bg-primary/90 font-semibold")}
                >
                  Start free
                </Button>
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
