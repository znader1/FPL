# Key-player absence analysis — design

Date: 2026-10-27. Status: phase 1 only. Phase 2 gated on phase-1 result.

## Intent

The xG stack treats a team's attack as a fixed rating. It is not: Chelsea with
João Pedro, Palmer and Rogers all on the pitch score freely; without João Pedro
they have produced almost nothing. The projection should know, before the
deadline, that a key absence lowers team xG and lowers the xGI of the teammates
who depend on him (and may raise a stand-in's). Transfer and wildcard
recommendations then inherit that.

Phase 1 answers one question with data: **is the effect real and large enough
to model, across all 20 teams, after controlling for opponent and venue?**
It is a monitoring tool for the owner. Nothing user-facing.

## Goals

- One script, run on demand, that reports for every team and each of its top-3
  key players: team attacking output and teammates' xG/xA rates with the key
  player present vs absent, with sample sizes.
- Works on both seasons on disk (2025-26 full, 2026-27 to date) so the method
  can be validated on 33 GWs before anyone trusts it on 8.
- An honest "no" is a valid output. The report must be able to say the effect
  is indistinguishable from noise.

## Non-goals

- No change to `projections.py`, `output_model.py`, `fixture_difficulty.py`
  or any API in phase 1.
- No user-facing explanation on the transfer card.
- No fitting of a per-team model. Per-team numbers are reported shrunk toward
  the league pool, never fitted alone.

## Anti-goals

- A report that makes a 2-match Chelsea split look like a finding.
- A split that is actually "away at Arsenal and Liverpool" vs "home to Burnley".
- Key players chosen from the same matches being split (survivorship bias).

## Data (what exists, verified 2026-10-27)

| Source | Rows | GWs | Notes |
|---|---|---|---|
| `data/processed/fpl/2025-26/player_match_history_2025-26.csv` | 24,659 | 1-33 | from `/element-summary/`; has `threat`, `creativity`, `starts`, zero-minute rows present |
| `data/processed/fpl/2026-27/player_match_history_2026-27.csv` | 1,236 | 1-4 | from `/event/{gw}/live/` via `live_history.py`; no threat/creativity; **zero-minute players are skipped** |
| Prod Fly volume | — | 1-8 | same live-history path, refreshed by `/admin/refresh` |

Common columns both files share: `element, element_type, team_id, fixture,
event, was_home, kickoff_time, minutes, starts, expected_goals,
expected_assists, expected_goals_conceded, total_points, bps`.
(`kickoff_time` is `kickoff_time_x` in the 2025-26 file; normalise on load.)

### Data decisions (owner-decided or builder's call, marked)

1. **Pull GW5-8 locally first.** Reuse `live_history.missing_event_ids` +
   `append_events` against the local 2026-27 CSV, exactly as `api/main.py`
   does at line ~1871. Four upstream calls. Do not run the 620-call
   `season_history` CLI. *(builder's call)*
2. **Absence is inferred, not read.** The live-history producer drops players
   with zero minutes, so "absent" = the team has rows for that fixture and the
   key player has none. For the 2025-26 file, also treat `minutes == 0` rows
   as absent so both seasons use one definition. "Benched" = `minutes > 0`
   and `starts == 0`, reported as a separate bucket. *(builder's call)*
3. **Transferred players.** `live_history.build_event_rows` assigns
   `team_id` from the current bootstrap team, so Isak's GW1-2 rows sit under
   Liverpool. Load `/fixtures/` (or the cached fixtures JSON) and drop any row
   whose `team_id` is neither `team_h` nor `team_a` of its fixture. Also build
   each team's per-fixture row set only from rows that survive this filter,
   so a moved player is never counted "absent" from a team he had left.
   *(builder's call)*
4. **Moved players are bounded.** Each (team, key player) split only covers
   fixtures between that player's first and last appearance for that club.
   Isak's Liverpool GW1-2 are neither present nor absent; January sales and
   signings in 2025-26 (27 players carry two `team_id`s) likewise. Note the
   step-3 filter is a no-op on 2025-26 (team_id already comes from the
   fixture pair); it matters only for the live-history file. *(builder's call)*
5. **Partial GW guard.** 2025-26 GW33 is partially scraped (fixtures 323,
   326, 333 have one-row or one-sided teams). A team "played" a fixture only
   if it has ≥ 11 rows with minutes > 0 for it; otherwise the fixture is
   dropped for that team. *(builder's call)*
6. **Cross-season join.** Element ids are reissued each season; join last
   season's ppg on bootstrap `code` (`data/raw/fpl/2025-26/bootstrap_static.json`
   has it; the 2026-27 bootstrap is fetched live, selection therefore needs
   network even without `--refresh`). *(builder's call)*
7. **2025-26 is the validation set and the prior; 2026-27 is the headline.**
   The owner asked for this season. Eight GWs cannot answer it per team, so the
   report leads with this season's numbers but always prints the league-wide
   2025-26 effect beside them. *(my call, stated to owner)*

## Key-player selection

Top 3 per team, chosen **before** looking at the matches to be split.

Score each outfield player on the team by rank-sum of (owner-specified
signals, rates chosen by me so a player's own absences cannot push him out
of the list):

- `threat` per 90 and `creativity` per 90 (bootstrap season totals / minutes,
  min 270 minutes this season; below that, last-season rate),
- `now_cost`,
- last-season points per game (from the 2025-26 file: `total_points` /
  appearances with minutes > 0, min 10 appearances),
- this-season points per game (appearances with minutes > 0).

For the 2025-26 run, use 2025-26 bootstrap-equivalent totals from the file
itself computed over the **whole** season, plus the `value` column for price.
(The season-total rank is a weak form of the same leakage noted above; it is
acceptable for a validation run because it is identical for every player and
does not depend on which matches he missed. Note it in the report.)

Tie-break by minutes. Goalkeepers excluded. The selected list is printed at
the top of the report so the owner can override by eye.

`--key-players "CHE:João Pedro,Palmer,Rogers"` forces a team's list. Required,
not optional: the owner will want to override by eye.

## Measurements

For every (team, key player), over the matches where the team played:

### A. Team attack vs fixture expectation

Two quantities per match, both reported, **only the second gates phase 2**:

- `team_xg_for`: whole-team xG. Mechanically drops when the key player is
  out (a team's top-threat player makes ~27% of its xG when he starts), so it
  cannot produce an honest "no".
- `teammates_xg_for = team_xg_for − key_player_xg`: what the rest of the
  team produced. This is what phase 2 would scale, because the absent player
  already projects zero in the engine; a whole-team multiplier would subtract
  him twice. *(my call, prompted by reviewer)*

For each, `ratio = value / expected_for`, where `expected_for` comes from
`fixture_difficulty.expected_xg_for_fixture` with ratings from the production
carryover path (`resolve_team_ratings` with the 2025-26 seed in
`data/models/`, knowledge discount off, decay off via a large
`halflife_days`). The carryover prior keeps opponent-defence ratings
meaningful at 8 matches where plain shrinkage would pull them ~43% toward
average; it is also the base a phase-2 multiplier would sit on. For the
2025-26 run use the same function with the 2024-25 seed if present, else
`compute_team_ratings` with `shrinkage_matches=0`. *(builder's call)*

Report, per bucket (present / absent / benched): n, mean of both ratios, mean
raw `xg_for`, mean goals if available (2025-26 has `team_h_score/team_a_score`;
2026-27 does not — print "n/a").

Effect (gating) = `mean_teammates_ratio_absent / mean_teammates_ratio_present`.
Whole-team effect printed beside it.

### B. Teammates' rates

For each other player on the team with ≥ 180 minutes in **both** buckets
(present and absent): minutes-weighted xG90 and xA90 in each bucket, and the
ratio. Print top 5 movers each way. This captures both "Palmer drops" and
"stand-in rises".

### C. League pool and shrinkage

Pool all (team, key player) pairs: weighted mean of the effect in A, weights =
`n_absent`. Report the pooled effect with its n and a bootstrap 90% interval
(resample pairs, 2000 draws).

Per-team effect shown as `shrunk = (n_absent * raw + k * pooled) / (n_absent + k)`
with `k = 4` matches, raw beside it. *(builder's call on k; it only affects
display in phase 1.)*

### D. Placebo

For each team, pick one regular outfield starter **not** in the top 3 (most
minutes among the rest, goalkeepers excluded), run A on him with the same
teammates-only ratio. Pool as in C. The report prints key-pooled vs
placebo-pooled side by side. Decision rule printed in the report:

> Signal is real if the key-player pooled interval does not contain the
> placebo pooled mean **and** the pooled effect is below 0.95.

Phase 2 goes ahead only if 2025-26 passes this rule. 2026-27 numbers are
informational either way.

## Outputs

- `data/backtest/key_absence_<season>.csv`: one row per (team, key player,
  bucket) with every number above.
- `data/backtest/key_absence_teammates_<season>.csv`: one row per
  (team, key player, teammate) with present/absent xG90, xA90, minutes.
- `docs/key_absence_<season>_<date>.md`: human report. Sections: selection
  list; league pooled effect vs placebo, with decision; per-team table sorted
  by shrunk effect; per-team "biggest movers"; caveats (n, transfers,
  inferred absence).

CLI:

```
python -m scripts.analyze_key_absence --season 2026-27 [--refresh] [--top 3] [--key-players ...]
python -m scripts.analyze_key_absence --season 2025-26
```

`--refresh` runs step 1 of data decisions for the current season only.

## Tests

`tests/test_analyze_key_absence.py`, synthetic fixtures:

- absence inferred correctly when the key player has no row for a fixture
  the team played; not inferred for fixtures the team did not play.
- transferred-player rows dropped when `team_id` not in the fixture pair.
- key selection ignores goalkeepers, returns exactly `top`, and a player
  with half the minutes but the same per-90 rate ranks the same.
- moved player: fixtures before first appearance for the club are neither
  present nor absent.
- partial fixture (one-sided or < 11 rows) is dropped, not counted absent.
- gating effect uses teammates-only xG: a key player who is 100% of team xG
  with unaffected teammates yields effect 1.0.
- effect ratio computed from `xg_ratio` not raw xG (construct a case where raw
  xG is lower in the absent bucket purely from tougher opponents and assert
  the ratio-based effect is ~1.0).
- placebo path runs and excludes the top-3.

## Phase 2 (not designed, gated)

If phase 1 passes on 2025-26: a per-(team, gw) attack multiplier driven by
FPL availability (`chance_of_playing_next_round`, `news`) for key players,
plus a teammate xGI multiplier, applied at the fixture level in
`projections.xg_team_difficulty_for_gw` / `output_model`, not via
`apply_knowledge_discount` (which is horizon-wide). Multiplier values come
from the pooled league effect, shrunk per team. Backtest-gated like every
other engine change (see `docs/roadmap_2026-27.md` and the harness-parity
caveat in memory).

## Left to the builder

- Exact rank-sum weighting across the five selection signals (equal weights
  default).
- Report formatting.
- Whether to cache the fixtures JSON next to the history file.

## Result (2026-10-27 run; numbers refreshed 2026-10-31 with MID/FWD-only key selection)

Reports: `docs/key_absence_2025-26_2026-10-31.md`, `docs/key_absence_2026-27_2026-10-31.md`.
The 2026-10-31 rerun drops defenders from the key selection (Gabriel, Botman,
Hall, Tarkowski, Murillo, Muñoz, Rice-adjacent picks were replaced by
Ødegaard, Wissa, Wood, Barry, Ndoye…). The 2025-26 whole-team pool moved
from 0.942 to 0.987 and the per-teammate pool from 0.973 to 0.988: with an
attacking-only key set the result is *weaker*, not stronger. Decision
unchanged: FAIL on both seasons.
Whole-team effect = absent / present ratio of team xG over fixture expectation
(opponent defence + venue controlled). Per-teammate effect = the same
teammate's xGI90 with vs without the key player (≥180 min in both), pooled
as a ratio of minutes-weighted means. 90% bootstrap intervals.

**Measurement correction found by running it.** The spec's "teammates-only"
ratio (team xG minus the key player's own, over expected) equals
`whole-team effect / (1 − key share)` whenever a replacement absorbs the
absentee's share, so it is inflated for better players and could never
produce an honest no (reviewer + advisor, independently). It is still
reported, with a share-adjusted column, but the gate is now the
per-teammate xGI90 pool, which is the quantity a phase-2 multiplier would
scale. Players who left the league (bootstrap `u` + "joined"/"loan" news:
Paquetá, Munetsi) are no longer counted absent for the rest of the season;
that moved the 2025-26 whole-team pool from 0.965 to 0.942.

| season | measure | key players | placebo (non-key regular starters) |
|---|---|---|---|
| 2025-26 (33 GWs) | whole-team xG | 0.987 [0.907, 1.060], 291 absences | 1.015 [0.973, 1.058], 658 absences |
| 2025-26 | per-teammate xGI90 | 0.988 [0.939, 1.036], 487 teammate rows | 1.000 [0.968, 1.032], 1271 rows |
| 2026-27 (GW1-8) | whole-team xG | 0.944 [0.723, 1.177], 27 absences | 1.021 [0.891, 1.167], 116 absences |
| 2026-27 | per-teammate xGI90 | 1.133 [0.786, 1.527], 41 rows | 0.932 [0.844, 1.021], 191 rows |

(2026-10-27 run, top-3 outfield incl. defenders: whole-team 0.942 [0.873, 1.013] vs 1.029; per-teammate 0.973 [0.923, 1.024] vs 1.016.)

**Decision: FAIL on 2025-26 (per-teammate gate: placebo inside the key
interval, shift 0.012 < 0.05). 2026-27 is underpowered (27 absences), not
evidence either way.**

Reading: over a full season a top-3 key player's absence costs his team
about 1% of whole-team xG with an attacking-only key set (6% when
defenders were admitted; placebo +2%), and the whole-team key interval
contains the placebo mean. But the players left on the pitch keep
their own xGI90 unchanged (0.99 vs placebo 1.00). The absentee's
share (15% on average for a top-3 pick, up to 38% for Isak) is mostly
absorbed by whoever replaces him, i.e. the player the engine's minutes
model promotes, not by the teammates the engine already projects. So:

- A league-wide "key player out → scale teammates" multiplier is not
  supported. Phase 2 as designed is **not unlocked**.
- The engine already zeroes the absent player; the ~1% gap between key and
  placebo on teammates is below the shift this analysis can resolve.

Per-team, 2026-27, sorted by shrunk whole-team effect (k = 4 toward 0.944):

| team | key player | present | absent | key share | whole-team effect | shrunk | xG/match present → absent |
|---|---|---|---|---|---|---|---|
| SUN | Brobbey | 6 | 2 | 0.30 | 0.186 | 0.692 | 1.78 → 0.40 |
| CHE | João Pedro | 6 | 2 | 0.33 | 0.440 | 0.776 | 1.52 → 0.66 |
| TOT | Sávio | 4 | 2 | 0.11 | 0.603 | 0.831 | 1.24 → 0.81 |
| LIV | Isak | 7 | 1 | 0.38 | 0.586 | 0.873 | 1.61 → 0.95 |

Chelsea / João Pedro: in his two absences (GW5, GW8) whole-team xG was 44%
of expectation; Rogers 0.52 → 0.24 xGI90 (180 absent min), Palmer 0.35 →
0.29 (169 absent min, under the 180 threshold so not in the teammate
table), Neto 0.41 → 0.22. Real in those two matches, but two matches shrink
to 0.78, and 2025-26 Chelsea without Palmer (11 absences) scored *more*
(whole-team 1.04). Player-specific dependencies exist; a pooled multiplier
does not.

Candidates for a per-pair rule (`n_absent ≥ 6`, shrunk whole-team effect
≤ 0.80), 2025-26: AVL Sancho (0.718, 9 absences), EVE Ndiaye (0.729, 6);
EVE Dewsbury-Hall sits on the bar (0.800, 7). 2026-27: none qualifies yet. Re-run each GW.

Sensitivity: with defenders admitted to the key set (2026-10-27 run) the
spec's original one-sided whole-team rule (< 0.95, placebo outside
interval) would have PASSED (0.942 [0.873, 1.013] vs 1.029); with the
attacking-only key set it fails on that measure too (0.987 [0.907, 1.060]
vs 1.015). That measure includes the absentee's own share, which the
engine already removes, so it is reported, not gated on.

Known weaknesses (deferred):
- Key selection is MID/FWD only since 2026-10-31; `--key-players` overrides
  per team (a threat-weighted selection is still an option).
- A key player who started but was substituted early counts as present.
- No `--season` vs bootstrap-season check on `--refresh`.
- Mean goals per bucket (spec §A, 2025-26 only) not implemented.
- CSV is one wide row per (team, key player) plus placebo rows flagged
  `placebo=True`, not one row per bucket.
