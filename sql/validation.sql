-- Reconciliation checks, run by src/validate.py after every other step.
-- Each block: a header line "-- check: <name> | <exact|info> | <tolerance> | <description>"
-- then one query returning columns expected, actual.
-- exact: PASS when |expected - actual| <= tolerance, otherwise FAIL.
-- info: reported, never fails (data quirks we decided how to handle).
-- {out} and {tableau} are replaced with the output folders.

-- check: policy_ids_unique | exact | 0 | No duplicate IDpol in the policy file
SELECT 0 AS expected, count(*) - count(DISTINCT IDpol) AS actual FROM raw_freq;

-- check: policy_rows_kept | exact | 0 | Every raw policy row reaches the modelling table
SELECT (SELECT count(*) FROM raw_freq) AS expected, (SELECT count(*) FROM policy) AS actual;

-- check: claim_rows_accounted | exact | 0 | Raw claim rows = matched claims + orphan claims
SELECT (SELECT count(*) FROM raw_sev) AS expected,
       (SELECT count(*) FROM claims) + (SELECT count(*) FROM claims_orphan) AS actual;

-- check: claim_amount_accounted | exact | 0.01 | Raw claim total = matched + orphan amounts
SELECT (SELECT sum(ClaimAmount) FROM raw_sev) AS expected,
       (SELECT sum(amount) FROM claims) + coalesce((SELECT sum(ClaimAmount) FROM claims_orphan), 0) AS actual;

-- check: orphan_claims | info | 0 | Claim amounts whose IDpol is not in the policy file (excluded)
SELECT 0 AS expected, (SELECT count(*) FROM claims_orphan) AS actual;

-- check: orphan_claim_amount | info | 0 | Amount of those orphan claims (excluded)
SELECT 0 AS expected, coalesce((SELECT sum(ClaimAmount) FROM claims_orphan), 0) AS actual;

-- check: claimnb_without_amounts | info | 0 | Policies with ClaimNb > 0 but no claim amounts (counted as 0 claims)
SELECT 0 AS expected, count(*) AS actual FROM policy WHERE claim_nb_reported > 0 AND n_claim_records = 0;

-- check: amounts_without_claimnb | info | 0 | Policies with claim amounts but ClaimNb = 0 (claims counted from amounts)
SELECT 0 AS expected, count(*) AS actual FROM policy WHERE claim_nb_reported = 0 AND n_claim_records > 0;

-- check: claimnb_differs_from_amounts | info | 0 | Policies where ClaimNb differs from the number of claim amounts
SELECT 0 AS expected, count(*) AS actual FROM policy WHERE claim_nb_reported <> n_claim_records;

-- check: exposure_capped | info | 0 | Policies with exposure above 1 year (capped at 1)
SELECT 0 AS expected, count(*) AS actual FROM policy WHERE exposure_reported > exposure;

-- check: claim_count_capped | info | 0 | Policies with more claims than the cap (capped for frequency)
SELECT 0 AS expected, count(*) AS actual FROM policy WHERE n_claim_records > n_claims;

-- check: exposure_in_range | exact | 0 | Exposure after capping is in (0, 1]
SELECT 0 AS expected, count(*) AS actual FROM policy WHERE exposure <= 0 OR exposure > 1 OR exposure IS NULL;

-- check: rating_factors_complete | exact | 0 | No missing values in any rating factor
SELECT 0 AS expected,
       count(*) FILTER (WHERE area IS NULL OR region IS NULL OR veh_brand IS NULL OR veh_gas IS NULL
                         OR DrivAge IS NULL OR VehAge IS NULL OR BonusMalus IS NULL OR VehPower IS NULL
                         OR Density IS NULL) AS actual
FROM policy;

-- check: cap_split_reconciles | exact | 0.01 | Capped + excess = original amount for every claim (total abs difference)
SELECT 0 AS expected, sum(abs(capped_amount + excess_amount - amount)) AS actual FROM claims;

-- check: policy_losses_tie_to_claims | exact | 0.01 | Losses on the policy table = matched claim amounts
SELECT (SELECT sum(amount) FROM claims) AS expected, (SELECT sum(total_amount) FROM policy) AS actual;

-- check: split_covers_all | exact | 0 | Train + test = all policies
SELECT (SELECT count(*) FROM policy) AS expected,
       (SELECT count_if(split = 'train') + count_if(split = 'test') FROM policy) AS actual;

-- check: oneway_exposure_ties | exact | 0.01 | Every one-way table sums to total exposure (worst factor)
SELECT 0 AS expected, max(abs(e - (SELECT sum(exposure) FROM policy))) AS actual
FROM (SELECT factor, sum(exposure) AS e FROM oneway GROUP BY factor);

-- check: oneway_claims_tie | exact | 0 | Every one-way table sums to total claims (worst factor)
SELECT 0 AS expected, max(abs(n - (SELECT sum(n_claims) FROM policy))) AS actual
FROM (SELECT factor, sum(claims) AS n FROM oneway GROUP BY factor);

-- check: heatmap_losses_tie | exact | 0.01 | Heatmap CSV losses = total losses
SELECT (SELECT sum(total_amount) FROM policy) AS expected, sum(losses) AS actual
FROM read_csv_auto('{tableau}/heatmap_age_region.csv');

-- check: heatmap_claims_tie | exact | 0 | Heatmap CSV claims = total claims
SELECT (SELECT sum(n_claims) FROM policy) AS expected, sum(claims) AS actual
FROM read_csv_auto('{tableau}/heatmap_age_region.csv');

-- check: segments_policies_tie | exact | 0 | Segment table covers every policy
SELECT (SELECT count(*) FROM policy) AS expected, sum(policies) AS actual
FROM read_csv_auto('{tableau}/segments.csv');

-- check: segments_losses_tie | exact | 0.01 | Segment table losses = total losses
SELECT (SELECT sum(total_amount) FROM policy) AS expected, sum(actual_losses) AS actual
FROM read_csv_auto('{tableau}/segments.csv');

-- check: segments_claims_tie | exact | 0 | Segment table claims = total claims
SELECT (SELECT sum(n_claims) FROM policy) AS expected, sum(claims) AS actual
FROM read_csv_auto('{tableau}/segments.csv');

-- check: pricing_rows | exact | 0 | Pricing table has one row per policy
SELECT (SELECT count(*) FROM policy) AS expected, (SELECT count(DISTINCT IDpol) FROM pricing) AS actual;

-- check: model_balanced_on_train | exact | 1 | Model expected cost = actual losses on training data
SELECT sum(total_amount) AS expected, sum(model_cost) AS actual FROM pricing WHERE split = 'train';

-- check: tariff_balanced_on_train | exact | 1 | Tariff risk premium = actual losses on training data
SELECT sum(total_amount) AS expected, sum(tariff_cost) AS actual FROM pricing WHERE split = 'train';

-- check: kpi_csv_ties | exact | 0.01 | KPI CSV losses = total losses
SELECT (SELECT sum(total_amount) FROM policy) AS expected, losses AS actual
FROM read_csv_auto('{tableau}/kpis.csv');

-- check: test_frequency_calibration | info | 0 | GLM predicted claims on test vs actual (expected = actual claims)
SELECT sum(n_claims) AS expected, sum(freq_glm * exposure) AS actual
FROM read_parquet('{out}/test_frequency_predictions.parquet');

-- check: test_cost_calibration | info | 0 | Model expected cost on test vs actual losses (expected = actual losses)
SELECT sum(total_amount) AS expected, sum(model_cost) AS actual FROM pricing WHERE split = 'test';
