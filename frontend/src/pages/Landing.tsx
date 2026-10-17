import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Navbar } from "@/components/layout/Navbar";
import {
  Brain,
  TrendingUp,
  Shield,
  ArrowRight,
  Shuffle,
  BarChart3,
  Trophy,
  Check,
  Star,
  Zap,
} from "lucide-react";

/* ─── Feature cards ────────────────────────────────────────────────────────── */
const features = [
  {
    icon: Brain,
    title: "xPts Modelling",
    description:
      "Expected-points forecasts for every player across upcoming gameweeks, driven by fixture difficulty and form.",
    color: "text-primary",
    bg: "bg-primary/10",
  },
  {
    icon: Shuffle,
    title: "Wildcard AI Drafter",
    description:
      "Build an optimal 15-man squad for your wildcard in seconds. Accounts for budget, fixtures, and multi-GW horizon.",
    color: "text-accent",
    bg: "bg-accent/10",
  },
  {
    icon: Star,
    title: "Captain Picks",
    description:
      "Data-backed captain and vice-captain recommendations every gameweek — ranked by ceiling and floor.",
    color: "text-primary",
    bg: "bg-primary/10",
  },
  {
    icon: TrendingUp,
    title: "Transfer Planner",
    description:
      "A multi-gameweek transfer plan, and what banking your free transfer instead is worth — both totals in points, side by side.",
    color: "text-accent",
    bg: "bg-accent/10",
  },
  {
    icon: Zap,
    title: "Chip Strategy",
    description:
      "Triple captain, bench boost, free hit — know exactly when and how to use each chip for maximum upside.",
    color: "text-primary",
    bg: "bg-primary/10",
  },
  {
    icon: BarChart3,
    title: "League Dashboard",
    description:
      "Mini-league strategy: chase, defend, or hunt differentials against your rivals.",
    color: "text-accent",
    bg: "bg-accent/10",
  },
];

/* ─── Beta perks ───────────────────────────────────────────────────────────── */
const betaPerks = [
  "xPts for every player, every GW",
  "Multi-GW planning horizon",
  "Wildcard & Free Hit chip drafts",
  "Transfer suggestions with point gain",
  "Captain & vice recommendations",
  "Mini-league strategy dashboard",
];

const comingSoon = ["Pro & Elite tiers", "Differential alerts", "API access"];

/* ─── Stats ─────────────────────────────────────────────────────────────────── */
const stats = [
  { value: "Every player", label: "xPts modelled per GW" },
  { value: "6 GWs", label: "Planning horizon" },
  { value: "2026/27", label: "Season live now" },
];

/* ─────────────────────────────────────────────────────────────────────────── */

export default function Landing() {
  return (
    <div className="min-h-screen bg-[hsl(248_20%_8%)] text-white">
      <Navbar />

      {/* ── Hero ── */}
      <section className="relative overflow-hidden pt-32 pb-24 px-4 sm:px-6">
        {/* background glow */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 flex items-center justify-center"
        >
          <div className="h-[600px] w-[600px] rounded-full bg-primary/20 blur-[120px] opacity-40" />
        </div>

        <div className="relative mx-auto max-w-4xl text-center">
          <Badge className="mb-6 bg-primary/15 text-primary border-primary/30 hover:bg-primary/20 text-xs font-semibold tracking-wide uppercase">
            AI-powered FPL decisions
          </Badge>

          <h1 className="text-5xl sm:text-6xl lg:text-7xl font-black leading-[1.05] tracking-tight mb-6">
            Your next FPL move,
            <br />
            <span className="text-primary">backed by</span> the numbers
          </h1>

          <p className="mx-auto max-w-2xl text-lg sm:text-xl text-white/60 mb-10 leading-relaxed">
            Transfer recommendations, captain picks and fixture analysis — all
            powered by xPts modelling, with an AI that explains the reasoning
            behind every call. Built by managers, for managers.
          </p>

          <div className="flex flex-wrap items-center justify-center gap-3 mb-16">
            <Link to="/auth">
              <Button
                size="lg"
                className="bg-primary hover:bg-primary/90 text-white font-bold px-8 h-12 text-base"
              >
                Build my squad
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </Link>
            <a href="#features">
              <Button
                size="lg"
                variant="outline"
                className="border-white/20 text-white bg-white/5 hover:bg-white/10 h-12 text-base"
              >
                See how it works
              </Button>
            </a>
          </div>

          {/* Stats row */}
          <div className="flex flex-wrap items-center justify-center gap-8 sm:gap-16">
            {stats.map((s) => (
              <div key={s.label} className="text-center">
                <p className="text-2xl sm:text-3xl font-black text-white">{s.value}</p>
                <p className="text-sm text-white/50 mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="py-24 px-4 sm:px-6">
        <div className="mx-auto max-w-6xl">
          <div className="text-center mb-16">
            <p className="text-xs font-bold uppercase tracking-widest text-primary mb-3">
              Core features
            </p>
            <h2 className="text-3xl sm:text-4xl font-black mb-4">
              Everything your FPL season needs
            </h2>
            <p className="text-white/50 max-w-xl mx-auto">
              FPLedge covers the full FPL manager workflow in one place.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {features.map((f) => {
              const Icon = f.icon;
              return (
                <div
                  key={f.title}
                  className="rounded-2xl border border-white/[0.08] bg-white/[0.04] p-6 hover:bg-white/[0.07] hover:border-white/[0.14] transition-all duration-200 group"
                >
                  <div className={`inline-flex h-10 w-10 items-center justify-center rounded-xl ${f.bg} mb-4`}>
                    <Icon className={`h-5 w-5 ${f.color}`} />
                  </div>
                  <h3 className="font-bold text-white mb-2">{f.title}</h3>
                  <p className="text-sm text-white/50 leading-relaxed">{f.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── Pitch preview strip ── */}
      <section className="py-16 px-4 sm:px-6 bg-white/[0.03] border-y border-white/[0.08]">
        <div className="mx-auto max-w-6xl flex flex-col md:flex-row items-center gap-10">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-bold uppercase tracking-widest text-accent mb-3">
              Live tool preview
            </p>
            <h2 className="text-3xl sm:text-4xl font-black mb-4">
              See your squad. Act on it.
            </h2>
            <p className="text-white/50 leading-relaxed mb-6">
              Enter your FPL team ID and instantly see your current squad on a
              real pitch, complete with fixture difficulty ratings, xPts for
              every player, and one-click AI recommendations.
            </p>
            <Link to="/auth">
              <Button className="bg-accent hover:bg-accent/90 text-white font-bold">
                Try it now — it's free
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </Link>
          </div>
          {/* Pitch mock */}
          <div className="flex-1 min-w-0 w-full max-w-sm mx-auto md:max-w-none">
            <div className="rounded-2xl border border-white/10 bg-[hsl(152_48%_26%)] overflow-hidden aspect-[3/4] relative shadow-2xl">
              {/* pitch lines */}
              <div className="absolute inset-4 border border-white/20 rounded-lg" />
              <div className="absolute top-1/2 left-4 right-4 h-px bg-white/20 -translate-y-1/2" />
              <div className="absolute top-1/2 left-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/20" />
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-6 p-6">
                <p className="text-white/40 text-sm font-medium">Pitch view</p>
                <Link to="/auth">
                  <Button size="sm" className="bg-white/15 hover:bg-white/25 text-white border border-white/20">
                    Open squad →
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Pricing ── */}
      <section id="pricing" className="py-24 px-4 sm:px-6">
        <div className="mx-auto max-w-5xl">
          <div className="text-center mb-14">
            <p className="text-xs font-bold uppercase tracking-widest text-primary mb-3">
              Pricing
            </p>
            <h2 className="text-3xl sm:text-4xl font-black mb-4">
              Simple, season-aligned plans
            </h2>
            <p className="text-white/50">Free while we're in beta — paid tiers arrive once the product earns them.</p>
          </div>

          <div className="mx-auto max-w-md">
            <div className="rounded-2xl border border-primary bg-primary/10 ring-1 ring-primary/50 p-8 flex flex-col gap-5 shadow-lg shadow-primary/20">
              <Badge className="w-fit bg-primary text-white text-xs font-bold">Beta</Badge>
              <div>
                <p className="text-4xl font-black text-white">
                  Free
                  <span className="text-lg font-medium text-white/40"> while in beta</span>
                </p>
                <p className="text-sm text-white/40 mt-1">
                  Full access. No card. Help shape the product.
                </p>
              </div>
              <ul className="flex flex-col gap-2.5">
                {betaPerks.map((perk) => (
                  <li key={perk} className="flex items-start gap-2 text-sm text-white/70">
                    <Check className="h-4 w-4 text-accent mt-0.5 shrink-0" />
                    {perk}
                  </li>
                ))}
              </ul>
              <div className="border-t border-white/10 pt-4">
                <p className="text-xs uppercase tracking-widest text-white/30 mb-2">Coming later</p>
                <ul className="flex flex-col gap-1.5">
                  {comingSoon.map((item) => (
                    <li key={item} className="text-sm text-white/35">{item}</li>
                  ))}
                </ul>
              </div>
              <Link to="/auth" className="mt-auto">
                <Button className="w-full font-bold bg-primary hover:bg-primary/90 text-white">
                  Get started free
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </section>


      {/* ── CTA ── */}
      <section className="py-24 px-4 sm:px-6 bg-white/[0.03] border-t border-white/[0.08]">
        <div className="mx-auto max-w-2xl text-center">
          <Trophy className="h-10 w-10 text-primary mx-auto mb-5 opacity-80" />
          <h2 className="text-3xl sm:text-4xl font-black mb-4">
            Make smarter picks this season
          </h2>
          <p className="text-white/50 mb-8">
            Free to start. No credit card required. Your first AI recommendation
            is one click away.
          </p>
          <Link to="/auth">
            <Button
              size="lg"
              className="bg-primary hover:bg-primary/90 text-white font-bold px-10 h-12 text-base"
            >
              Get started free
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-white/[0.08] py-8 px-4 sm:px-6">
        <div className="mx-auto max-w-6xl flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-white/30">
          <div className="flex items-center gap-2 font-bold text-white/60">
            <span className="flex h-6 w-6 items-center justify-center rounded bg-primary text-[10px] font-black text-white">
              FPL
            </span>
            FPLedge
          </div>
          <p>© {new Date().getFullYear()} FPLedge. Not affiliated with the Premier League.</p>
          <div className="flex gap-4">
            <Link to="/privacy" className="hover:text-white/60 transition-colors">Privacy</Link>
            <Link to="/terms" className="hover:text-white/60 transition-colors">Terms</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
