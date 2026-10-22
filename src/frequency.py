"""Step 5: claim frequency models -> reports/frequency.md, reports/lorenz_frequency.png

  GLM:      Poisson, log link, offset = log(exposure), banded rating factors (statsmodels)
  LightGBM: objective='poisson' on claims per policy-year, weighted by exposure
            (equivalent to the offset formulation for the Poisson likelihood)

Both are fit on the training split and compared on the test split with exposure-weighted
Poisson deviance and the Gini index from the Lorenz curve, not accuracy.
Then LightGBM is used as a check on the GLM: where do they disagree, and who is right?

    python src/frequency.py
"""
from __future__ import annotations

import itertools
import json
import pickle

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.stats import norm

from common import ASSUMPTIONS as A
from common import OUT, REPORTS, con, lorenz_gini, md_table, weighted_poisson_deviance

BASE_LEVELS = {"driv_age_band": "41-50", "bm_band": "50", "veh_age_band": "6-10", "veh_power_band": "6"}
GLM_FACTORS = ["driv_age_band", "bm_band", "veh_age_band", "veh_power_band", "area", "veh_gas", "veh_brand", "region"]
LGB_NUM = ["DrivAge", "BonusMalus", "VehAge", "VehPower", "log_density"]
LGB_CAT = ["area", "veh_gas", "veh_brand", "region"]


def glm_formula(target):
    terms = []
    for f in GLM_FACTORS:
        base = BASE_LEVELS.get(f)
        terms.append(f"C({f}, Treatment('{base}'))" if base else f"C({f})")
    return f"{target} ~ " + " + ".join(terms) + " + log_density"


def relativities(res):
    ci = np.exp(res.conf_int())
    out = pd.DataFrame({"term": res.params.index, "relativity": np.exp(res.params.values),
                        "ci_low": ci[0].values, "ci_high": ci[1].values, "p_value": res.pvalues.values})
    return out


def main():
    c = con()
    df = c.execute("SELECT * FROM policy").df()
    for f in LGB_CAT + list(BASE_LEVELS):
        df[f] = df[f].astype("category")
    tr, te = df[df.split == "train"].copy(), df[df.split == "test"].copy()
    tr["rate"], te["rate"] = tr.n_claims / tr.exposure, te.n_claims / te.exposure

    # ---- GLM
    glm = smf.glm(glm_formula("n_claims"), data=tr, family=sm.families.Poisson(),
                  offset=np.log(tr.exposure)).fit()
    rel = relativities(glm)
    rel.to_parquet(OUT / "glm_frequency_relativities.parquet", index=False)
    glm_rate = lambda d: glm.predict(d, offset=np.zeros(len(d)))  # per policy-year
    te["freq_glm"] = glm_rate(te)

    # ---- LightGBM
    rng = np.random.default_rng(A["seed"])
    es = rng.random(len(tr)) < 0.1
    feats = LGB_NUM + LGB_CAT
    dtr = lgb.Dataset(tr.loc[~es, feats], tr.rate[~es], weight=tr.exposure[~es], categorical_feature=LGB_CAT)
    des = lgb.Dataset(tr.loc[es, feats], tr.rate[es], weight=tr.exposure[es], reference=dtr)
    params = dict(objective="poisson", learning_rate=0.03, num_leaves=31, min_data_in_leaf=300,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
                  cat_smooth=50, verbose=-1, seed=A["seed"])
    gbm = lgb.train(params, dtr, 3000, valid_sets=[des], callbacks=[lgb.early_stopping(150, verbose=False)])
    te["freq_lgb"] = gbm.predict(te[feats], num_iteration=gbm.best_iteration)

    # ---- comparison on test
    null_rate = tr.n_claims.sum() / tr.exposure.sum()
    rows = []
    curves = {}
    for name, pred in [("Null (portfolio mean)", np.full(len(te), null_rate)),
                       ("Poisson GLM", te.freq_glm.to_numpy()), ("LightGBM (poisson)", te.freq_lgb.to_numpy())]:
        dev = weighted_poisson_deviance(te.rate, pred, te.exposure)
        x, y, g = lorenz_gini(te.rate.to_numpy(), pred, te.exposure.to_numpy())
        curves[name] = (x, y, g)
        rows.append(dict(model=name, poisson_deviance=dev, gini=g,
                         predicted_claims=float((pred * te.exposure).sum())))
    comp = pd.DataFrame(rows)
    comp.loc[0, "gini"] = 0.0  # a constant prediction has no ordering; tie order would add noise
    null_dev = comp.poisson_deviance.iloc[0]
    comp["deviance_explained"] = 1 - comp.poisson_deviance / null_dev
    comp["actual_claims"] = te.n_claims.sum()
    comp.to_parquet(OUT / "frequency_comparison.parquet", index=False)
    g_glm, g_lgb = comp.gini.iloc[1], comp.gini.iloc[2]
    gini_uplift = (g_lgb - g_glm) / g_glm

    # ---- what did the GLM miss? two-way cells where the models disagree, judged on test actuals
    cand = ["driv_age_band", "bm_band", "veh_age_band", "area", "veh_gas", "veh_power_band"]
    te["glm_claims"], te["lgb_claims"] = te.freq_glm * te.exposure, te.freq_lgb * te.exposure
    miss = []
    for a, b in itertools.combinations(cand, 2):
        g = te.groupby([a, b], observed=True).agg(exposure=("exposure", "sum"), claims=("n_claims", "sum"),
                                                  glm=("glm_claims", "sum"), lgb=("lgb_claims", "sum"))
        g = g[g.exposure >= 300].reset_index()
        g["cell"] = a + "=" + g[a].astype(str) + " & " + b + "=" + g[b].astype(str)
        miss.append(g[["cell", "exposure", "claims", "glm", "lgb"]])
    miss = pd.concat(miss, ignore_index=True)
    miss["actual_vs_glm"] = miss.claims / miss.glm
    miss["actual_vs_lgb"] = miss.claims / miss.lgb
    miss["lgb_vs_glm"] = miss.lgb / miss.glm
    # Poisson z-score of the GLM's miss, so tiny cells don't dominate
    miss["z_glm"] = (miss.claims - miss.glm) / np.sqrt(miss.glm)
    z_crit = float(norm.ppf(1 - 0.05 / (2 * len(miss))))  # Bonferroni across all cells tested
    missed = miss[(miss.z_glm.abs() > z_crit) & ((miss.lgb - miss.claims).abs() < (miss.glm - miss.claims).abs())]
    missed = missed.reindex(missed.z_glm.abs().sort_values(ascending=False).index)
    missed.to_parquet(OUT / "glm_missed_cells.parquet", index=False)

    # ---- predictions for every policy, for the pricing step
    df["freq_glm"] = glm_rate(df)
    df["freq_lgb"] = gbm.predict(df[feats], num_iteration=gbm.best_iteration)
    pred = df[["IDpol", "freq_glm", "freq_lgb"]]
    c.execute("CREATE OR REPLACE TABLE pred_freq AS SELECT * FROM pred")
    te[["IDpol", "exposure", "n_claims", "rate", "freq_glm", "freq_lgb"]].to_parquet(OUT / "test_frequency_predictions.parquet", index=False)
    glm.remove_data()
    with open(OUT / "glm_frequency.pkl", "wb") as fh:
        pickle.dump(glm, fh)
    gbm.save_model((OUT / "lgb_frequency.txt").as_posix(), num_iteration=gbm.best_iteration)
    json.dump(dict(gini_glm=g_glm, gini_lgb=g_lgb, gini_uplift=gini_uplift,
                   lgb_trees=gbm.best_iteration, glm_params=len(glm.params)),
              open(OUT / "frequency_metrics.json", "w"), indent=2)

    # ---- plot
    fig, ax = plt.subplots(figsize=(6.2, 5.6))
    for (name, (x, y, g)), col in zip(curves.items(), ["#999", "#2f5d8a", "#d35400"]):
        ax.plot(x, y, color=col, label=f"{name} (Gini {g:.3f})")
    ax.plot([0, 1], [0, 1], ls=":", color="#bbb")
    ax.set_xlabel("cumulative share of exposure (lowest predicted risk first)")
    ax.set_ylabel("cumulative share of claims")
    ax.set_title("Lorenz curves, test set")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout(); fig.savefig(REPORTS / "lorenz_frequency.png", dpi=150)

    # ---- report
    md = ["# Claim frequency", "",
          f"Train {len(tr):,} policies / test {len(te):,} (split by hash of IDpol). "
          f"Portfolio frequency {null_rate:.4f} claims per policy-year.", "",
          "## GLM vs LightGBM on the test set", ""]
    md += md_table(comp[["model", "poisson_deviance", "deviance_explained", "gini", "predicted_claims", "actual_claims"]],
                   {"poisson_deviance": "{:.5f}", "deviance_explained": "{:.2%}", "gini": "{:.4f}",
                    "predicted_claims": "{:,.0f}", "actual_claims": "{:,}"})
    md += ["", f"**LightGBM's Gini is {gini_uplift:+.1%} relative to the GLM** "
               f"({g_lgb:.4f} vs {g_glm:.4f}).", "",
           "![Lorenz](lorenz_frequency.png)", "",
           "## Where the GLM misses (and LightGBM gets closer)", "",
           "Two-way cells with ≥ 300 policy-years in the test set where actual claims differ from the GLM by more than "
           f"{z_crit:.2f} Poisson standard errors (Bonferroni across {len(miss):,} cells) and LightGBM is closer to "
           "actual. These are candidate interaction terms to add to the GLM.", ""]
    if len(missed):
        md += md_table(missed.head(12)[["cell", "exposure", "claims", "glm", "lgb", "actual_vs_glm", "actual_vs_lgb"]],
                       {"exposure": "{:,.0f}", "claims": "{:,.0f}", "glm": "{:,.1f}", "lgb": "{:,.1f}",
                        "actual_vs_glm": "{:.2f}", "actual_vs_lgb": "{:.2f}"})
    else:
        md.append("None found: the GLM's main effects capture the structure LightGBM finds.")
    md += ["", "## GLM relativities (multiplicative, vs base level)", "",
           "Base levels: " + ", ".join(f"{k} = {v}" for k, v in BASE_LEVELS.items()) + "; other factors use the "
           "first level alphabetically. `log_density` is per unit of log density.", ""]
    show = rel[rel.term != "Intercept"].copy()
    show["term"] = show.term.str.replace(r"C\((\w+)(?:, Treatment\('[^']*'\))?\)\[T\.(.*)\]", r"\1 = \2", regex=True)
    md += md_table(show, {"relativity": "{:.3f}", "ci_low": "{:.3f}", "ci_high": "{:.3f}", "p_value": "{:.3g}"})
    (REPORTS / "frequency.md").write_text("\n".join(md))
    print(comp.to_string(index=False))
    print(f"Gini uplift of LightGBM over GLM: {gini_uplift:+.1%}; GLM-missed cells: {len(missed)}")


if __name__ == "__main__":
    main()
