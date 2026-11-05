# Monitoring backfill: dry-run check, 2026-11-05

What the backfill produced on real data before anything was written to the database, and what is still unverified. Plan: `docs/superpowers/plans/2026-11-05-monitoring-data-backfill.md`, Task 9.

## What was run

| Run | Command | Data |
|---|---|---|
| A | `monitor_backfill.py --gws 1-10 --skip-replay --out-dir …` | Real FPL API and Scout feed, both entries. No stored projections (no database access from the laptop), so no app columns. |
| B | `monitor_backfill.py --gws 9 --entries 107342 --snapshots-csv <extract> --out-dir …` | Real engine, advice rebuilt. Snapshot extract = 174 of GW9's 670 rows (the test fixture plus the engine's input columns), so the app's eleven is exact but the rebuilt advice chose from a reduced market. |

Nothing was written to Supabase in either run.

## Results against known facts

| Check | Expected | Got |
|---|---|---|
| Owner's scores GW1–GW9 (entry 107342) | 56, 84, 49, 90, 42, 75, 76, 32, 64 | same |
| GW9 Scout eleven, no captain | 69 | 69 |
| GW9 best possible eleven | 115 | 115 |
| GW9 app eleven (run B) | 70 (the eleven worked out by hand in the spec) | 70, same eleven, Haaland captain |
| GW9 owner's transfer, 1 gameweek | +15 (Maguire → Van Hecke) | +15 |
| GW1 app column | unavailable | "no pre-deadline snapshot" |
| GW7 | chip week, no transfer line | `chip_week: true` |
| Scout Selection GW2–GW10 | 9 articles, 11 players each | 9, all 11, all names matched |
| Transfer radar GW1–GW10 | 10 articles | 10, 4 tips each, all names matched |
| Squad articles | GW1 season squad, wildcard GW2, 3, 4, 6 | all 5 found, flagged for review |

Transfer gains were recomputed independently from FPL's live endpoint for GW3, GW4, GW5 and GW6 and agree (GW3 −15, GW4 0, GW5 0, GW6 +4 over three gameweeks).

## Scout Selection, as parsed

| GW | Captain | Vice | Stated | Points (headline basis) |
|---|---|---|---|---|
| 2 | Bruno Fernandes | Erling Haaland | yes | 96 with captain |
| 3 | Erling Haaland | Rayan Cherki | yes | 60 with captain |
| 4 | Cole Palmer | Joao Pedro | yes | 80 with captain |
| 5 | Erling Haaland | Morgan Gibbs-White | yes | 57 with captain |
| 6 | Bukayo Saka | Erling Haaland | yes | 38 with captain |
| 7 | Erling Haaland | Bukayo Saka | yes | 64 with captain |
| 8 | Erling Haaland | Cole Palmer | yes | 48 with captain |
| 9 | none stated (Haaland inferred) | | no | 69 without captain |
| 10 | Erling Haaland | Alexander Isak | yes | before deadline |

Each captain and vice was checked by reading the sentence in the article.

## What the dry run changed

1. **Captain wording.** The plan's rule looked for "named captain" and matched only GW10. The Scout states the captain every week in different words ("earns the captain's armband", "is handed the armband", "is selected as captain", "given the vice-captaincy"). The rule is now: the sentence containing "vice-captain" that names exactly two listed players; first is captain, second is vice.
2. **Captain inference.** The original fallback (any section mentioning "captaincy" or "armband") would have named the wrong player in GW3, GW7 and GW8 had no statement existed (a team-mate called "an alternative for the captaincy"). It is now limited to sections that discuss the decision itself.
3. **Club names.** "Coventry" and "Hull" did not resolve to Coventry City and Hull City. A unique whole-word prefix now resolves.
4. **First names.** "Dan Ballard" did not match Daniel Ballard. A shortened first name with a full surname match now resolves, only when one player at the club fits.
5. **One spelling override.** The GW5 article spells Mbeumo "Mbuemo". Not guessed: one entry in `data/monitoring/scout_overrides.json`.

## The five squads that cannot be parsed

The season squad and the wildcard squads are not in the article text at all: the fifteen are a graphic embedded in the page. Each graphic was read by eye on 2026-11-05 and entered in `data/monitoring/scout_overrides.json` with `confirmed_by_owner: false`. Each sums to £100.0m or less at the prices shown, which supports the reading. **They are not scored until the owner confirms them.**

| GW | Article | Fifteen as read (total at the prices shown) |
|---|---|---|
| 1 | [4681112](https://www.premierleague.com/en/news/4681112) | Kinsky, Dubravka; Gabriel, Mosquera, Maguire, Greaves, Thomas; B.Fernandes, Mbeumo, Tzolis, Groß, M.Sangaré; Haaland, João Pedro, Kusi-Asare (£100.0m) |
| 2 | [4698173](https://www.premierleague.com/en/news/4698173) | Raya, Dubravka; Gabriel, Tarkowski, Bijol, Ajer, Konsa; Palmer, Szoboszlai, Dewsbury-Hall, Stach, M.Sangaré; Haaland, João Pedro, Walle Egeli (£100.0m) |
| 3 | [4705463](https://www.premierleague.com/en/news/4705463) | Verbruggen, Steele; Ajer, Dedić, Konsa, Egan, Thomas; B.Fernandes, Palmer, Cherki, Szoboszlai, Slater; Haaland, João Pedro, Wissa (£99.9m) |
| 4 | [4712921](https://www.premierleague.com/en/news/4712921) | Raya, Dubravka; Gabriel, Ajer, Elvedi, Konsa, Thomas; Palmer, Mbeumo, Dewsbury-Hall, Stach, Janelt; Haaland, João Pedro, Wissa (£99.8m) |
| 6 | [4726681](https://www.premierleague.com/en/news/4726681) | Raya, Dubravka; Muharemović, Vuskovic, Konsa, Affengruber, Thomas; Palmer, Saka, Schade, Tavernier, Groß; Haaland, João Pedro, Gonzalo (£99.8m) |

"Thomas" is Bobby Thomas (Coventry); "Konsa" and "Tzolis" are Arsenal players this season; "Dubravka" is at Spurs. To confirm one, set its `confirmed_by_owner` to `true` in the overrides file and rerun the backfill.

## Run B: the rebuilt advice (illustrative, reduced market)

- Transfer plan for GW9: Calafiori → Silva ("Move now", +3.6 this gameweek, +8.1 over GW9–11 projected); real gain after one gameweek +2. The owner's own move scored +15.
- Wildcard drafts: all three presets built; kept squad 67, Balanced draft 73 after one of five gameweeks.
- Buy lists after one gameweek: app 5.0 points per player, Scout radar 8.75.
- `dropped_squad_ids: [418]`: Maguire, held before GW9, is not in the 174-row extract. Expected here; the full table has him.
- Parity: "no same-version baseline" (GW9 predates the model version column).

## Not yet verified

- **Rebuilt advice on the full snapshot table.** The laptop has no database credentials, so the replay ran only on the GW9 extract. The first workflow run is the full check; verify with the query in the plan (Task 9, step 10).
- **The feed from a GitHub runner.** Reachable from the laptop; the runner is untested. If it is blocked the run says so, stores no Scout rows and exits non-zero.
- **GW10.** Its deadline is 2026-11-06 18:30 GMT. Run it after that.
- **Entry 5645321** produced a report for every gameweek in run A; its numbers were not checked against anything.
