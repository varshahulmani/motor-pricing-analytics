"""Step 3: the assumed current tariff (the dataset has no real premiums).

Assumption, stated in every report: today's price is a simple multiplicative tariff on
three factors (bonus-malus band, driver age band, area), built on training data from
capped losses, with the base rate rebalanced to total losses. Two ways to set the
relativities (ASSUMPTIONS['tariff_method'] / env MTPL_TARIFF):

  glm     (default) a Tweedie GLM on capped loss cost with just those three factors.
          A competent but limited tariff: mispricing then measures what the factors it
          ignores (vehicle, fuel, region, density) are worth.
  oneway  each factor's loss cost relative to the portfolio average, multiplied together.
          How many older tariffs were built; it double-counts correlated factors (mature
          drivers mostly also have the best bonus-malus, so they get the discount twice),
          which inflates the mispricing it shows.

  risk premium  = base rate x rel(bm_band) x rel(driv_age_band) x rel(area)
  gross premium = risk premium / permissible loss ratio (expenses and profit)

    python src/tariff.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from common import ASSUMPTIONS as A
from common import con


def glm_relativities(c, factors):
    """Overwrite tariff_relativities with exp(coefficients) of a 3-factor Tweedie GLM."""
    d = c.execute(f"SELECT {', '.join(factors)}, exposure, capped_amount FROM policy WHERE split = 'train'").df()
    d["lc"] = d.capped_amount / d.exposure
    m = smf.glm("lc ~ " + " + ".join(f"C({f})" for f in factors), data=d,
                family=sm.families.Tweedie(var_power=1.5, link=sm.families.links.Log()),
                var_weights=d.exposure).fit()
    rows = []
    for f in factors:
        for lev in sorted(d[f].unique()):
            coef = m.params.get(f"C({f})[T.{lev}]", 0.0)  # base level has coefficient 0
            rows.append((f, lev, float(d.loc[d[f] == lev, "exposure"].sum()), float(np.exp(coef))))
    rel = pd.DataFrame(rows, columns=["factor", "level", "exposure", "relativity"])
    c.execute("CREATE OR REPLACE TABLE tariff_relativities AS SELECT * FROM rel")


def main():
    c = con()
    factors = A["tariff_factors"]
    # Relativities use CAPPED losses, as any actuary would: on total losses a handful of huge
    # claims in a small cell (8 claims in the 18-20 band on the real data) would set its
    # relativity to ~12x and drag every other price down when rebalanced. Large-claim cost
    # still reaches the price through the base rate, which is balanced to total losses.
    overall = c.execute(
        "SELECT sum(capped_amount) / sum(exposure) FROM policy WHERE split = 'train'").fetchone()[0]
    rel_sql = " UNION ALL ".join(
        f"""SELECT '{f}' AS factor, {f} AS level, sum(exposure) AS exposure,
                   sum(capped_amount) / sum(exposure) / {overall} AS relativity
            FROM policy WHERE split = 'train' GROUP BY {f}""" for f in factors)
    c.execute(f"CREATE OR REPLACE TABLE tariff_relativities AS {rel_sql}")
    if A["tariff_method"] == "glm":
        glm_relativities(c, factors)

    joins = " ".join(
        f"JOIN (SELECT level, relativity AS rel_{f} FROM tariff_relativities WHERE factor = '{f}') r_{f} "
        f"ON p.{f} = r_{f}.level" for f in factors)
    prod = " * ".join(f"rel_{f}" for f in factors)
    c.execute(f"CREATE OR REPLACE TEMP TABLE _t AS SELECT p.IDpol, p.split, p.exposure, p.total_amount, {prod} AS rel FROM policy p {joins}")
    base = c.execute("SELECT sum(total_amount) / sum(rel * exposure) FROM _t WHERE split = 'train'").fetchone()[0]
    c.execute(f"""
        CREATE OR REPLACE TABLE tariff AS
        SELECT IDpol, {base} * rel AS tariff_risk_rate,                      -- per policy-year
               {base} * rel / {A['permissible_loss_ratio']} AS tariff_gross_rate
        FROM _t""")
    n_pol, n_tar = c.execute("SELECT (SELECT count(*) FROM policy), (SELECT count(*) FROM tariff)").fetchone()
    assert n_pol == n_tar, f"tariff lost policies: {n_pol} vs {n_tar} (a level unseen in training?)"
    total_lc = c.execute("SELECT sum(total_amount) / sum(exposure) FROM policy WHERE split = 'train'").fetchone()[0]
    msg = f"{A['tariff_method']} tariff on {', '.join(factors)}: base rate {base:,.1f} per policy-year"
    if A["tariff_method"] == "oneway":
        msg += f" (rebalancing factor {base / total_lc:.3f}: below 1 means the one-way relativities double-count)"
    print(msg)
    print(c.execute("SELECT factor, level, round(relativity, 2) AS rel FROM tariff_relativities ORDER BY factor, level").df()
          .to_string(index=False))


if __name__ == "__main__":
    main()
