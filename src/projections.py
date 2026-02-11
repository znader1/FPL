import pandas as pd

from . import transforms


DIFFICULTY_MULTIPLIER = {
    1: 1.15,
    2: 1.08,
    3: 1.00,
    4: 0.93,
    5: 0.86,
}


def difficulty_multiplier(diff_avg):
    """Map FPL difficulty (1..5) to a simple multiplier."""
    if pd.isna(diff_avg):
        return 1.0
    try:
        d = int(round(float(diff_avg)))
    except Exception:
        return 1.0
    d = max(1, min(5, d))
    return float(DIFFICULTY_MULTIPLIER.get(d, 1.0))


def baseline_points_per_gw(elements, ppg_weight=0.6, form_weight=0.4):
    """
    Fallback baseline when ep_next is missing: blend points_per_game and form.
    """
    ppg = pd.to_numeric(elements.get("points_per_game", 0), errors="coerce").fillna(0.0)
    form = pd.to_numeric(elements.get("form", 0), errors="coerce").fillna(0.0)
    return float(ppg_weight) * ppg + float(form_weight) * form


def project_elements_next_gws(
    elements,
    fixtures,
    teams_short_map,
    gw_start,
    horizon_gws=3,
    ppg_weight=0.6,
    form_weight=0.4,
):
    """
    Lightweight next-N gameweeks projection table (FPL-only baseline).

    - Uses `ep_next` for the first GW when available.
    - Otherwise falls back to a simple `ppg+form` baseline.
    - Adjusts for fixture difficulty and doubles/blanks.
    - Applies playing probability (chance_of_playing_next_round) for the immediate GW only.
    """
    gw_start = int(gw_start)
    horizon_gws = int(horizon_gws)
    gws = [gw_start + i for i in range(horizon_gws)]

    df = elements.copy()
    base_fallback = baseline_points_per_gw(df, ppg_weight=ppg_weight, form_weight=form_weight)

    if "ep_next" in df.columns:
        ep_next = pd.to_numeric(df["ep_next"], errors="coerce")
    else:
        ep_next = pd.Series(pd.NA, index=df.index)
    base_gw0 = ep_next.where(ep_next.notna(), base_fallback).fillna(0.0)

    if "chance_of_playing_next_round" in df.columns:
        chance_next = pd.to_numeric(df["chance_of_playing_next_round"], errors="coerce")
        play_prob = (chance_next / 100.0).fillna(1.0).clip(lower=0.0, upper=1.0)
    else:
        play_prob = pd.Series(1.0, index=df.index)

    horizon_total = pd.Series(0.0, index=df.index, dtype="float64")

    for i, gw in enumerate(gws):
        ann = transforms.annotate_elements_with_gw_fixtures(df, fixtures, int(gw), teams_short_map)
        fixture_count = pd.to_numeric(ann["gw_fixture_count"], errors="coerce").fillna(0.0)
        diff_avg = pd.to_numeric(ann["gw_diff_avg"], errors="coerce").fillna(0.0)
        mult = diff_avg.apply(difficulty_multiplier)

        base = base_gw0 if i == 0 else base_fallback
        xpts = base * fixture_count * mult
        if i == 0:
            xpts = xpts * play_prob

        df[f"fixtures_gw{gw}"] = ann["gw_fixtures"].fillna("")
        df[f"fixture_count_gw{gw}"] = fixture_count.astype(int)
        df[f"diff_avg_gw{gw}"] = diff_avg
        df[f"xpts_gw{gw}"] = xpts

        horizon_total = horizon_total + xpts.fillna(0.0)

    df["xpts_horizon"] = horizon_total

    keep_base = [
        "id",
        "web_name",
        "pos",
        "team",
        "team_short",
        "team_name",
        "price_m",
        "now_cost",
        "status",
        "chance_of_playing_next_round",
        "form",
        "points_per_game",
        "total_points",
        "selected_by_percent",
        "ep_next",
    ]
    keep = [c for c in keep_base if c in df.columns]
    for gw in gws:
        keep.extend(
            [
                f"xpts_gw{gw}",
                f"fixtures_gw{gw}",
                f"fixture_count_gw{gw}",
                f"diff_avg_gw{gw}",
            ]
        )
    keep.append("xpts_horizon")

    out = df[[c for c in keep if c in df.columns]].copy()
    out = out.sort_values("xpts_horizon", ascending=False)
    return out
