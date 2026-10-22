"""Step 7: pure premium and mispriced segments -> reports/pricing.md (+ lift charts)

  expected claim cost per policy-year ("pure premium")
      = expected frequency (Poisson GLM) x expected capped severity (Gamma GLM) x (1 + large-claim loading)

The large-claim loading spreads the excess above the cap over every policy in
proportion to its expected cost. The pure premium is rebalanced so it reproduces total
training losses.

Mispricing: for each segment (driver age band x bonus-malus band x vehicle age band x
fuel) compare the model's expected cost with the assumed tariff's risk premium. Segments
where they differ by more than the threshold, with enough exposure to judge, are
mispriced: under-priced if the model expects more than the tariff charges.

    python src/pricing.py
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import ASSUMPTIONS as A
from common import OUT, REPORTS, con, lorenz_gini, md_table


def decile_table(d, by, cols):
    d = d.sort_values(by, kind="mergesort").copy()
    cw = d.exposure.cumsum() / d.exposure.sum()
    d["decile"] = np.minimum((cw * 10).apply(np.ceil).astype(int), 10)
    agg = d.groupby("decile").agg(exposure=("exposure", "sum"), **{c: (c, "sum") for c in cols})
    return agg.reset_index()


def main():
    c = con()
    df = c.execute("""
        SELECT p.*, t.tariff_risk_rate, t.tariff_gross_rate, f.freq_glm, f.freq_lgb, s.sev_glm
        FROM policy p JOIN tariff t USING (IDpol) JOIN pred_freq f USING (IDpol) JOIN pred_sev s USING (IDpol)
    """).df()
    tr = df.split == "train"
    load = df.loc[tr, "excess_amount"].sum() / df.loc[tr, "capped_amount"].sum()
    raw_pp = df.freq_glm * df.sev_glm * (1 + load)
    balance = df.loc[tr, "total_amount"].sum() / (raw_pp[tr] * df.exposure[tr]).sum()
    df["pp_model"] = raw_pp * balance
    df["pp_lgb_freq"] = df.freq_lgb * df.sev_glm * (1 + load) * balance  # alternative, for comparison only
    df["model_cost"] = df.pp_model * df.exposure
    df["tariff_cost"] = df.tariff_risk_rate * df.exposure
    df["tariff_gross_premium"] = df.tariff_gross_rate * df.exposure
    pricing = df[["IDpol", "split", "exposure", "n_claims", "total_amount", "capped_amount", "pp_model", "pp_lgb_freq",
                  "tariff_risk_rate", "tariff_gross_rate", "model_cost", "tariff_cost", "tariff_gross_premium"]]
    c.execute("CREATE OR REPLACE TABLE pricing AS SELECT * FROM pricing")

    # ---------------- test-set validation of the pure premium
    te = df[~tr].copy()
    # Gini against three versions of "what happened": claim counts, capped losses, total losses.
    # Total losses are dominated by a few huge claims nobody can predict, so capped losses is the main one.
    ginis = {}
    for target in ("n_claims", "capped_amount", "total_amount"):
        y = (te[target] / te.exposure).to_numpy()
        ginis[target] = {name: lorenz_gini(y, te[col].to_numpy(), te.exposure.to_numpy())[2]
                         for name, col in [("tariff", "tariff_risk_rate"), ("model", "pp_model"),
                                           ("model_lgb_freq", "pp_lgb_freq")]}
    g_model, g_tariff = ginis["capped_amount"]["model"], ginis["capped_amount"]["tariff"]

    # "actual (capped + loading)" swaps each policy's large-claim excess for the average loading,
    # which is what a price can be expected to predict; total actuals are shown too
    te["actual_smoothed"] = te.capped_amount * (1 + load) * balance
    cols = ["model_cost", "tariff_cost", "total_amount", "actual_smoothed"]
    lift = decile_table(te, "pp_model", cols)
    for col in cols:
        lift[col.replace("_cost", "").replace("total_amount", "actual") + "_loss_cost"] = lift[col] / lift.exposure
    lift.to_parquet(OUT / "lift_model.parquet", index=False)
    te["ratio"] = te.pp_model / te.tariff_risk_rate
    dl = decile_table(te, "ratio", cols)
    dl["model_vs_tariff"] = dl.model_cost / dl.tariff_cost
    dl["actual_vs_tariff"] = dl.total_amount / dl.tariff_cost
    dl["actual_smoothed_vs_tariff"] = dl.actual_smoothed / dl.tariff_cost
    dl["actual_vs_model"] = dl.total_amount / dl.model_cost
    dl.to_parquet(OUT / "double_lift.parquet", index=False)

    # ---------------- segments
    seg_f = A["segment_factors"]
    seg = df.groupby(seg_f, observed=True).agg(
        policies=("IDpol", "size"), exposure=("exposure", "sum"), claims=("n_claims", "sum"),
        actual_losses=("total_amount", "sum"), model_cost=("model_cost", "sum"),
        tariff_cost=("tariff_cost", "sum"), gross_premium=("tariff_gross_premium", "sum")).reset_index()
    tseg = te.groupby(seg_f, observed=True).agg(test_actual=("total_amount", "sum"), test_model=("model_cost", "sum"),
                                                test_tariff=("tariff_cost", "sum")).reset_index()
    seg = seg.merge(tseg, on=seg_f, how="left")
    seg["segment"] = seg[seg_f].astype(str).agg(" · ".join, axis=1)
    seg["model_vs_tariff"] = seg.model_cost / seg.tariff_cost
    seg["actual_vs_tariff"] = seg.actual_losses / seg.tariff_cost
    seg["loss_ratio"] = seg.actual_losses / seg.gross_premium
    seg["credible"] = seg.exposure >= A["min_segment_exposure"]
    thr = A["mispricing_threshold"]
    seg["status"] = np.select([~seg.credible, seg.model_vs_tariff > 1 + thr, seg.model_vs_tariff < 1 - thr],
                              ["too small to judge", "under-priced", "over-priced"], "fair")
    seg["premium_gap"] = seg.model_cost - seg.tariff_cost  # + means tariff charges too little
    # on test data only: was the model closer to what actually happened than the tariff?
    seg["model_closer_on_test"] = (seg.test_actual - seg.test_model).abs() < (seg.test_actual - seg.test_tariff).abs()
    seg = seg.sort_values("premium_gap", ascending=False)
    seg.to_parquet(OUT / "segments.parquet", index=False)

    tot_pol, tot_exp = len(df), df.exposure.sum()
    s = seg.groupby("status").agg(segments=("segment", "size"), policies=("policies", "sum"),
                                  exposure=("exposure", "sum"), premium_gap=("premium_gap", "sum")).reindex(
        ["under-priced", "over-priced", "fair", "too small to judge"]).fillna(0)
    s["share_policies"] = s.policies / tot_pol
    s["share_exposure"] = s.exposure / tot_exp
    mis = seg[seg.status.isin(["under-priced", "over-priced"])]
    mis_share = mis.policies.sum() / tot_pol
    under_gap = seg.loc[seg.status == "under-priced", "premium_gap"].sum()
    total_tariff = df.tariff_cost.sum()
    closer = mis.model_closer_on_test.mean() if len(mis) else float("nan")

    # pooled out-of-sample check: group the TEST policies by their segment's status and ask whether
    # each group cost what the model said (relative to the tariff). Pooling beats a segment-by-segment
    # vote, which one year of noisy losses can't settle.
    tg = te.merge(seg[seg_f + ["status"]], on=seg_f, how="left").groupby("status").agg(
        exposure=("exposure", "sum"), claims=("n_claims", "sum"), actual_capped=("actual_smoothed", "sum"),
        actual_total=("total_amount", "sum"), model=("model_cost", "sum"), tariff=("tariff_cost", "sum"))
    tg = tg.reindex(["under-priced", "over-priced", "fair", "too small to judge"]).dropna(how="all")
    tg["model_vs_tariff"] = tg.model / tg.tariff
    tg["actual_capped_vs_tariff"] = tg.actual_capped / tg.tariff
    tg["actual_total_vs_tariff"] = tg.actual_total / tg.tariff
    tg.reset_index().to_parquet(OUT / "mispricing_test_check.parquet", index=False)
    pooled = {k: dict(model=float(r.model_vs_tariff), actual_capped=float(r.actual_capped_vs_tariff),
                      actual_total=float(r.actual_total_vs_tariff)) for k, r in tg.iterrows()}

    metrics = dict(large_claim_loading=load, balance_factor=balance, gini_capped_model=g_model, gini_capped_tariff=g_tariff,
                   gini=ginis, mispriced_policy_share=mis_share,
                   mispriced_share_of_judged=mis.policies.sum() / seg.loc[seg.credible, "policies"].sum(),
                   mispriced_exposure_share=mis.exposure.sum() / tot_exp,
                   underpriced_policy_share=float(s.loc["under-priced", "share_policies"]),
                   overpriced_policy_share=float(s.loc["over-priced", "share_policies"]),
                   underpriced_gap=under_gap, underpriced_gap_share_of_premium=under_gap / total_tariff,
                   model_closer_on_test_share=closer, test_check=pooled, tariff_method=A["tariff_method"],
                   n_segments=len(seg),
                   n_credible=int(seg.credible.sum()))
    (OUT / "pricing_metrics.json").write_text(json.dumps(metrics, indent=2))

    # ---------------- charts
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.plot(lift.decile, lift.actual_smoothed_loss_cost, marker="o", color="#222", label="actual (capped + loading)")
    ax.plot(lift.decile, lift.actual_loss_cost, color="#222", alpha=0.3, lw=1, label="actual (total)")
    ax.plot(lift.decile, lift.model_loss_cost, marker="s", color="#2f5d8a", label="model expected cost")
    ax.plot(lift.decile, lift.tariff_loss_cost, marker="^", color="#d35400", label="tariff risk premium")
    ax.set_xticks(range(1, 11)); ax.set_xlabel("decile of model expected cost (equal exposure)")
    ax.set_ylabel("loss cost per policy-year"); ax.set_title("Lift chart, test set")
    ax.legend(frameon=False); fig.tight_layout(); fig.savefig(REPORTS / "lift_chart.png", dpi=150)
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.plot(dl.decile, dl.actual_smoothed_vs_tariff, marker="o", color="#222", label="actual (capped + loading) / tariff")
    ax.plot(dl.decile, dl.actual_vs_tariff, color="#222", alpha=0.3, lw=1, label="actual (total) / tariff")
    ax.plot(dl.decile, dl.model_vs_tariff, marker="s", color="#2f5d8a", label="model / tariff")
    ax.axhline(1, ls=":", color="#999")
    ax.set_xticks(range(1, 11)); ax.set_xlabel("decile of model ÷ tariff (left: tariff too high, right: too low)")
    ax.set_ylabel("ratio to tariff"); ax.set_title("Double lift: where the model and tariff disagree, who is right?")
    ax.legend(frameon=False); fig.tight_layout(); fig.savefig(REPORTS / "double_lift.png", dpi=150)

    # ---------------- report
    judged = seg.loc[seg.credible, "policies"].sum()
    md = ["# Pricing and mispriced segments", "",
          "Expected cost per policy-year = Poisson GLM frequency × Gamma GLM capped severity × (1 + large-claim loading), "
          "rebalanced to training losses.", "",
          f"Current tariff (assumed, the data has no premiums): **{A['tariff_method']}** relativities on "
          f"{', '.join(A['tariff_factors'])}, from capped training losses, rebalanced to total losses. See `src/tariff.py`.", "",
          f"- Large-claim loading: **{load:.1%}** (excess above the cap, as a share of capped losses, training data).",
          f"- Balance factor: {balance:.4f}.", "",
          "## Does the model rank risk better than the tariff? (test set)", "",
          "Gini of each price measured against what happened in the test year. Capped losses is the fair comparison: "
          "total losses include a few very large claims that no rating factor predicts.", "",
          "| price | Gini on claim counts | **Gini on capped losses** | Gini on total losses |", "|---|---|---|---|"]
    for name, label in [("tariff", "Assumed 3-factor tariff"), ("model", "GLM pure premium"),
                        ("model_lgb_freq", "same, with LightGBM frequency")]:
        md.append(f"| {label} | {ginis['n_claims'][name]:.4f} | **{ginis['capped_amount'][name]:.4f}** | "
                  f"{ginis['total_amount'][name]:.4f} |")
    md += ["",
          "![lift](lift_chart.png)", "", "![double lift](double_lift.png)", "",
          "Read the double lift chart from left to right: on the left the model says the tariff charges too much, on "
          "the right too little. If the black line (what actually happened, with each policy's large-claim excess "
          "replaced by the average loading) follows the blue one, the model is right.", "",
          f"## Mispriced segments", "",
          f"Segments: {' × '.join(seg_f)} ({len(seg)} segments, {int(seg.credible.sum())} with ≥ "
          f"{A['min_segment_exposure']:,} policy-years). Mispriced = model expected cost differs from the tariff by "
          f"more than {thr:.0%}.", "",
          f"**{mis_share:.1%} of policies are in mispriced segments**: "
          f"{s.loc['under-priced', 'share_policies']:.1%} under-priced and {s.loc['over-priced', 'share_policies']:.1%} "
          f"over-priced ({mis.policies.sum() / judged:.1%} of the {judged:,} policies in segments big enough to judge). "
          f"The under-priced segments are short {under_gap:,.0f} of risk premium, "
          f"{under_gap / total_tariff:.1%} of the portfolio total.", ""]
    md += ["### Did it hold up out of sample?", "",
           "Test-set policies grouped by their segment's status. If the model is right, under-priced groups should "
           "cost more than the tariff charged (ratio above 1) and over-priced groups less. 'Capped' replaces each "
           "policy's large-claim excess with the average loading, which is what a price can be expected to predict.", "",
           "| group (test set) | policy-years | claims | model ÷ tariff | **actual (capped) ÷ tariff** | actual (total) ÷ tariff |",
           "|---|---|---|---|---|---|"]
    md += [f"| {k} | {r.exposure:,.0f} | {int(r.claims):,} | {r.model_vs_tariff:.2f} | **{r.actual_capped_vs_tariff:.2f}** | "
           f"{r.actual_total_vs_tariff:.2f} |" for k, r in tg.iterrows()]
    md += ["", f"Segment by segment, the model was closer than the tariff to test-set losses in {closer:.0%} of mispriced "
               "segments: one year of losses per segment is too noisy to settle it individually, hence the pooled check.",
           "", "| status | segments | policies | share of policies | share of exposure | premium gap |", "|---|---|---|---|---|---|"]
    md += [f"| {k} | {int(r.segments)} | {int(r.policies):,} | {r.share_policies:.1%} | {r.share_exposure:.1%} | {r.premium_gap:,.0f} |"
           for k, r in s.iterrows()]
    cols = ["segment", "policies", "exposure", "claims", "model_vs_tariff", "actual_vs_tariff", "loss_ratio", "premium_gap"]
    fmt = {"policies": "{:,}", "exposure": "{:,.0f}", "claims": "{:,}", "model_vs_tariff": "{:.2f}",
           "actual_vs_tariff": "{:.2f}", "loss_ratio": "{:.1%}", "premium_gap": "{:,.0f}"}
    md += ["", "### Most under-priced (largest premium gap)", ""] + md_table(seg[seg.status == "under-priced"].head(12)[cols], fmt)
    md += ["", "### Most over-priced", ""] + md_table(
        seg[seg.status == "over-priced"].sort_values("premium_gap").head(12)[cols], fmt)
    (REPORTS / "pricing.md").write_text("\n".join(md))
    print(f"Gini on capped losses: tariff {g_tariff:.4f}, model {g_model:.4f} | mispriced {mis_share:.1%} of policies "
          f"(under {s.loc['under-priced', 'share_policies']:.1%}, over {s.loc['over-priced', 'share_policies']:.1%}) "
          f"| test, actual(capped)/tariff: " + ", ".join(f"{k} {v['actual_capped']:.2f} (model {v['model']:.2f})"
                                                          for k, v in pooled.items() if k in ("under-priced", "over-priced")))


if __name__ == "__main__":
    main()
