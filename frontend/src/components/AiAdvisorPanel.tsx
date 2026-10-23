import { useState } from "react";
import { Sparkles, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  fetchChatAnswer,
  fetchSpecialistAnswer,
  type ChatResponse,
  type Specialist,
} from "@/lib/fplAssistantApi";

interface AiAdvisorPanelProps {
  entryId?: number;
  currentGw?: number;
  chipsRemaining?: string[];
}

type Preset = {
  label: string;
  specialist?: Specialist; // if set, skip orchestrator
  question: string;        // used for display + orchestrator fallback
};

const PRESETS: Preset[] = [
  { label: "Who should I captain?", specialist: "captain", question: "Who should I captain?" },
  { label: "Best transfer?", specialist: "transfer", question: "Should I make a transfer or roll my FT?" },
  { label: "Should I play a chip?", specialist: "chip", question: "Should I play a chip this week?" },
  { label: "Full game plan", question: "What should I do this week?" }, // uses orchestrator
];

export const AiAdvisorPanel = ({
  entryId,
  currentGw,
  chipsRemaining,
}: AiAdvisorPanelProps) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<ChatResponse | null>(null);
  const [lastQuestion, setLastQuestion] = useState<string>("");
  const [lastPreset, setLastPreset] = useState<Preset | null>(null);

  const runPreset = async (preset: Preset) => {
    if (!entryId) {
      setError("Enter your FPL team ID first.");
      return;
    }
    setLoading(true);
    setError(null);
    setLastQuestion(preset.question);
    setLastPreset(preset);
    try {
      const res = preset.specialist
        ? await fetchSpecialistAnswer(preset.specialist, {
            entry_id: entryId,
            current_gw: currentGw,
            chips_remaining: chipsRemaining,
          })
        : await fetchChatAnswer({
            entry_id: entryId,
            message: preset.question,
            current_gw: currentGw,
            chips_remaining: chipsRemaining,
          });
      setAnswer(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const regenerate = () => {
    if (lastPreset) runPreset(lastPreset);
  };

  return (
    <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <p className="text-[11px] font-bold uppercase tracking-wider text-primary">
          ZN AI Advisor
        </p>
      </div>

      {!answer && !loading && !error && (
        <p className="text-xs text-muted-foreground leading-relaxed">
          Ask the agent for personalised advice based on your squad, fixtures, and projections.
        </p>
      )}

      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => (
          <Button
            key={p.label}
            variant="outline"
            size="sm"
            disabled={loading || !entryId}
            onClick={() => runPreset(p)}
            className="text-[11px] h-7 px-2.5"
          >
            {p.label}
          </Button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>Thinking… {lastQuestion && `"${lastQuestion}"`}</span>
        </div>
      )}

      {error && !loading && (
        <div className="rounded-md bg-destructive/10 border border-destructive/30 px-2.5 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      {answer && !loading && (
        <div className="rounded-md bg-card border border-border px-3 py-2.5 text-xs text-foreground leading-relaxed whitespace-pre-wrap">
          {lastQuestion && (
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
              Q: {lastQuestion}
            </p>
          )}
          {answer.answer}
          <div className="flex items-center justify-between mt-2.5 pt-2 border-t border-border/50">
            <span className="text-[10px] text-muted-foreground">
              GW{answer.current_gw} · {(answer.latency_ms / 1000).toFixed(1)}s
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={regenerate}
              className="h-6 px-2 text-[10px]"
            >
              <RefreshCw className="h-3 w-3 mr-1" /> Regenerate
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
