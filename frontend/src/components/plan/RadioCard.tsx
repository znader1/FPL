import type { ReactNode } from "react";

interface RadioCardProps {
  checked: boolean;
  disabled?: boolean;
  onPick: () => void;
  children: ReactNode;
  className?: string;
  label: string;
}

/** The handoff's selectable card: a radio dot, pink ring when chosen. */
export function RadioCard({ checked, disabled = false, onPick, children, className = "", label }: RadioCardProps) {
  return (
    <div
      role="radio"
      aria-checked={checked}
      aria-disabled={disabled || undefined}
      aria-label={label}
      tabIndex={disabled ? -1 : 0}
      onClick={disabled ? undefined : onPick}
      onKeyDown={(e) => {
        if (disabled) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onPick();
        }
      }}
      className={`flex flex-col gap-3 rounded-2xl border p-5 text-left transition-[border-color,background-color,box-shadow] duration-200 ${
        checked
          ? "border-primary/70 bg-primary/10 shadow-[0_0_0_1px_hsl(var(--primary)/.5),0_12px_40px_hsl(var(--primary)/.22)]"
          : "border-border bg-card"
      } ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:border-primary/30"} ${className}`}
    >
      {children}
    </div>
  );
}

export function RadioDot({ checked, size = 18 }: { checked: boolean; size?: number }) {
  return (
    <span
      aria-hidden
      className={`flex shrink-0 items-center justify-center rounded-full border-2 ${checked ? "border-primary" : "border-muted-foreground/50"}`}
      style={{ width: size, height: size }}
    >
      <span className={`rounded-full ${checked ? "bg-primary" : "bg-transparent"}`} style={{ width: size * 0.44, height: size * 0.44 }} />
    </span>
  );
}
