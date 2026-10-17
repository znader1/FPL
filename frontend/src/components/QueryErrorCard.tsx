import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  title?: string;
  message?: string;
  onRetry: () => void;
  retrying?: boolean;
}

export const QueryErrorCard = ({
  title = "Couldn't load data",
  message,
  onRetry,
  retrying = false,
}: Props) => (
  <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-5 text-center">
    <p className="font-semibold text-destructive mb-1">{title}</p>
    {message && <p className="text-xs text-destructive/80 mb-3 break-words">{message}</p>}
    <Button size="sm" variant="outline" onClick={onRetry} disabled={retrying}>
      <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${retrying ? "animate-spin" : ""}`} />
      {retrying ? "Retrying…" : "Retry"}
    </Button>
  </div>
);
