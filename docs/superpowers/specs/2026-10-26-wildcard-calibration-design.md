# Wildcard calibration: better projections, honest wildcard, quiet banner

Date: 2026-10-26. Backend repo `FPL` (master `1d656f1`) and frontend repo `fpl-decision-hub` (main `6d6d075`).

## Why

The user compared the GW9 wildcard draft with their own squad and gut feeling. Three Chelsea players and Barry felt wrong. The analysis that followed (2026-10-26, live data after GW8, entry 107342) found the feeling was partly right, and for reasons the user could not see on screen:

- **Projections are biased by price.** Comparing the stored pre-deadline `model_xpts` with actual points for GW3–GW8 (Supabase `player_gw_snapshots`): expensive attacking midfielders are over-projected and cheap regular starters under-projected.

  | Player | Projected (sum GW3–8) | Actual |
  |---|---|---|
  | B.Fernandes | 33.7 | 8 |
  | Palmer | 28.0 | 17 |
  | Saka | 29.2 | 17 |
  | Vuskovic | 26.7 | 46 |
  | Van Hecke | 20.8 | 36 |
  | Tavernier | 27.3 | 41 |
  | Evanilson | 21.6 | 34 |

  Per 60-minute appearance, the MID £8m+ band projects 4.70 against an actual 3.50. Two candidate causes, neither proven: the price prior still carries about 38% weight at GW9 (`PROJ_SHRINKAGE_GAMES` 5 against 8 games played, prior = `PROJ_PRICE_PRIOR_SLOPE` × price), and the xG-model half (weight `PROJ_MODEL_BLEND_WEIGHT` 0.7 since 22 Oct, 0.5 before) sits far below the output-based half for over-performers (GW9: Evanilson 4.93 vs 8.34, Neto 4.20 vs 7.65, Raya 3.40 vs 5.67). The pattern already existed at 0.5.
- **The captaincy bonus rewards captains who will never captain.** `add_wildcard_scores` gives every MID/FWD priced at or above `CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR` (£8.5m) a captaincy bonus. Palmer ranks about 9th among midfielders on weighted 5-GW xPts (18.7) and 2nd after a +3.72 bonus, while projecting 4.07 for GW9 against Haaland's 6.64.
- **Team strength ignores who is available.** João Pedro is doubtful (75%, P(60) 0.33) and the engine knows it, but Chelsea's attack rating and his teammates' outlooks are unchanged. The only lever is the hand-edited `data/models/knowledge_discount.json` (Chelsea last edited 26 Sep).
- **The wildcard can never be recommended.** `api/chips.py` builds the no-chip baseline with `allow_hits=True` and planner defaults (3 moves a GW) over the full 8-GW chip horizon, because `CHIP_PLAN_BASELINE_HEADLINE_SETTINGS` is False. `chip_advisor.score_wildcard` measures the wildcard over `CHIP_WILDCARD_DEFAULT_HORIZON_GWS` (5) and subtracts that 8-GW plan gain, then compares with a bar of 120 (`CHIP_PLAN_MIN_EV["wildcard"]`, a documented stopgap). GW9 snapshot for entry 107342: plan net gain 69.8; wildcard absent from recommendations.
- **The banner shows a meaningless number.** The main page shows "Wildcard · best week GW9: +0.6 xPts" every week. The user does not understand it and it takes space.

Full analysis tables: session scratchpad `an/findings_gw9.md` (not committed; the numbers above are the ones that matter).

## Goals

1. **Projections that match reality better,** judged on actual points. The price-band bias in the table above shrinks: premium attacking midfielders stop being over-rated, cheap regular starters stop being under-rated, without making overall accuracy worse.
2. **Team strength follows availability.** A doubtful or missing key player lowers his team's attack (or defence, for keepers and defenders) by his share of the team's output. That lowers his teammates' outlook and makes the fixture easier for opponents. It reverts automatically when he is back.
3. **No absurd captain logic.** Only a realistic captain earns the captaincy bonus in wildcard scoring.
4. **An honest wildcard verdict.** The chip planner compares the wildcard with the plan the user is actually shown, over the same weeks, against a reachable bar, so it can say "play it".
5. **A quiet main page.** No wildcard banner on ordinary weeks. One appears, in plain words, only when the planner says to play it this week.
6. **Monitoring.** Each finished GW, predictions are compared with actual points, broken down by position and price band and tagged with the model version that made them. This is internal only.

## Non-goals

- A public "track record" page. The user agreed it could become a differentiator later; it is a separate project once the numbers hold up.
- More "why" text on the screen. The user wants clearer, not more explanation.
- Suspension handling (a one-match ban currently removes a player from the whole window). Real but lower priority; Palmer's case was a cup match, which correctly does not affect league projections.
- Changing the three presets' identities (Aggressive / Balanced / Gems) or the draft builder's structure beyond the captaincy fix.

## Anti-goals

- Shipping a projection change because it looks right on one squad. Actual results decide. A change that wins a backtest but then loses to the following GWs' actual points is rolled back.
- Tuning on the same weeks used to judge the change without saying so.
- Hiding a regression in a single overall number. The price-band and position breakdown must be reported every time.

## Constraints

- All tunables live in `src/config.py`, tagged per the existing convention (`[untested]`, `[tuned]` with the evidence in the comment). The FPL rulebook in `src/rules.py` is never changed.
- The existing backtest harness does not match production (see the 2026-10-05 review noted in `CLAUDE.md`: the adapter sets `ep_next` to 0.0 while production blends it at 0.5; `scripts/backtest_season.py` carries its own constants). Any evidence used to change a projection setting must come from a harness that runs the production projection code with production config, with no future data leaking into a past GW.
- The `player_gw_snapshots` table holds only the final blended `model_xpts` per player per GW, not its parts. It cannot answer "what would a different setting have predicted" by itself; replays must recompute from as-of-GW data.
- Supabase migrations are applied by hand in the dashboard; ship the SQL file and say so.
- Use worktrees, never switch branches in the shared checkouts. One PR per repo. Run a security review on each diff before its PR.
- Match the existing frontend stack and patterns (React, TanStack Query, `WildcardCard`, `ChipNudgeCard`, the Chip step).

## Decided with the user

- **Order of work:** better projections first, then team strength from availability, then the captaincy fix, then the wildcard netting, then the frontend, with monitoring alongside.
- **Referee:** actual points. Before shipping, a change is tested on past weeks (this season and last). After shipping, every finished GW is compared with the prediction, per model version.
- **Monitoring is internal for now.**
- **Banner, option A:** silent on ordinary weeks; the wildcard sits in the Chip step with the other chips. A banner appears only when the chip planner recommends playing the wildcard this GW, worded like "Play your wildcard this week · about +14 pts over GW9–13 vs your planned transfers", with a button to the draft. The "Compare three wildcard squads" link stays reachable from the Chip step.
- **Availability affects opponents too:** a weakened team is an easier fixture for the other side.

## The parts

### 1. Projection calibration

Test, on a parity-correct replay of past GWs, three settings: how strongly the price prior pulls (`PROJ_SHRINKAGE_GAMES`, `PROJ_PRICE_PRIOR_SLOPE`), the xG-model weight (`PROJ_MODEL_BLEND_WEIGHT`), and how strongly fixtures move a projection (the difficulty multiplier table in `src/projections.py` and the opponent/team form factors). Report for each candidate: MAE, bias (mean predicted minus actual) and rank correlation, overall and per position × price band (<£6m, £6–8m, £8m+). Keep a change only if it reduces the price-band bias without worsening overall MAE. The `[tuned]` config comment cites the run.

### 2. Availability-adjusted team strength

For each team and GW, derive an availability factor from FPL status / `chance_of_playing_next_round` and each player's share of the team's recent attacking output (xG + xA) and, for defence, the keeper's and defenders' share of minutes. Apply it to the team's attack and defence ratings for the GWs the absence is expected to cover, so both teammates' and opponents' projections move. The prior manual nudge in `knowledge_discount.json` stays and composes with it.

### 3. Captaincy bonus for the realistic captain

Only players who could plausibly be the squad's captain earn the bonus. The fix must make the GW9 case come out right: Palmer (4.07 next GW) earns nothing while Haaland (6.64) is in the market. A regression test pins that case.

### 4. Wildcard netting

The baseline plan uses the headline-plan settings (no hits, free-transfer-bounded moves, the horizon-scaled bar). The wildcard uplift and the plan gain are measured over the same GWs. The bar `CHIP_PLAN_MIN_EV["wildcard"]` is recalibrated with stated evidence so that it reads "hold" on ordinary weeks and is reachable for a genuinely broken squad. Guidance copy in `_chip_guidance` is updated to match. Tests cover the window match and the hits-free baseline.

### 5. Frontend: quiet banner

`Index.tsx` shows the wildcard banner only when the chip plan recommends the wildcard for the deadline GW. The current every-week `WildcardCard` with "best week … +x xPts" goes. Copy is plain words with a whole-number gain and the GW range. The wildcard remains selectable in the Chip step, which keeps the link to the three-squad page.

### 6. Monitoring

Add a model version to every snapshot row (`player_gw_snapshots` gains a column filled by `scripts/snapshot_to_db.py` from a version string the API reports). After each GW's actuals are filled, a report gives per-version MAE, bias and rank correlation by position and price band, plus captain-pick hit rate. Output goes to the internal admin surface or a script the user can run; no user-facing page.

## Left to the builder

- The exact replay harness design, as long as it uses production code paths and config with no future leak.
- How the availability factor is computed and decayed across GWs.
- The exact captain-plausibility rule.
- The recalibrated wildcard bar value, with its evidence.
- Where the monitoring report lives (admin route, script, or both) and its format.
- How the work is split into PRs, within one PR per repo per phase.
