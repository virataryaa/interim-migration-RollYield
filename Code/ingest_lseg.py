"""
Roll Yield Ingest — LSEG (interim migration)
================================================
LSEG-API replacement for ICEBREAKER/Roll Yield/Code/ingest.py (icepython-
based). Same structure, same output schema, same per-commodity curve-index
choices for Spot/OneYr (carried over unchanged — these are ICE Connect's
Nth-nearby continuation points, and LSEG's own `<root>c<N>` continuation
RICs are the direct equivalent, so no re-derivation was needed).

Output: ../Database/roll_yield_data.parquet
Schema: Date, Commodity, Spot, OneYr, Roll_Yield_1yr, c1-c8

Also writes ../Database/fx_brl.parquet (Date, USDBRL) — used only by the
dashboard's KC-vs-BMF diff tab, and treated as optional there.

Usage:
    python ingest_lseg.py
(mode — full history vs incremental upsert — is auto-detected from whether
the output parquet already exists, same as the ICE original.)
"""
import datetime
import logging
import pandas as pd
pd.set_option("future.no_silent_downcasting", True)  # silences a harmless lseg.data internal FutureWarning
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

OUT        = Path(__file__).parent.parent / "Database" / "roll_yield_data.parquet"
# USD/BRL, kept in its own file rather than shoehorned into the c1-c8 schema.
# Only consumer is the dashboard's KC-vs-BMF diff tab, which treats it as
# optional — if this parquet is missing the tab just drops the BRL panels.
FX_OUT     = Path(__file__).parent.parent / "Database" / "fx_brl.parquet"
FX_RIC     = "BRL="
TODAY      = datetime.date.today().isoformat()
FULL_START = "2016-01-01"

# (key, name, spot_idx, yr1_idx, LSEG continuation root)
# spot_idx/yr1_idx are 1-based curve positions (c<idx>), carried over
# unchanged from the ICE source's per-commodity index choices EXCEPT RC and
# JO: LSEG's own far-dated continuation RICs for these two are too sparse to
# use as a daily series (checked empirically over 2020-2026: RCc8 is only
# ~42% populated, OJc7 only ~3.5%, OJc8 ~0.5% — nowhere near dense enough to
# treat as real daily data, vs. 90%+ for every other index used here). Moved
# RC's OneYr from c8 to c6 (~91% dense) and JO's from c7 to c4 (~64% dense,
# the best available beyond c3 — still the weakest point in this dataset and
# worth treating JO's Roll_Yield_1yr with more caution than the rest).
#
# BMF (B3/BM&F Arabica, root ICF — NOT IFC) is deliberately NOT a 1yr number.
# It rolls on the same five months as KC (H/K/N/U/Z), so the 1yr point from
# c2 would be c7 — but ICFc7 has no prints before Mar-2023 and is ~30% dense
# even after gap-filling. B3's curve is only genuinely liquid out to ~c5, so
# BMF is quoted here as a **6-month carry** instead. c5 is ~7.2m out from c2
# (99% dense, 2024+ 99.2%); c4 is ~4.8m and closer to a literal 6m but sits
# stale for weeks at a time (last print 23-Jul vs c5's 19-Aug as of Aug-2026),
# so c5 is the better-behaved side of the 6m mark. Its Roll_Yield_1yr column
# keeps the shared schema name but the dashboard labels it as 6-month.
# Quoted in USD per 60kg bag, 100 bags/lot (see lot_mult in the dashboard).
COMMODITIES = [
    ("KC",  "Arabica",     2, 7, "KC"),
    ("RC",  "Robusta",     2, 6, "LRC"),
    ("CC",  "NYC Cocoa",   2, 7, "CC"),
    ("LCC", "LDN Cocoa",   2, 7, "LCC"),
    ("SB",  "Sugar",       1, 5, "SB"),
    ("CT",  "Cotton",      2, 7, "CT"),
    ("W",   "White Sugar", 1, 6, "LSU"),
    ("ZC",  "Corn",        1, 6, "C"),
    ("ZW",  "Wheat",       1, 6, "W"),
    ("KE",  "KC Wheat",    1, 6, "KW"),
    ("JO",  "OJ",          2, 4, "OJ"),
    ("BMF", "BMF Arabica", 2, 5, "ICF"),   # ~6m carry, not 1yr — see note above
]


def _start() -> tuple[str, bool]:
    if OUT.exists():
        last = pd.to_datetime(pd.read_parquet(OUT, columns=["Date"])["Date"]).max().date()
        start = (last - datetime.timedelta(days=10)).isoformat()
        log.info(f"Incremental: from {start} (last={last})")
        return start, True
    log.info(f"Full history from {FULL_START}")
    return FULL_START, False


def _fetch_curve(ld, root: str, start: str) -> dict:
    """Fetch c1..c8 for one commodity. Tries a single batched multi-RIC call
    first (fast); falls back to per-RIC fetches for anything missing from
    the batch response (mirrors the retry pattern used in the COT/Rollex
    migrations)."""
    rics = [f"{root}c{n}" for n in range(1, 9)]
    out = {}
    try:
        df = ld.get_history(universe=rics, fields=["TRDPRC_1"], start=start, end=TODAY,
                             interval="daily", count=10000)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            for n, ric in enumerate(rics, start=1):
                if ric in df.columns:
                    out[n] = df[ric].dropna()
    except Exception as e:
        log.warning(f"  {root}: batch fetch failed ({e}) — falling back to per-RIC")

    missing = [n for n, ric in enumerate(rics, start=1) if n not in out]
    for n in missing:
        ric = f"{root}c{n}"
        try:
            d = ld.get_history(universe=[ric], fields=["TRDPRC_1"], start=start, end=TODAY,
                                interval="daily", count=10000)
            if d is None or d.empty:
                continue
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = [c[0] for c in d.columns]
            out[n] = d.iloc[:, 0].dropna()
        except Exception as e:
            log.warning(f"  {ric}: {e}")

    if not out:
        return out
    # Different curve legs can each have their own small gaps (a leg not
    # printing on a day the others did). Reindex onto the union of dates any
    # leg actually has, then linearly interpolate strictly-internal holes
    # (never extrapolating past a leg's own first/last real print) — same
    # treatment used in the Rollex migration for the same underlying issue.
    full_idx = sorted(set().union(*(s.index for s in out.values())))
    for n in list(out.keys()):
        out[n] = out[n].reindex(full_idx).interpolate(method="linear", limit_area="inside")
    return out


def fx_brl(ld, start: str) -> pd.DataFrame:
    """USD/BRL daily mid. Returns empty on failure — the FX leg is a nice-to-have
    for the diff tab and must never take the whole ingest down with it."""
    try:
        d = ld.get_history(universe=[FX_RIC], fields=["MID_PRICE"], start=start,
                           end=TODAY, interval="daily", count=10000)
    except Exception as e:
        log.warning(f"  {FX_RIC}: {e} — skipping FX")
        return pd.DataFrame()
    if d is None or d.empty:
        log.warning(f"  {FX_RIC}: no data — skipping FX")
        return pd.DataFrame()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] for c in d.columns]
    out = d.iloc[:, 0].dropna().rename("USDBRL").to_frame()
    out.index.name = "Date"
    out = out.reset_index()
    log.info(f"  USD/BRL: {len(out)} rows | last = {out['USDBRL'].iloc[-1]:.4f}")
    return out


def save_fx(new: pd.DataFrame):
    if new.empty:
        return
    if FX_OUT.exists():
        old = pd.read_parquet(FX_OUT)
        old["Date"] = pd.to_datetime(old["Date"])
        old = old[old["Date"] < new["Date"].min()]
        new = pd.concat([old, new], ignore_index=True)
    new = new.sort_values("Date").drop_duplicates("Date", keep="last")
    new.to_parquet(FX_OUT, index=False)
    log.info(f"Saved {len(new):,} FX rows -> {FX_OUT}")


def build(ld, start: str) -> pd.DataFrame:
    rows = []
    for comm, name, spot_idx, yr1_idx, root in COMMODITIES:
        log.info(f"{name} ({comm})")
        curve = _fetch_curve(ld, root, start)
        if spot_idx not in curve or yr1_idx not in curve:
            log.warning(f"  {comm}: missing Spot(c{spot_idx}) or OneYr(c{yr1_idx}) — skipping")
            continue

        df = pd.DataFrame({f"c{n}": s for n, s in curve.items()})
        df = df.dropna(subset=[f"c{spot_idx}", f"c{yr1_idx}"])
        if df.empty:
            log.warning(f"  {comm}: no data — skipping")
            continue

        df.index.name = "Date"
        df = df.reset_index()
        df["Commodity"]      = comm
        df["Spot"]           = df[f"c{spot_idx}"]
        df["OneYr"]          = df[f"c{yr1_idx}"]
        df["Roll_Yield_1yr"] = df[f"c{spot_idx}"] / df[f"c{yr1_idx}"] - 1
        keep = ["Date", "Commodity", "Spot", "OneYr", "Roll_Yield_1yr"] + [f"c{i}" for i in range(1, 9)]
        rows.append(df[[c for c in keep if c in df.columns]])
        log.info(f"  {len(df)} rows | roll = {df['Roll_Yield_1yr'].iloc[-1]:.2%}")

    if not rows:
        log.error("All commodities returned no data")
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def save(new: pd.DataFrame, incremental: bool):
    if incremental and OUT.exists():
        old = pd.read_parquet(OUT)
        old["Date"] = pd.to_datetime(old["Date"])
        # Per-commodity cutoff — avoids gaps if one commodity returns fewer days
        filtered = old.copy()
        for comm, grp in new.groupby("Commodity"):
            cutoff = grp["Date"].min()
            filtered = filtered[~((filtered["Commodity"] == comm) & (filtered["Date"] >= cutoff))]
        df = pd.concat([filtered, new], ignore_index=True).sort_values(["Commodity", "Date"])
        log.info(f"Upserted {len(new)} rows into {len(filtered)} existing")
    else:
        df = new
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    log.info(f"Saved {len(df):,} rows -> {OUT}")
    log.info(f"Range: {df['Date'].min().date()} -> {df['Date'].max().date()}")


if __name__ == "__main__":
    import sys
    log.info("=" * 50 + f"\nRoll Yield Ingest (LSEG) | {TODAY}\n" + "=" * 50)

    import lseg.data as ld
    ld.open_session()
    try:
        start, incremental = _start()
        new = build(ld, start)
        log.info("USD/BRL")
        fx = fx_brl(ld, FULL_START if not FX_OUT.exists() else start)
    finally:
        ld.close_session()

    save_fx(fx)

    if new.empty:
        log.error("Nothing to save — exiting with error")
        log.info("=" * 50)
        sys.exit(1)
    save(new, incremental)
    log.info("=" * 50)
