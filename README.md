# Motor Insurance Pricing & Loss Analytics

A pricing study on the French motor third-party liability data (**freMTPL2**: 678K policies, ~26K claim amounts): exposure-weighted SQL analysis, a Poisson GLM for claim frequency benchmarked against LightGBM, a Gamma GLM for claim cost, a pure premium, and a segment-level comparison against an assumed current tariff to find under- and over-priced business. Every number in the reports is reconciled back to the raw files by SQL checks, and the results feed a Tableau Public dashboard.

> **Approach in one line:** GLMs for the final price, because regulators and underwriters need explainable rating factors. LightGBM ranked risk about 11% better, and I used it to find which interactions the GLM was missing.

## Results (real freMTPL2 data: 677,991 policies, 358K policy-years, 26,444 claims)

| | |
|---|---|
| **50.7% of policies sit in segments mispriced by more than 10%** vs a 3-factor GLM tariff: 33.8% under-priced, 16.9% over-priced | `reports/pricing.md` |
| It held up out of sample: in the test year, under-priced segments cost **1.11×** what the tariff charged and over-priced ones **0.67×** (capped losses) | `reports/pricing.md` |
| Under-priced segments are short €2.5M of risk premium, 4.4% of the book | `reports/pricing.md` |
| Pure premium Gini on capped losses: model 0.318 vs tariff 0.303 | `reports/pricing.md` |
| Frequency Gini: Poisson GLM 0.300, LightGBM 0.334 (**+11.4%**); deviance explained 5.0% vs 6.8% | `reports/frequency.md` |
| The 133 claims above €34K (top 0.5%) carry 25% of all losses above that line; priced as a flat loading | `reports/validation_log.md` |
| 20 reconciliation checks pass; 1,224 exposures over 1 year and 8 claim counts over 4 capped | `reports/validation_log.md` |

Dashboard: `<your Tableau Public link>`

With the naive one-way tariff instead (`MTPL_TARIFF=oneway make all`), 71.7% of policies come out mispriced, mostly because one-way relativities double-count: mature drivers usually also hold the best bonus-malus, so they get the discount twice. The GLM tariff is the default because it is the fairer comparison.

## Run it

```bash
pip install -r requirements.txt

make demo     # whole pipeline on synthetic data with the real columns (~1 min, no download)
make clean
make all      # real data: downloads freMTPL2 from OpenML on the first run, then every step
```

| step | script | output |
|---|---|---|
| Load raw data into DuckDB | `src/load.py` | tables `raw_freq`, `raw_sev` in `data/mtpl.duckdb` |
| Clean, cap, band (SQL) | `src/prep.py` + `sql/prep.sql` | tables `claims`, `claims_per_policy`, `policy` |
| Assumed current tariff | `src/tariff.py` | table `tariff` |
| Exploratory analysis | `src/eda.py` | `reports/eda.md`, one-way charts, loss ratio heatmap |
| Frequency: Poisson GLM vs LightGBM | `src/frequency.py` | `reports/frequency.md`, Lorenz curves |
| Severity: Gamma GLM | `src/severity.py` | `reports/severity.md` |
| Pure premium + mispriced segments | `src/pricing.py` | `reports/pricing.md`, lift and double-lift charts |
| Tableau extracts | `src/export_tableau.py` | `tableau/data/*.csv` |
| Reconciliation | `src/validate.py` + `sql/validation.sql` | `reports/validation_log.md` |

`src/load.py` tries OpenML first and falls back to the same data from the CASdatasets R package on GitHub. You can also drop `freMTPL2freq.csv` and `freMTPL2sev.csv` into `data/raw/` yourself.

## How it works

**Cleaning (SQL).** Claim amounts are added up per policy and joined to the policy table. Every judgement call is in `ASSUMPTIONS` in `src/common.py` and printed in the validation log:
- exposure capped at 1 year; claim counts capped at 4 for the frequency model;
- claims above the 99.5th percentile are "large": capped for the severity model, with the excess spread back over every policy as a flat loading;
- claims are **counted from the amounts file**, not from `ClaimNb`, because the two files disagree for some policies and frequency × severity must reproduce the actual losses;
- claim amounts whose policy isn't in the policy file are set aside;
- driver age, vehicle age, bonus-malus and vehicle power are banded.

**Exploration.** Frequency is claims per policy-year, weighted by exposure, because a policy in force for three months had a quarter of the chance to claim. One-way tables for every factor give frequency, severity, loss cost and loss ratio.

**The tariff assumption.** The data has no premiums, so the "current price" is assumed: a multiplicative tariff on bonus-malus band, driver age band and area only, fit on capped training losses with the base rate rebalanced to total losses. Gross premium = risk premium / 70% (expenses and profit). By default the relativities come from a Tweedie GLM on those three factors, so the tariff is competent but limited, and "mispriced" measures what the factors it ignores (vehicle, fuel, region, density) are worth. `MTPL_TARIFF=oneway` switches to one-way relativities, the way many older tariffs were built, which double-count correlated factors. Both use capped losses: on total losses, 8 huge claims among 18–20 year-olds would set that band's relativity to 12×.

**Frequency.** Poisson GLM in statsmodels with `offset = log(exposure)`, against LightGBM with `objective='poisson'` on claims per policy-year weighted by exposure (the same likelihood). Both are fit on a deterministic 80% split and compared on the other 20% by exposure-weighted Poisson deviance and the Gini index from the Lorenz curve, never accuracy. LightGBM then audits the GLM: two-way cells where actual claims differ from the GLM by more than a Bonferroni-corrected number of Poisson standard errors and LightGBM is closer are flagged as candidate interactions.

**Severity.** Gamma GLM with log link on average capped claim cost, policies with claims only, weighted by claim count, then rebalanced (a log-link Gamma GLM is not automatically unbiased in total).

**Pure premium.** Expected frequency × expected severity × (1 + large-claim loading), rebalanced to training losses. On the test set it is compared with the tariff by Gini (on claim counts, capped losses and total losses), a lift chart and a double-lift chart.

**Mispriced segments.** Segments are driver age band × bonus-malus band × vehicle age band × fuel. A segment with at least 500 policy-years is mispriced if the model's expected cost differs from the tariff's risk premium by more than 10%: under-priced if the model expects more. The report gives the share of policies in each group and the premium gap, then checks it out of sample: test-set policies are pooled by their segment's status, and each group's actual losses are compared with what the tariff charged. A segment-by-segment vote is also reported, but one year of losses per segment is too noisy to settle much on its own (on the real data it's about 50/50).

**Validation.** `sql/validation.sql` holds ~30 checks: raw row and claim counts carried through every table; raw claim totals equal matched plus orphan amounts to the cent; capped + excess = original for every claim; one-way tables, heatmap, segment table and KPI extract each sum back to total exposure, claims and losses; train/test covers every policy; both model and tariff balance to training losses. Data quirks are reported with how each was handled. `make validate` exits non-zero on any failure, and each run is appended to `outputs/validation_history.csv`.

## Tableau dashboard

`tableau/TABLEAU.md` walks through building it from `tableau/data/`: a loss-ratio heatmap by driver age band × region (centred on the 70% target), the model lift chart, and the mispriced-segments table, plus KPI tiles. Publish to Tableau Public and link it above. The same charts are in `reports/` as PNGs.

## Design choices worth defending

- **GLM for the price, boosting as a check.** Rating factors must be filed and explained, and a GLM gives one relativity per level. On this data LightGBM ranks risk about 11% better (Gini 0.334 vs 0.300). Most of that comes from bonus-malus and driver age interacting, which is where the "missed cells" table points (e.g. 61–70 year-olds with bonus-malus 61–80 have 47% more claims than the GLM predicts). Adding a log bonus-malus term and a driver-age spline only closed a sliver of the gap (validation Gini 0.303 → 0.309). So the trade-off is real and stated, not assumed away: the next step would be adding the specific interactions boosting finds.
- **Deviance and Gini, not accuracy or RMSE.** Most policies have zero claims; Poisson deviance is the likelihood the model is fit on and Gini measures how well it ranks risks, which is what pricing needs.
- **Capping large claims.** A handful of huge claims would otherwise drive the severity relativities; they are priced as a flat loading instead.
- **Counting claims from the amounts file.** Otherwise frequency × severity wouldn't add up to actual losses.
- **Deterministic split by policy id hash**, so reruns and SQL checks see the same test set.

## Repo layout

```
src/        pipeline steps (common.py: paths, assumptions, metrics)
sql/        prep.sql (cleaning), validation.sql (reconciliation checks)
scripts/    synthetic data generator
reports/    generated reports and charts (committed)
tableau/    TABLEAU.md build guide + data/ extracts (committed)
data/       raw CSVs and the DuckDB database (git-ignored)
outputs/    intermediate tables and models (git-ignored)
```
