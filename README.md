# Roll Yield — Interim Migration (LSEG)

Interim replacement for `ICEBREAKER/Roll Yield`, rebuilt against the **LSEG
Data API** (`lseg.data`) instead of ICE Connect (`icepython`), for the period
while ICE API access is unavailable. Produces a daily carry/roll-yield
dataset across 12 commodities — softs (KC, RC, CC, LCC, SB, CT, W) plus
grains (ZC corn, ZW wheat, KE Kansas wheat), orange juice (JO) and B3/BM&F
Arabica (BMF).

## What's here

- **`Code/ingest_lseg.py`** — the ingest pipeline. Same structure as the ICE
  source (single script, mode auto-detected from whether the output parquet
  exists — no separate backfill/incremental scripts), same output schema,
  same `Roll_Yield_1yr = Spot/OneYr - 1` formula, same per-commodity curve
  positions for Spot/OneYr **except RC and JO** (see below).
- **`Database/roll_yield_data.parquet`** — `Date, Commodity, Spot, OneYr,
  Roll_Yield_1yr, c1..c8`, full history from 2016.
- **`Dashboard/app.py`** — pure parquet consumer, no ICE dependency. Three
  tabs: **Roll Yield** (copied verbatim from the ICE source), plus **BMF
  Arabica** and **KC vs BMF Diff**, added Aug-2026. The ICE source's Roll
  Cost tab was dropped Aug-2026 — the BMF tab still carries a roll-cost
  readout for that contract.
- **`Database/fx_brl.parquet`** — `Date, USDBRL`. Written by the same ingest;
  consumed only by the diff tab, which treats it as optional.
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
| BMF (B3 Arabica) | c7 (by analogy to KC) | ~6% | **c5** — deliberately a 6m carry | ~99% (filled) |

Every other commodity's OneYr index (KC c7, CC c7, LCC c7, SB c5, CT c7, W
c6, ZC c6, ZW c6, KE c6) has 75–99.5% density on LSEG and was kept unchanged.
Validated against the ICE archive: correlation on `Roll_Yield_1yr` is
0.94–0.9998 for nine of the eleven commodities; RC (0.987) and JO (0.884) are
the two exceptions, and that's expected, not a bug — they're now measuring a
genuinely nearer-dated carry than ICE's version for those two, because
LSEG's own data doesn't support anything further out. JO in particular
should be treated as the least reliable series here even after the fix — c4
is the best available point, not a fully solved one.

### BMF — B3/BM&F Arabica (added Aug-2026)

The LSEG continuation root is **`ICF`**, not `IFC` — `IFCc1` returns
*"universe is not found"*.

BMF is **deliberately not a 1-year number**, and it lives on its own third
dashboard tab rather than in the cross-commodity charts. B3 Arabica rolls on
the same five months as KC (H/K/N/U/Z), so the 1yr point from c2 would be c7
— but `ICFc7` has no prints before Mar-2023 and is only ~30% dense even after
gap-filling. B3's curve is genuinely liquid only to about c5, so BMF is
quoted here as a **6-month carry (c2 vs c5)** instead:

| Leg | ~months out from c2 | density (filled) | 2024+ | last real print (Aug-2026) |
|---|---|---|---|---|
| c4 | ~4.8 | 98.8% | 96.4% | 23-Jul — goes stale for weeks |
| **c5** | ~7.2 | **99.1%** | **99.2%** | **19-Aug** |
| c6 | ~9.6 | 96.8% | 98.8% | 14-Aug |
| c7 | ~12 (the "real" 1yr) | 29.9% | — | 21-May |

6 months falls between c4 and c5; c5 is the better-behaved side. Switching
from c6 to c5 also removed a +56% outlier in the history that was a
stale-deep-leg artifact — the c5 series runs −19.0% to +26.4%.

The column keeps the shared schema name `Roll_Yield_1yr`; only the dashboard
labelling says 6-month. If the 1yr point is ever wanted, revisit once `ICFc7`
has a few more years of prints.

**Units.** Quoted in **USD per 60kg bag**, **100 bags per lot**, so the raw
`c2−c1` spread is USD/bag and is *not* unit-comparable to the cents/lb and
$/tonne contracts on the other tabs. The `$/Lot` figure (`lot_mult` 100) is
the comparable one. Carry is a ratio and is comparable as-is, subject to the
6m-vs-1yr caveat above.

**Known gaps.** `ICFc4` in particular can sit unprinted for weeks (last print
23-Jul as of 27-Aug-2026) — the forward-curve chart coerces those to `None`
and bridges the gap with `connectgaps`. `build()` never extrapolates past a
leg's last real print, so BMF's series can also end a few days behind the
other eleven commodities. The BMF tab reads its own latest row, so it is
unaffected; it is simply absent from tabs 1-2 by construction.

### KC vs BMF Diff tab (added Aug-2026)

`KC c2 − BMF c2`, both in US cents/lb (BMF converted at 132.2774 lb per 60kg
bag). Same physical commodity, same five months, so the difference reads as a
**Brazil differential proxy** — origin diff, internal logistics, BRL,
financing. It is *not* an arb: delivery does not cross between B3 and ICE.

**Front month only, deliberately.** B3 is too thin past ~c3 for a deferred-leg
diff to carry information rather than staleness.

What the history says (2016-02 to 2026-08, 2,545 overlapping days):

| | |
|---|---|
| Mean / sd | **+15.6** / 6.6 c/lb |
| Range | −27.9 to +56.5 |
| Level correlation | 0.997 |
| Daily-**return** correlation | **0.79** — ~20% of the daily move is idiosyncratic |
| AR(1) half-life | **~8 business days** |
| sd, 2017-19 -> 2024-26 | 2.5-3.5 -> **8-10** (materially looser since 2020) |

**Like-for-like carry panel.** The tab also compares `KC c2/c5` against
`BMF c2/c5`. Both contracts roll H/K/N/U/Z, so `c2 -> c5` is three contract
gaps (~7.2 months) on *each* — the same tenor. This matters: the Roll Yield
tab measures KC at `c2/c7` (~12 months), so KC's headline carry there is
**not** comparable to BMF's, and pairing them would show a ~0.5pp gap that is
pure tenor rather than any market difference (KC's own c2/c7 and c2/c5 differ
by -0.53% on average). Carry is a ratio, so no unit conversion applies.

Full history (n=2,545): KC c2/c5 averages -1.18% (sd 5.36%), BMF -0.47% (sd
7.68%), correlation 0.86. The spread averages -0.71% with an ~11 business-day
AR(1) half-life. It is close to **orthogonal to the price differential**
(r = 0.14 on levels, 0.19 on changes) — so it is genuinely separate
information, not a repackaging: the diff says how cheap Brazil is, the carry
spread says which market is tighter.

**On the BRL panel — read it with low expectations.** Correlating *daily
changes* (not levels: both series are persistent enough that a level
correlation would mostly report trend), the full-period r is only **−0.13**,
and the rolling 120d window ranges about −0.36 to +0.25. The BRL link is
weaker at daily frequency than desk folklore suggests; it may still matter at
lower frequency or via export pace, which this tab does not model. Export
pace lives in the separate Cecafe-Monthly project and was deliberately not
wired in here.

## Running it

```bash
python Code/ingest_lseg.py     # writes both roll_yield_data.parquet and fx_brl.parquet
streamlit run Dashboard/app.py
```

Filters (commodity multiselect, date range) live in the native Streamlit
sidebar, open by default.

The two cached loaders take the parquet's mtime as a cache-key argument.
`st.cache_data` keys only on a function's arguments, and the ingest rewrites
these files in place — without the mtime, a long-running app keeps serving its
previous load for up to an hour after a rebuild. Note the receiving parameter
must NOT be underscore-prefixed: Streamlit excludes those from hashing, which
would silently defeat it.

Requires an authenticated LSEG Workspace/Eikon session on the host running
the ingest script.
