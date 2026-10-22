"""Write CSVs with the same columns as freMTPL2freq / freMTPL2sev, for testing without a download.

Planted structure (so you can check the models recover it):
  * frequency rises for young drivers, high bonus-malus, dense areas and new vehicles
  * young drivers in diesel cars are riskier than the two effects multiplied (an interaction
    a GLM without that term misses and boosting can find)
  * claim cost is heavy-tailed with a few very large claims
Planted data problems (so validation has something to catch):
  * exposure above 1 year and claim counts above 4
  * policies with ClaimNb > 0 but no claim amounts, and the reverse
  * claim amounts whose IDpol is not in the policy file
  * string values wrapped in quotes, as OpenML delivers them

    python scripts/make_synthetic.py --rows 120000 --out data/raw
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REGIONS = ["R11", "R21", "R22", "R23", "R24", "R25", "R26", "R31", "R41", "R42", "R43",
           "R52", "R53", "R54", "R72", "R73", "R74", "R82", "R83", "R91", "R93", "R94"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=120000)
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    n = a.rows
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    area = rng.choice(list("ABCDEF"), n, p=[0.15, 0.11, 0.28, 0.22, 0.20, 0.04])
    area_ix = np.array([ord(x) - 65 for x in area])
    density = np.round(np.exp(rng.normal(3 + 1.1 * area_ix, 0.8))).clip(1, 27000).astype(int)
    region_w = rng.dirichlet(np.ones(len(REGIONS)) * 0.8)
    region = rng.choice(REGIONS, n, p=region_w)
    drivage = (18 + rng.gamma(4.5, 6.5, n)).astype(int).clip(18, 100)
    young = drivage < 26
    bm = np.where(rng.random(n) < np.where(young, 0.15, 0.62), 50,
                  50 + rng.gamma(1.5, np.where(young, 25, 12), n)).astype(int).clip(50, 230)
    vehage = rng.exponential(7, n).astype(int).clip(0, 100)
    vehpower = (4 + rng.poisson(2.5, n)).clip(4, 15)
    brand = rng.choice([f"B{i}" for i in (1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14)], n)
    gas = rng.choice(["Diesel", "Regular"], n, p=[0.49, 0.51])
    exposure = np.round(np.where(rng.random(n) < 0.35, 1.0, rng.uniform(0.01, 1, n)), 2)
    over = rng.random(n) < 0.002
    exposure[over] = np.round(rng.uniform(1.01, 2.0, over.sum()), 2)

    reg_eff = dict(zip(REGIONS, rng.normal(0, 0.15, len(REGIONS))))
    log_f = (np.log(0.075)
             + np.select([drivage <= 20, drivage <= 25, drivage <= 30, drivage >= 75], [0.9, 0.45, 0.15, 0.2], 0)
             + 0.012 * (bm - 50)
             + 0.07 * (np.log(density) - 5)
             + np.where(vehage <= 1, 0.25, 0) - 0.01 * np.minimum(vehage, 20)
             + np.where((gas == "Diesel") & young, 0.45, 0)      # interaction
             + np.vectorize(reg_eff.get)(region))
    true_freq = np.exp(log_f)
    claims = rng.poisson(true_freq * np.minimum(exposure, 1))
    heavy = rng.choice(n, 25, replace=False)
    claims[heavy] = rng.integers(5, 12, 25)

    ids = np.arange(1, n + 1) * 2 + 1
    freq = pd.DataFrame({
        "IDpol": ids.astype(float), "ClaimNb": claims, "Exposure": exposure,
        "Area": [f"'{x}'" for x in area], "VehPower": vehpower, "VehAge": vehage, "DrivAge": drivage,
        "BonusMalus": bm, "VehBrand": [f"'{x}'" for x in brand], "VehGas": [f"'{x}'" for x in gas],
        "Density": density, "Region": [f"'{x}'" for x in region]})

    # claim amounts: one row per claim; ~3% of claiming policies get no amounts at all
    rows = []
    sev_mu = np.log(1300) + 0.004 * (drivage - 45) + np.where(vehage <= 2, 0.2, 0)
    for i in np.where(claims > 0)[0]:
        if rng.random() < 0.03:
            continue
        for _ in range(claims[i]):
            amt = rng.lognormal(sev_mu[i], 1.0)
            if rng.random() < 0.004:
                amt *= rng.pareto(1.3) * 40 + 20   # rare very large claims
            rows.append((ids[i], round(amt, 2)))
    # reverse problem: amounts for a few policies recorded with ClaimNb = 0
    for i in rng.choice(np.where(claims == 0)[0], 6, replace=False):
        rows.append((ids[i], round(rng.lognormal(7, 1), 2)))
    # orphans: amounts for policy ids that don't exist
    for _ in range(9):
        rows.append((int(ids.max() + 2 * rng.integers(1, 1000)), round(rng.lognormal(7, 1), 2)))
    sev = pd.DataFrame(rows, columns=["IDpol", "ClaimAmount"])

    freq.to_csv(out / "freMTPL2freq.csv", index=False)
    sev.to_csv(out / "freMTPL2sev.csv", index=False)
    print(f"wrote {n:,} policies ({claims.sum():,} claims recorded) and {len(sev):,} claim amounts to {out}")


if __name__ == "__main__":
    main()
