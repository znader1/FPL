import { getTeamConfig } from "@/lib/teamColors";

interface JerseyIconProps {
  team: string;
  number?: number;
  size?: "sm" | "md" | "lg";
  isCaptain?: boolean;
}

const sizeMap = {
  sm: { width: 36, height: 40, fontSize: 10, badgeSize: 12 },
  md: { width: 48, height: 54, fontSize: 13, badgeSize: 16 },
  lg: { width: 64, height: 72, fontSize: 16, badgeSize: 20 },
};

export const JerseyIcon = ({ team, number, size = "md", isCaptain = false }: JerseyIconProps) => {
  const config = getTeamConfig(team);
  const s = sizeMap[size];

  return (
    <div className="relative inline-block">
      <svg
        width={s.width}
        height={s.height}
        viewBox="0 0 64 72"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="drop-shadow-md"
      >
        {/* Shirt body */}
        <path
          d="M12 20L4 14L10 4L22 2L32 8L42 2L54 4L60 14L52 20V68H12V20Z"
          fill={`hsl(${config.primary})`}
          stroke={`hsl(${config.secondary} / 0.3)`}
          strokeWidth="1"
        />
        {/* Sleeves */}
        <path
          d="M12 20L4 14L10 4L16 8L12 20Z"
          fill={`hsl(${config.primary})`}
          stroke={`hsl(${config.secondary} / 0.2)`}
          strokeWidth="0.5"
        />
        <path
          d="M52 20L60 14L54 4L48 8L52 20Z"
          fill={`hsl(${config.primary})`}
          stroke={`hsl(${config.secondary} / 0.2)`}
          strokeWidth="0.5"
        />
        {/* Collar */}
        <path
          d="M22 2L32 8L42 2"
          fill="none"
          stroke={`hsl(${config.secondary})`}
          strokeWidth="2"
          strokeLinecap="round"
        />
        {/* Stripe detail */}
        <rect
          x="28"
          y="20"
          width="8"
          height="48"
          fill={`hsl(${config.secondary} / 0.08)`}
        />
        {/* Number */}
        {number !== undefined && (
          <text
            x="32"
            y="46"
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={s.fontSize}
            fontWeight="bold"
            fill={`hsl(${config.secondary})`}
            style={{ fontFamily: "system-ui, sans-serif" }}
          >
            {number}
          </text>
        )}
      </svg>
      {/* Captain badge */}
      {isCaptain && (
        <div
          className="absolute -top-1 -right-1 rounded-full flex items-center justify-center text-[8px] font-bold border border-background"
          style={{
            width: s.badgeSize,
            height: s.badgeSize,
            background: `hsl(${config.accent})`,
            color: config.accent === "0 0% 100%" ? "hsl(0 0% 10%)" : "hsl(0 0% 100%)",
          }}
        >
          C
        </div>
      )}
    </div>
  );
};
