"""Step 6: claim severity model -> reports/severity.md

Gamma GLM with log link on the average (capped) claim amount per policy, using only
policies that had a claim, weighted by the number of claims. Claims above the
large-claim threshold are capped here; their excess is added back as a portfolio
loading in the pricing step, because a handful of huge claims would otherwise swing
the severity relativities.

    python src/severity.py
"""
from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from common import OUT, REPORTS, con, md_table, weighted_gamma_deviance

SEV_FACTORS = {"driv_age_band": "41-50", "bm_band": "50", "veh_age_band": "6-10", "veh_gas": None, "area": None}


def formula():
    terms = [f"C({f}, Treatment('{b}'))" if b else f"C({f})" for f, b in SEV_FACTORS.items()]
    return "avg_claim ~ " + " + ".join(terms)


def main():
    c = con()
    thr = json.loads((OUT / "prep_params.json").read_text())["large_claim_threshold"]
    df = c.execute("""
        SELECT *, capped_amount / n_claim_records AS avg_claim FROM policy
        WHERE n_claim_records > 0 AND capped_amount > 0""").df()
    tr, te = df[df.split == "train"], df[df.split == "test"]

    glm = smf.glm(formula(), data=tr, family=sm.families.Gamma(link=sm.families.links.Log()),
                  var_weights=tr.n_claim_records).fit()
    te_pred = glm.predict(te)
    null = np.average(tr.avg_claim, weights=tr.n_claim_records)
    dev_null = weighted_gamma_deviance(te.avg_claim, np.full(len(te), null), te.n_claim_records)
    dev_glm = weighted_gamma_deviance(te.avg_claim, te_pred, te.n_claim_records)

    # the Gamma log-link GLM is not automatically balanced; rescale so predicted = actual on train
    balance = tr.capped_amount.sum() / (glm.predict(tr) * tr.n_claim_records).sum()

    allp = c.execute("SELECT IDpol, driv_age_band, bm_band, veh_age_band, veh_gas, area FROM policy").df()
    allp["sev_glm"] = glm.predict(allp) * balance
    pred = allp[["IDpol", "sev_glm"]]
    c.execute("CREATE OR REPLACE TABLE pred_sev AS SELECT * FROM pred")

    ci = np.exp(glm.conf_int())
    rel = pd.DataFrame({"term": glm.params.index, "relativity": np.exp(glm.params.values),
                        "ci_low": ci[0].values, "ci_high": ci[1].values, "p_value": glm.pvalues.values})
    rel.to_parquet(OUT / "glm_severity_relativities.parquet", index=False)
    glm.remove_data()
    with open(OUT / "glm_severity.pkl", "wb") as fh:
        pickle.dump(glm, fh)
    m = dict(gamma_deviance_null=dev_null, gamma_deviance_glm=dev_glm,
             deviance_explained=1 - dev_glm / dev_null, balance_factor=balance,
             mean_capped_severity_train=null, n_train=len(tr), n_test=len(te))
    (OUT / "severity_metrics.json").write_text(json.dumps(m, indent=2))

    show = rel[rel.term != "Intercept"].copy()
    show["term"] = show.term.str.replace(r"C\((\w+)(?:, Treatment\('[^']*'\))?\)\[T\.(.*)\]", r"\1 = \2", regex=True)
    md = ["# Claim severity", "",
          f"Gamma GLM, log link, on the average claim amount (capped at {thr:,.0f}) of {len(tr):,} training policies "
          f"with claims, weighted by claim count.", "",
          "| | test-set Gamma deviance |", "|---|---|",
          f"| Null (mean claim {null:,.0f}) | {dev_null:.4f} |",
          f"| Gamma GLM | {dev_glm:.4f} ({1 - dev_glm / dev_null:.1%} explained) |", "",
          f"Balance factor applied so predicted capped losses equal actual on the training data: {balance:.4f}.", "",
          "Severity is much noisier than frequency, so expect only a few percent of deviance explained and wide "
          "confidence intervals. That's normal for motor claims and why severity models use fewer factors.", "",
          "## Relativities", ""]
    md += md_table(show, {"relativity": "{:.3f}", "ci_low": "{:.3f}", "ci_high": "{:.3f}", "p_value": "{:.3g}"})
    (REPORTS / "severity.md").write_text("\n".join(md))
    print(f"Gamma GLM: deviance {dev_glm:.4f} vs null {dev_null:.4f} ({1 - dev_glm / dev_null:.1%} explained), "
          f"balance factor {balance:.4f}")


if __name__ == "__main__":
    main()
