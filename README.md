# Roll Yield — Interim Migration (LSEG)

Interim replacement for `ICEBREAKER/Roll Yield`, rebuilt against the **LSEG
Data API** (`lseg.data`) instead of ICE Connect (`icepython`), for the period
while ICE API access is unavailable. Produces a daily carry/roll-yield
dataset across 11 commodities — softs (KC, RC, CC, LCC, SB, CT, W) plus
grains (ZC corn, ZW wheat, KE Kansas wheat) and orange juice (JO).

## What's here

- **`Code/ingest_lseg.py`** — the ingest pipeline. Same structure as the ICE
  source (single script, mode auto-detected from whether the output parquet
  exists — no separate backfill/incremental scripts), same output schema,
  same `Roll_Yield_1yr = Spot/OneYr - 1` formula, same per-commodity curve
  positions for Spot/OneYr **except RC and JO** (see below).
- **`Database/roll_yield_data.parquet`** — `Date, Commodity, Spot, OneYr,
  Roll_Yield_1yr, c1..c8`, full history from 2016.
- **`Dashboard/app.py`** — copied verbatim from the ICE source (pure parquet
  consumer, no ICE dependency, confirmed by grep). Roll Yield and Roll Cost
  tabs.
- **`Automater/`** — `run.bat` (daily ingest + git push + email),
  `send_mail.py`.

## Where this deliberately deviates from the ICE source

`c1..c8` are each commodity's Nth-nearby continuation contract. On ICE
Connect these are dense every day out to c8 for every commodity. On LSEG,
two of the eleven don't have usable daily data that far out the curve —
checked empirically over 2020-2026:

| Commodity | ICE's OneYr index | LSEG density at that index | LSEG's OneYr index used here | Density |
|---|---|---|---|---|
| RC (Robusta) | c8 | ~42% | **c6** | ~91% |
| JO (Orange Juice) | c7 | ~3.5% | **c4** | ~64% |

Every other commodity's OneYr index (KC c7, CC c7, LCC c7, SB c5, CT c7, W
c6, ZC c6, ZW c6, KE c6) has 75–99.5% density on LSEG and was kept unchanged.
Validated against the ICE archive: correlation on `Roll_Yield_1yr` is
0.94–0.9998 for nine of the eleven commodities; RC (0.987) and JO (0.884) are
the two exceptions, and that's expected, not a bug — they're now measuring a
genuinely nearer-dated carry than ICE's version for those two, because
LSEG's own data doesn't support anything further out. JO in particular
should be treated as the least reliable series here even after the fix — c4
is the best available point, not a fully solved one.

`_fetch_curve()` also reindexes each curve leg onto the union of dates any
leg has data for that commodity, and linearly interpolates strictly-internal
gaps (never extrapolating past a leg's own first/last real print) — the same
treatment used in the Rollex migration for the same underlying issue
(individual curve legs having their own small gaps on days others don't).

## Running it

```bash
python Code/ingest_lseg.py
streamlit run Dashboard/app.py
```

Requires an authenticated LSEG Workspace/Eikon session on the host running
the ingest script.
