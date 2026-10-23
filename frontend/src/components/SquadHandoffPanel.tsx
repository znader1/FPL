import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { formatSquadForClipboard, type HandoffPlayer } from "@/lib/squadDraft";
import { ENTRY_ID_STORAGE_KEY, parseEntryIdInput } from "@/lib/entryId";
import { useProfile } from "@/hooks/useProfile";
import { Check, Copy } from "lucide-react";

/**
 * Shown once a legal 15 is drafted: copy the list, enter it on the FPL site,
 * come back and link the new entry ID — which drops the user straight into
 * the main squad page.
 */
export function SquadHandoffPanel({ squad }: { squad: HandoffPlayer[] }) {
  const navigate = useNavigate();
  const { saveEntryId } = useProfile();
  const [copied, setCopied] = useState(false);
  const [draftId, setDraftId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const copySquad = async () => {
    try {
      await navigator.clipboard.writeText(formatSquadForClipboard(squad));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Copy failed — select and copy the list manually.");
    }
  };

  const linkEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const id = parseEntryIdInput(draftId);
    if (!id) {
      setError("Enter your team ID or paste your FPL team URL.");
      return;
    }
    localStorage.setItem(ENTRY_ID_STORAGE_KEY, String(id));
    await saveEntryId(id);
    navigate("/app");
  };

  return (
    <Card className="p-4 border-primary/40">
      <div className="text-sm font-semibold mb-2">Happy with this squad? Take it live</div>
      <ol className="text-sm text-muted-foreground list-decimal pl-5 space-y-1 mb-3">
        <li>
          Copy the squad list, then create your team at{" "}
          <a
            className="text-primary underline"
            href="https://fantasy.premierleague.com"
            target="_blank"
            rel="noreferrer"
          >
            fantasy.premierleague.com
          </a>
          .
        </li>
        <li>Pick these 15 players there and save your team.</li>
        <li>Come back and paste your new team ID (or team URL) below.</li>
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={copySquad}>
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5 mr-1" /> Copied
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5 mr-1" /> Copy squad list
            </>
          )}
        </Button>
        <form className="flex flex-1 min-w-56 gap-2" onSubmit={linkEntry}>
          <Input
            type="text"
            inputMode="numeric"
            placeholder="Team ID or full URL"
            value={draftId}
            onChange={(e) => setDraftId(e.target.value)}
            className="flex-1"
          />
          <Button type="submit" className="shrink-0">
            Link my team
          </Button>
        </form>
      </div>
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </Card>
  );
}
