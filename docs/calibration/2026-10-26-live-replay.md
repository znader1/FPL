# Live-season replay, 2026-10-26

Production projection code (master `1d656f1` + `PROJ_FDR_STRENGTH`, default 1.0) replayed on the 2026-27 finished gameweeks from the stored pre-deadline snapshots (`scripts/backtest_live_season.py`). Population: every player-GW whose team had a fixture, benched and zero-minute included.

## The harness reproduces production

Replaying GW8 with today's settings against the `model_xpts` production stored before the GW8 deadline: n 668, mean |difference| **0.026** pts, correlation **0.999**. Verdicts below are production verdicts, not a different model's.

## 1-GW error (tune GW3–6, hold-out GW7–8, 27 candidates)

| Setting | Tune MAE | Hold-out MAE | Hold-out band bias | MID £8m+ bias (pts/GW) |
|---|---|---|---|---|
| Current (shrink 5, blend 0.7, fixtures 1.0) | 1.226 | 1.192 | 0.156 | +2.13 |
| Shrink 0, blend 0.5, fixtures 2.0 | 1.196 | 1.178 | 0.103 | +2.20 |
| Shrink 0, blend 0.6, fixtures 2.0 | 1.199 | 1.176 | 0.118 | +2.18 |
| Shrink 0, blend 0.7, fixtures 2.0 | 1.205 | 1.174 | 0.133 | +2.15 |

All 27 candidates pass the 1% MAE gate. Shrinkage 0 beats the current setting in five of six weeks (GW3 is level). Blend weight and fixture strength move MAE by less than 0.01.

## 5-GW error (the wildcard's horizon; windows GW3–7 and GW4–8 only)

| Setting | MAE (5-GW sum) | Bias (5-GW sum) | Band bias | MID £8m+ bias |
|---|---|---|---|---|
| Current (shrink 5) | 4.95 | +1.56 | 1.51 | +6.6 |
| Shrink 2.5 | 4.83 | +1.39 | 1.35 | +7.1 |
| Shrink 0 | 4.53 | +0.87 | 0.87 | +8.9 |

Fixture strength 2.0 changes nothing here. Two windows is thin; both start early in the season, when the price prior carries the most weight (71% at GW3, 38% at GW9), so the effect at GW9 onward is smaller than this table.

## Last season (NON-PARITY: 2025-26 Vaastav, no ep_next or availability)

Blend 0.5 / 0.6 / 0.7: MAE 1.916 / 1.915 / 1.922 over GW6–38. A tie, as in every earlier sweep.

## What it means in plain words

- **Turning the price pull off makes projections more accurate overall,** about 2% on a single week and up to 8% over five weeks. Cheap players who are actually playing well stop being dragged down towards "what a £4.5m player normally scores".
- **It does not fix the premium-midfielder problem, and makes it slightly worse.** That bias is not about price. Four players carry it: B.Fernandes (projected 35.9 over GW3–8, scored 8), Saka (31.3 vs 17), Palmer (27.4 vs 17) and Gibbs-White (13.9 vs 4 in three games). Every part of the model rates them highly, the xG half least of all (+1.3/GW against +1.9 for the output half). Barcola and Semenyo go the other way. That reads as a few players underperforming their underlying numbers, part variance and part form the model can't see, not a setting that is wrong.
- **The xG weight (0.5–0.7) and fixture strength don't matter** within the tested ranges. `PROJ_FDR_STRENGTH` only moves the output half of the blend, about 30% of a projection at 0.7, so a flat result means this knob is weak, not that fixtures don't matter.
- **A correction to the earlier analysis:** "cheap regular starters are under-projected" was partly an artefact of looking only at players who played 60+ minutes. Across everyone with a fixture, cheap players' bias is close to zero; the model hedges minutes risk, so it is low when they play and high when they are benched.

## As-of rerun after review (knowledge file off, 2026-10-26)

The first run used today's `knowledge_discount.json` for every replayed GW, which encodes facts learned after GW3–4. The replay now runs without it. The price-pull comparison, rerun as-of:

| Price pull (`PROJ_SHRINKAGE_GAMES`) | 1-GW tune MAE | 1-GW tune band bias | 5-GW MAE | 5-GW band bias | MID £8m+ bias, 5-GW |
|---|---|---|---|---|---|
| 5 (before) | 1.223 | 0.299 | 4.94 | 1.53 | — |
| **2.5 (shipped)** | **1.216** | **0.294** | **4.81** | **1.37** | +7.1 |
| 0 | 1.201 | 0.288 | 4.52 | 0.89 | +8.8 |

Same conclusion as above. Players without a snapshot row for a GW are dropped from that GW, never defaulted: 15 at GW3, 10 at GW4, 1–2 from GW5 on (new and late-registered players).

Parity note: GW8's stored projections were made with the price pull at 5, so `--parity-gw 8` now needs `--grid "PROJ_SHRINKAGE_GAMES=5"`-style overrides on the parity call, or a GW produced by the shipped version, to read near zero again.

## Options

1. **Ship shrinkage 0** (price pull off): best accuracy, slightly worse on premium midfielders.
2. **Ship shrinkage 2.5** (half the price pull): about half the gain, premium bias roughly unchanged.
3. **Ship nothing yet** and let monitoring collect more weeks first.

Blend 0.7 and fixture strength 1.0 stay either way. The premium-midfielder issue needs a player-level answer (for example, weighting a player's recent output gap against his xG), which is a separate design.
