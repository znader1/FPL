export interface TeamConfig {
  name: string;
  short: string;
  primary: string;    // HSL values
  secondary: string;  // HSL values
  accent: string;     // HSL values (for shirt details)
}

export const TEAM_COLORS: Record<string, TeamConfig> = {
  ARS: {
    name: "Arsenal",
    short: "ARS",
    primary: "0 76% 48%",        // Red
    secondary: "0 0% 100%",      // White
    accent: "45 100% 50%",       // Gold
  },
  AVL: {
    name: "Aston Villa",
    short: "AVL",
    primary: "280 60% 30%",      // Claret
    secondary: "195 100% 55%",   // Sky blue
    accent: "45 100% 50%",
  },
  BOU: {
    name: "Bournemouth",
    short: "BOU",
    primary: "0 80% 42%",        // Cherry red
    secondary: "0 0% 10%",       // Black
    accent: "0 0% 100%",
  },
  BRE: {
    name: "Brentford",
    short: "BRE",
    primary: "0 85% 50%",        // Red
    secondary: "0 0% 100%",      // White
    accent: "0 0% 15%",
  },
  BHA: {
    name: "Brighton",
    short: "BHA",
    primary: "218 80% 45%",      // Blue
    secondary: "0 0% 100%",      // White
    accent: "45 100% 50%",
  },
  BUR: {
    name: "Burnley",
    short: "BUR",
    primary: "280 50% 25%",      // Claret
    secondary: "195 70% 50%",    // Blue
    accent: "45 100% 50%",
  },
  CHE: {
    name: "Chelsea",
    short: "CHE",
    primary: "225 85% 40%",      // Blue
    secondary: "0 0% 100%",      // White
    accent: "45 100% 50%",
  },
  CRY: {
    name: "Crystal Palace",
    short: "CRY",
    primary: "225 85% 40%",      // Blue
    secondary: "0 80% 50%",      // Red
    accent: "0 0% 100%",
  },
  EVE: {
    name: "Everton",
    short: "EVE",
    primary: "218 85% 40%",      // Blue
    secondary: "0 0% 100%",      // White
    accent: "0 0% 100%",
  },
  FUL: {
    name: "Fulham",
    short: "FUL",
    primary: "0 0% 100%",        // White
    secondary: "0 0% 10%",       // Black
    accent: "0 75% 45%",
  },
  IPS: {
    name: "Ipswich",
    short: "IPS",
    primary: "225 80% 35%",      // Blue
    secondary: "0 0% 100%",      // White
    accent: "0 0% 100%",
  },
  LEI: {
    name: "Leicester",
    short: "LEI",
    primary: "225 85% 45%",      // Blue
    secondary: "0 0% 100%",      // White
    accent: "45 100% 50%",
  },
  LIV: {
    name: "Liverpool",
    short: "LIV",
    primary: "0 80% 45%",        // Red
    secondary: "0 0% 100%",      // White
    accent: "45 100% 50%",
  },
  MCI: {
    name: "Man City",
    short: "MCI",
    primary: "200 75% 55%",      // Sky blue
    secondary: "0 0% 100%",      // White
    accent: "215 60% 30%",
  },
  MUN: {
    name: "Man United",
    short: "MUN",
    primary: "0 80% 45%",        // Red
    secondary: "0 0% 100%",      // White
    accent: "45 100% 50%",
  },
  NEW: {
    name: "Newcastle",
    short: "NEW",
    primary: "0 0% 10%",         // Black
    secondary: "0 0% 100%",      // White
    accent: "0 0% 100%",
  },
  NFO: {
    name: "Nott'm Forest",
    short: "NFO",
    primary: "0 80% 42%",        // Red
    secondary: "0 0% 100%",      // White
    accent: "0 0% 100%",
  },
  SOU: {
    name: "Southampton",
    short: "SOU",
    primary: "0 80% 45%",        // Red
    secondary: "0 0% 100%",      // White
    accent: "0 0% 10%",
  },
  TOT: {
    name: "Tottenham",
    short: "TOT",
    primary: "0 0% 100%",        // White
    secondary: "220 30% 20%",    // Navy
    accent: "220 30% 20%",
  },
  WHU: {
    name: "West Ham",
    short: "WHU",
    primary: "280 50% 25%",      // Claret
    secondary: "195 80% 50%",    // Blue
    accent: "45 100% 50%",
  },
  WOL: {
    name: "Wolves",
    short: "WOL",
    primary: "40 85% 50%",       // Old gold
    secondary: "0 0% 10%",       // Black
    accent: "0 0% 100%",
  },
};

export const getTeamConfig = (teamShort: string): TeamConfig => {
  return TEAM_COLORS[teamShort] || {
    name: teamShort,
    short: teamShort,
    primary: "142 76% 36%",
    secondary: "0 0% 100%",
    accent: "0 0% 100%",
  };
};
