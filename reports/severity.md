# Claim severity

Gamma GLM, log link, on the average claim amount (capped at 34,377) of 19,990 training policies with claims, weighted by claim count.

| | test-set Gamma deviance |
|---|---|
| Null (mean claim 1,709) | 1.1126 |
| Gamma GLM | 1.1131 (-0.0% explained) |

Balance factor applied so predicted capped losses equal actual on the training data: 0.9999.

Severity is much noisier than frequency, so expect only a few percent of deviance explained and wide confidence intervals. That's normal for motor claims and why severity models use fewer factors.

## Relativities

| term | relativity | ci_low | ci_high | p_value |
|---|---|---|---|---|
| driv_age_band = 18-20 | 1.492 | 1.235 | 1.803 | 3.35e-05 |
| driv_age_band = 21-25 | 0.956 | 0.844 | 1.083 | 0.481 |
| driv_age_band = 26-30 | 1.004 | 0.903 | 1.117 | 0.937 |
| driv_age_band = 31-40 | 1.016 | 0.941 | 1.097 | 0.686 |
| driv_age_band = 51-60 | 1.026 | 0.950 | 1.109 | 0.507 |
| driv_age_band = 61-70 | 0.964 | 0.872 | 1.066 | 0.475 |
| driv_age_band = 71+ | 1.176 | 1.047 | 1.321 | 0.00632 |
| bm_band = 101+ | 1.129 | 0.988 | 1.291 | 0.0747 |
| bm_band = 51-60 | 1.028 | 0.947 | 1.116 | 0.514 |
| bm_band = 61-80 | 1.046 | 0.974 | 1.123 | 0.217 |
| bm_band = 81-100 | 1.117 | 1.019 | 1.224 | 0.018 |
| veh_age_band = 0 | 1.178 | 1.034 | 1.342 | 0.0138 |
| veh_age_band = 1-2 | 1.053 | 0.974 | 1.138 | 0.192 |
| veh_age_band = 11-15 | 0.964 | 0.896 | 1.036 | 0.318 |
| veh_age_band = 16+ | 0.947 | 0.846 | 1.060 | 0.345 |
| veh_age_band = 3-5 | 1.048 | 0.974 | 1.129 | 0.21 |
| veh_gas = Regular | 0.998 | 0.947 | 1.052 | 0.94 |
| area = B | 0.989 | 0.887 | 1.102 | 0.84 |
| area = C | 0.950 | 0.870 | 1.036 | 0.247 |
| area = D | 0.995 | 0.910 | 1.087 | 0.906 |
| area = E | 1.046 | 0.956 | 1.145 | 0.325 |
| area = F | 0.799 | 0.676 | 0.944 | 0.00846 |