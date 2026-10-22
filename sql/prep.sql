-- Step 2: clean, cap and band. Placeholders like {{large_threshold}} are filled in by src/prep.py.

-- claim amounts whose policy is not in the policy file are set aside (reported in validation)
CREATE OR REPLACE TABLE claims_orphan AS
SELECT s.* FROM raw_sev s ANTI JOIN raw_freq f USING (IDpol);

-- one row per claim, with the large-claim split
CREATE OR REPLACE TABLE claims AS
SELECT s.claim_row, s.IDpol, s.ClaimAmount AS amount,
       s.ClaimAmount > {large_threshold}                    AS is_large,
       least(s.ClaimAmount, {large_threshold})              AS capped_amount,
       greatest(s.ClaimAmount - {large_threshold}, 0)       AS excess_amount
FROM raw_sev s SEMI JOIN raw_freq f USING (IDpol);

-- add up claim amounts per policy
CREATE OR REPLACE TABLE claims_per_policy AS
SELECT IDpol,
       count(*)            AS n_claim_records,
       sum(amount)         AS total_amount,
       sum(capped_amount)  AS capped_amount,
       sum(excess_amount)  AS excess_amount,
       count_if(is_large)  AS n_large
FROM claims GROUP BY IDpol;

-- the modelling table: one row per policy
CREATE OR REPLACE TABLE policy AS
SELECT f.IDpol,
       f.ClaimNb                                            AS claim_nb_reported,
       f.Exposure                                           AS exposure_reported,
       least(f.Exposure, {exposure_cap})                    AS exposure,
       -- claims are counted from the amounts file so that frequency x severity = losses
       least(coalesce(c.n_claim_records, 0), {claim_count_cap}) AS n_claims,
       coalesce(c.n_claim_records, 0)                       AS n_claim_records,
       coalesce(c.total_amount, 0)                          AS total_amount,
       coalesce(c.capped_amount, 0)                         AS capped_amount,
       coalesce(c.excess_amount, 0)                         AS excess_amount,
       coalesce(c.n_large, 0)                               AS n_large,
       f.Area AS area, f.VehPower, f.VehAge, f.DrivAge, f.BonusMalus,
       f.VehBrand AS veh_brand, f.VehGas AS veh_gas, f.Density, ln(f.Density) AS log_density,
       f.Region AS region,
       {band_driv_age}, {band_veh_age}, {band_bm}, {band_veh_power},
       CASE WHEN hash(f.IDpol + {seed}) % 1000 < {test_permille} THEN 'test' ELSE 'train' END AS split
FROM raw_freq f
LEFT JOIN claims_per_policy c USING (IDpol);
