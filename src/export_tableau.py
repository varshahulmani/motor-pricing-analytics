"""Step 8: write the CSVs the Tableau Public dashboard is built from -> tableau/data/

Small, pre-aggregated tables (Tableau Public works best with tidy extracts), every
one reconciled to the source tables by src/validate.py.

    python src/export_tableau.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import ASSUMPTIONS as A
from common import OUT, TABLEAU, band_order, con, lorenz_gini


def main():
    c = con()
    hm = pd.read_parquet(OUT / "heatmap_age_region.parquet")
    hm["age_order"] = hm.driv_age_band.map({b: i for i, b in enumerate(band_order("driv_age_band"))})
    hm.to_csv(TABLEAU / "heatmap_age_region.csv", index=False)

    pd.read_parquet(OUT / "oneway.parquet").to_csv(TABLEAU / "oneway.csv", index=False)

    lift = pd.read_parquet(OUT / "lift_model.parquet")
    long = lift.melt(id_vars=["decile", "exposure"],
                     value_vars=["actual_smoothed_loss_cost", "model_loss_cost", "tariff_loss_cost", "actual_loss_cost"],
                     var_name="series", value_name="loss_cost")
    long["series"] = long.series.map({"actual_smoothed_loss_cost": "Actual (capped + loading)",
                                      "model_loss_cost": "Model expected cost", "tariff_loss_cost": "Tariff risk premium",
                                      "actual_loss_cost": "Actual (total)"})
    long.to_csv(TABLEAU / "lift_chart.csv", index=False)
    pd.read_parquet(OUT / "double_lift.parquet").to_csv(TABLEAU / "double_lift.csv", index=False)

    seg = pd.read_parquet(OUT / "segments.parquet")
    keep = A["segment_factors"] + ["segment", "status", "credible", "policies", "exposure", "claims", "actual_losses",
                                   "model_cost", "tariff_cost", "gross_premium", "model_vs_tariff", "actual_vs_tariff",
                                   "loss_ratio", "premium_gap", "model_closer_on_test"]
    seg[keep].to_csv(TABLEAU / "segments.csv", index=False)

    te = pd.read_parquet(OUT / "test_frequency_predictions.parquet")
    rows = []
    for name, col in [("Poisson GLM", "freq_glm"), ("LightGBM", "freq_lgb")]:
        x, y, g = lorenz_gini(te.rate.to_numpy(), te[col].to_numpy(), te.exposure.to_numpy())
        idx = np.unique(np.linspace(0, len(x) - 1, 201).astype(int))
        rows.append(pd.DataFrame({"model": f"{name} (Gini {g:.3f})", "cum_exposure": x[idx], "cum_claims": y[idx]}))
    rows.append(pd.DataFrame({"model": "Random", "cum_exposure": [0, 1], "cum_claims": [0, 1]}))
    pd.concat(rows).to_csv(TABLEAU / "lorenz_frequency.csv", index=False)

    tot = c.execute("""
        SELECT count(*) AS policies, sum(exposure) AS policy_years, sum(n_claims) AS claims,
               sum(total_amount) AS losses, sum(tariff_gross_premium) AS gross_premium,
               sum(total_amount) / sum(tariff_gross_premium) AS loss_ratio
        FROM pricing""").df()
    pm = json.loads((OUT / "pricing_metrics.json").read_text())
    tot["mispriced_policy_share"] = pm["mispriced_policy_share"]
    tot["underpriced_policy_share"] = pm["underpriced_policy_share"]
    tot["overpriced_policy_share"] = pm["overpriced_policy_share"]
    tot.to_csv(TABLEAU / "kpis.csv", index=False)
    print(f"wrote {len(list(TABLEAU.glob('*.csv')))} CSVs to {TABLEAU}")


if __name__ == "__main__":
    main()
