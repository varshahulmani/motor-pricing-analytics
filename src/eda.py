"""Step 4: exploratory analysis -> reports/eda.md, reports/oneway.png, reports/heatmap_lr.png

Claim frequency is claims per policy-year (exposure-weighted), because a policy that
was only in force for 3 months has had a quarter of the chance to claim. Loss ratio
uses the assumed tariff's gross premium earned (rate x exposure).

    python src/eda.py
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import ASSUMPTIONS as A
from common import OUT, REPORTS, band_order, con, md_table

FACTORS = ["driv_age_band", "bm_band", "veh_age_band", "veh_power_band", "area", "veh_gas", "region", "veh_brand"]


def oneway(c, f):
    df = c.execute(f"""
        SELECT {f} AS level, count(*) AS policies, sum(exposure) AS exposure, sum(n_claims)::BIGINT AS claims,
               sum(n_claims) / sum(exposure) AS frequency,
               sum(total_amount) / nullif(sum(n_claim_records), 0) AS severity,
               sum(total_amount) / sum(exposure) AS loss_cost,
               sum(total_amount) / sum(t.tariff_gross_rate * exposure) AS loss_ratio
        FROM policy JOIN tariff t USING (IDpol)
        GROUP BY {f}""").df()
    try:
        order = band_order(f)
    except KeyError:
        order = sorted(df.level)
    df["level"] = pd.Categorical(df.level, order, ordered=True)
    df = df.sort_values("level")
    df.insert(0, "factor", f)
    df["level"] = df.level.astype(str)
    return df


def main():
    c = con()
    tot = c.execute("""
        SELECT count(*), sum(exposure), sum(n_claims), sum(total_amount),
               sum(total_amount) / sum(t.tariff_gross_rate * exposure)
        FROM policy JOIN tariff t USING (IDpol)""").fetchone()
    base_freq = tot[2] / tot[1]
    ow = pd.concat([oneway(c, f) for f in FACTORS], ignore_index=True)
    ow.to_parquet(OUT / "oneway.parquet", index=False)
    c.execute("CREATE OR REPLACE TABLE oneway AS SELECT * FROM ow")

    # small multiples: frequency line over exposure bars
    show = FACTORS[:6]
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for ax, f in zip(axes.flat, show):
        d = ow[ow.factor == f]
        ax.bar(d.level, d.exposure, color="#d9dee6")
        ax.set_ylabel("policy-years", fontsize=8, color="#777")
        ax2 = ax.twinx()
        ax2.plot(d.level, d.frequency * 100, marker="o", color="#2f5d8a")
        ax2.axhline(base_freq * 100, ls="--", lw=0.8, color="#999")
        ax2.set_ylabel("claims per 100 policy-years", fontsize=8)
        ax.set_title(f, fontsize=10)
        ax.tick_params(axis="x", labelsize=7, rotation=30)
        ax.tick_params(axis="y", labelsize=7); ax2.tick_params(labelsize=7)
    fig.suptitle("Claim frequency by rating factor (bars = exposure)")
    fig.tight_layout(); fig.savefig(REPORTS / "oneway.png", dpi=140)

    # loss ratio heatmap: driver age band x region
    hm = c.execute("""
        SELECT driv_age_band, region, sum(exposure) AS exposure, sum(n_claims)::BIGINT AS claims,
               sum(total_amount) AS losses, sum(t.tariff_gross_rate * exposure) AS premium,
               sum(total_amount) / sum(t.tariff_gross_rate * exposure) AS loss_ratio,
               sum(n_claims) / sum(exposure) AS frequency
        FROM policy JOIN tariff t USING (IDpol) GROUP BY ALL""").df()
    hm.to_parquet(OUT / "heatmap_age_region.parquet", index=False)
    piv = hm.pivot(index="driv_age_band", columns="region", values="loss_ratio").reindex(band_order("driv_age_band"))
    expo = hm.pivot(index="driv_age_band", columns="region", values="exposure").reindex(band_order("driv_age_band"))
    masked = piv.where(expo >= 200)  # thin cells are too noisy to colour
    fig, ax = plt.subplots(figsize=(14, 4.6))
    im = ax.imshow(masked.to_numpy() * 100, cmap="RdYlGn_r", vmin=30, vmax=110, aspect="auto")
    ax.set_xticks(range(len(piv.columns)), piv.columns, fontsize=8, rotation=45)
    ax.set_yticks(range(len(piv.index)), piv.index, fontsize=8)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = masked.iat[i, j]
            if v == v:
                ax.text(j, i, f"{v * 100:.0f}", ha="center", va="center", fontsize=6.5)
    fig.colorbar(im, ax=ax, label="loss ratio (%)")
    ax.set_title(f"Loss ratio by driver age band × region (target {A['permissible_loss_ratio']:.0%}; "
                 "cells under 200 policy-years blank)")
    fig.tight_layout(); fig.savefig(REPORTS / "heatmap_lr.png", dpi=140)

    md = ["# Exploratory analysis", "",
          f"{tot[0]:,} policies, {tot[1]:,.0f} policy-years, {tot[2]:,} claims "
          f"(**{100 * base_freq:.2f} claims per 100 policy-years**), losses {tot[3]:,.0f}. "
          f"Portfolio loss ratio against the assumed tariff: {tot[4]:.1%}.", "",
          "> The data has no premiums. Loss ratios use an assumed simple tariff (see `src/tariff.py`) with "
          f"gross premium = risk premium / {A['permissible_loss_ratio']:.0%}, so the portfolio loss ratio is "
          f"close to {A['permissible_loss_ratio']:.0%} by construction. What matters is how segments differ.", "",
          "![one-way](oneway.png)", "", "![heatmap](heatmap_lr.png)", ""]
    fmt = {"policies": "{:,}", "exposure": "{:,.0f}", "claims": "{:,}", "frequency": "{:.4f}",
           "severity": "{:,.0f}", "loss_cost": "{:,.1f}", "loss_ratio": "{:.1%}"}
    for f in FACTORS:
        d = ow[ow.factor == f].drop(columns="factor")
        if f in ("region", "veh_brand"):
            d = d.sort_values("loss_ratio", ascending=False)
        md += [f"## {f}", ""] + md_table(d, fmt) + [""]
    (REPORTS / "eda.md").write_text("\n".join(md))
    print(md[2])


if __name__ == "__main__":
    main()
