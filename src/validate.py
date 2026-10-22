"""Step 9: reconcile every reported number back to the raw data -> reports/validation_log.md

Runs the checks in sql/validation.sql: row counts, claim counts and claim totals from
raw files to modelling tables to the Tableau extracts, plus the data quirks found and
how each was handled. Exits non-zero if any exact check fails, so it can gate a refresh.
Each run is also appended to outputs/validation_history.csv.

    python src/validate.py
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

import pandas as pd

from common import ASSUMPTIONS, OUT, REPORTS, SQL, TABLEAU, con

HEADER = re.compile(r"^-- check: (.+)$", re.M)


def parse(text):
    parts = HEADER.split(text)[1:]
    for head, body in zip(parts[0::2], parts[1::2]):
        name, kind, tol, desc = [x.strip() for x in head.split("|", 3)]
        yield name, kind, float(tol), desc, body.strip()


def main():
    c = con(read_only=True)
    text = SQL.joinpath("validation.sql").read_text()
    text = text.replace("{out}", OUT.as_posix()).replace("{tableau}", TABLEAU.as_posix())
    rows = []
    for name, kind, tol, desc, sql in parse(text):
        try:
            exp, act = c.execute(sql).fetchone()
            exp, act = float(exp or 0), float(act or 0)
            diff = act - exp
            status = "INFO" if kind == "info" else ("PASS" if abs(diff) <= tol else "FAIL")
        except Exception as e:  # a missing extract etc. is a failure, not a crash
            exp = act = diff = float("nan")
            status = f"ERROR: {str(e).splitlines()[0][:80]}"
        rows.append(dict(check=name, status=status, expected=exp, actual=act, difference=diff, description=desc))
    res = pd.DataFrame(rows)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    hist = res.assign(run=stamp)
    hpath = OUT / "validation_history.csv"
    hist.to_csv(hpath, mode="a", header=not hpath.exists(), index=False)

    n_fail = (~res.status.isin(["PASS", "INFO"])).sum()
    n_pass = (res.status == "PASS").sum()
    params = json.loads((OUT / "prep_params.json").read_text())

    def num(x):
        if x != x:
            return "–"
        return f"{x:,.2f}" if abs(x - round(x)) > 1e-9 else f"{x:,.0f}"

    md = ["# Validation log", "", f"Run: {stamp}. **{n_pass} checks passed, {n_fail} failed**, "
          f"{(res.status == 'INFO').sum()} informational.", "",
          "Every figure in the reports and the Tableau extracts is reconciled to the raw OpenML files: rows, claim "
          "counts and claim amounts. SQL in `sql/validation.sql`.", "",
          "## Checks", "", "| check | status | expected | actual | difference | what it checks |", "|---|---|---|---|---|---|"]
    for r in res.itertuples():
        st = {"PASS": "✅ PASS", "INFO": "ℹ️ info"}.get(r.status, f"❌ {r.status}")
        md.append(f"| `{r.check}` | {st} | {num(r.expected)} | {num(r.actual)} | {num(r.difference)} | {r.description} |")
    info = res.set_index("check").actual
    md += ["", "## Data issues found and how they were handled", "",
           f"- **{info['orphan_claims']:,.0f} claim amounts ({info['orphan_claim_amount']:,.0f}) belong to IDpol values "
           "that are not in the policy file.** Excluded from losses; kept in table `claims_orphan`.",
           f"- **{info['claimnb_differs_from_amounts']:,.0f} policies have a ClaimNb that differs from their number of "
           f"claim amounts**, including {info['claimnb_without_amounts']:,.0f} with claims but no amounts and "
           f"{info['amounts_without_claimnb']:,.0f} with amounts but ClaimNb = 0. Claims are counted from the amounts "
           "file so that frequency × severity reproduces the losses.",
           f"- {info['exposure_capped']:,.0f} policies had exposure above 1 year → capped at {ASSUMPTIONS['exposure_cap']}.",
           f"- {info['claim_count_capped']:,.0f} policies had more than {ASSUMPTIONS['claim_count_cap']} claims → "
           f"capped at {ASSUMPTIONS['claim_count_cap']} for the frequency model (their amounts are kept).",
           f"- Claims above {params['large_claim_threshold']:,.0f} (the {ASSUMPTIONS['large_claim_quantile']:.1%} "
           "percentile) are capped for the severity model; the excess is added back as a flat loading.", "",
           "## Assumptions", "", "```", json.dumps(ASSUMPTIONS, indent=2), "```"]
    (REPORTS / "validation_log.md").write_text("\n".join(md))
    print(res[["check", "status", "expected", "actual"]].to_string(index=False))
    print(f"\n{n_pass} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
