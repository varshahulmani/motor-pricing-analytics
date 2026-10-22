# Validation log

Run: 2026-10-20 16:35. **20 checks passed, 0 failed**, 9 informational.

Every figure in the reports and the Tableau extracts is reconciled to the raw OpenML files: rows, claim counts and claim amounts. SQL in `sql/validation.sql`.

## Checks

| check | status | expected | actual | difference | what it checks |
|---|---|---|---|---|---|
| `policy_ids_unique` | ✅ PASS | 0 | 0 | 0 | No duplicate IDpol in the policy file |
| `policy_rows_kept` | ✅ PASS | 678,013 | 678,013 | 0 | Every raw policy row reaches the modelling table |
| `claim_rows_accounted` | ✅ PASS | 26,639 | 26,639 | 0 | Raw claim rows = matched claims + orphan claims |
| `claim_amount_accounted` | ✅ PASS | 60,697,930.68 | 60,697,930.68 | -0.00 | Raw claim total = matched + orphan amounts |
| `orphan_claims` | ℹ️ info | 0 | 195 | 195 | Claim amounts whose IDpol is not in the policy file (excluded) |
| `orphan_claim_amount` | ℹ️ info | 0 | 788,714.18 | 788,714.18 | Amount of those orphan claims (excluded) |
| `claimnb_without_amounts` | ℹ️ info | 0 | 9,116 | 9,116 | Policies with ClaimNb > 0 but no claim amounts (counted as 0 claims) |
| `amounts_without_claimnb` | ℹ️ info | 0 | 0 | 0 | Policies with claim amounts but ClaimNb = 0 (claims counted from amounts) |
| `claimnb_differs_from_amounts` | ℹ️ info | 0 | 9,117 | 9,117 | Policies where ClaimNb differs from the number of claim amounts |
| `exposure_capped` | ℹ️ info | 0 | 1,224 | 1,224 | Policies with exposure above 1 year (capped at 1) |
| `claim_count_capped` | ℹ️ info | 0 | 8 | 8 | Policies with more claims than the cap (capped for frequency) |
| `exposure_in_range` | ✅ PASS | 0 | 0 | 0 | Exposure after capping is in (0, 1] |
| `rating_factors_complete` | ✅ PASS | 0 | 0 | 0 | No missing values in any rating factor |
| `cap_split_reconciles` | ✅ PASS | 0 | 0 | 0 | Capped + excess = original amount for every claim (total abs difference) |
| `policy_losses_tie_to_claims` | ✅ PASS | 59,909,216.50 | 59,909,216.50 | 0.00 | Losses on the policy table = matched claim amounts |
| `split_covers_all` | ✅ PASS | 678,013 | 678,013 | 0 | Train + test = all policies |
| `oneway_exposure_ties` | ✅ PASS | 0 | 0.00 | 0.00 | Every one-way table sums to total exposure (worst factor) |
| `oneway_claims_tie` | ✅ PASS | 0 | 0 | 0 | Every one-way table sums to total claims (worst factor) |
| `heatmap_losses_tie` | ✅ PASS | 59,909,216.50 | 59,909,216.50 | 0.00 | Heatmap CSV losses = total losses |
| `heatmap_claims_tie` | ✅ PASS | 26,405 | 26,405 | 0 | Heatmap CSV claims = total claims |
| `segments_policies_tie` | ✅ PASS | 678,013 | 678,013 | 0 | Segment table covers every policy |
| `segments_losses_tie` | ✅ PASS | 59,909,216.50 | 59,909,216.50 | 0.00 | Segment table losses = total losses |
| `segments_claims_tie` | ✅ PASS | 26,405 | 26,405 | 0 | Segment table claims = total claims |
| `pricing_rows` | ✅ PASS | 678,013 | 678,013 | 0 | Pricing table has one row per policy |
| `model_balanced_on_train` | ✅ PASS | 45,583,384.15 | 45,583,384.15 | -0.00 | Model expected cost = actual losses on training data |
| `tariff_balanced_on_train` | ✅ PASS | 45,583,384.15 | 45,583,384.15 | -0.00 | Tariff risk premium = actual losses on training data |
| `kpi_csv_ties` | ✅ PASS | 59,909,216.50 | 59,909,216.50 | 0.00 | KPI CSV losses = total losses |
| `test_frequency_calibration` | ℹ️ info | 5,235 | 5,320.19 | 85.19 | GLM predicted claims on test vs actual (expected = actual claims) |
| `test_cost_calibration` | ℹ️ info | 14,325,832.35 | 11,451,182.74 | -2,874,649.61 | Model expected cost on test vs actual losses (expected = actual losses) |

## Data issues found and how they were handled

- **195 claim amounts (788,714) belong to IDpol values that are not in the policy file.** Excluded from losses; kept in table `claims_orphan`.
- **9,117 policies have a ClaimNb that differs from their number of claim amounts**, including 9,116 with claims but no amounts and 0 with amounts but ClaimNb = 0. Claims are counted from the amounts file so that frequency × severity reproduces the losses.
- 1,224 policies had exposure above 1 year → capped at 1.0.
- 8 policies had more than 4 claims → capped at 4 for the frequency model (their amounts are kept).
- Claims above 34,377 (the 99.5% percentile) are capped for the severity model; the excess is added back as a flat loading.

## Assumptions

```
{
  "claim_count_cap": 4,
  "exposure_cap": 1.0,
  "large_claim_quantile": 0.995,
  "permissible_loss_ratio": 0.7,
  "tariff_factors": [
    "bm_band",
    "driv_age_band",
    "area"
  ],
  "tariff_method": "glm",
  "mispricing_threshold": 0.1,
  "min_segment_exposure": 500,
  "segment_factors": [
    "driv_age_band",
    "bm_band",
    "veh_age_band",
    "veh_gas"
  ],
  "test_share": 0.2,
  "seed": 42
}
```