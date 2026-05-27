# Counterfactual Replay Report

| policy | bets | bet_rows | final_bankroll | profit | roi | risk_adjusted_roi | max_drawdown | variance | profit_std | survival_score | ruin_probability | collapse_probability | survival_improvement | variance_reduction | stress_robustness | halt_reason | drawdown_delta_vs_baseline | roi_delta_vs_baseline | survival_delta_vs_baseline | variance_delta_vs_baseline | collapse_avoidance | stability_improvement |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_bet | 0 | 82 | 20000.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 | 1.0 | 0.0 | 1.0 |  | 3121.74991 | 0.727236 | 30.184250000000006 | -38085.356795 | 1.0 | -38055.172545 |
| defensive | 0 | 82 | 20000.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 | 0.0 | 1.0 | 0.0 | 1.0 |  | 3121.74991 | 0.727236 | 30.184250000000006 | -38085.356795 | 1.0 | -38055.172545 |
| aggressive | 35 | 82 | 18209.60951 | -1790.39049 | -0.462062 | -6.027842 | -1952.509532 | 88220.975206 | 297.02016 | 74.42618 | 0.0 | 0.038 | 1.0 | 0.0 | 0.902375 |  | 1169.240378 | 0.265174 | 4.610430000000008 | 50135.618411 | 0.962 | -50131.007981 |
| kelly_half | 70 | 82 | 17448.09918 | -2551.90082 | -0.737163 | -28.142998 | -2406.07582 | 8222.177926 | 90.676226 | 72.526579 | 0.0 | 0.038 | 1.0 | 0.0 | 0.879696 |  | 715.67409 | -0.00992700000000002 | 2.710829000000004 | -29863.178869 | 0.962 | -29860.46804 |
| regime_no_bet | 65 | 82 | 17242.136371 | -2757.863629 | -0.732123 | -24.961544 | -2582.873629 | 12206.824092 | 110.484497 | 71.945147 | 0.0 | 0.038 | 1.0 | 0.0 | 0.870856 |  | 538.8762809999998 | -0.004886999999999975 | 2.1293970000000115 | -25878.532702999997 | 0.962 | -25876.403305999997 |
| calibration_stop | 63 | 82 | 16927.738754 | -3072.261246 | -0.695444 | -21.638921 | -2838.941246 | 20157.890464 | 141.978486 | 71.074866 | 0.0 | 0.198 | 1.0 | 0.0 | 0.858053 |  | 282.80866400000014 | 0.03179200000000004 | 1.259116000000006 | -17927.466331 | 0.802 | -17926.207215 |
| recorded | 48 | 82 | 16410.25009 | -3589.74991 | -0.727236 | -18.394381 | -3121.74991 | 38085.356795 | 195.1547 | 69.81575 | 0.0 | 0.262 | 1.0 | 0.0 | 0.843913 |  | 0.0 | 0.0 | 0.0 | 0.0 | 0.738 | 0.0 |

## Exposure Heatmap
| policy | regime | avg_exposure | avg_stake | roi | bets |
| --- | --- | --- | --- | --- | --- |
| recorded | BALANCED | 0.00562 | 108.955076 | -0.999995 | 4 |
| recorded | DEEP_LONGSHOT | 0.002801 | 51.272297 | -0.317047 | 17 |
| recorded | FAVORITE_TO_BALANCED | 0.0 | 0.0 | 0.0 | 0 |
| recorded | LONGSHOT | 0.003407 | 59.519388 | -0.932865 | 27 |
| no_bet | BALANCED | 0.0 | 0.0 | 0.0 | 0 |
| no_bet | DEEP_LONGSHOT | 0.0 | 0.0 | 0.0 | 0 |
| no_bet | FAVORITE_TO_BALANCED | 0.0 | 0.0 | 0.0 | 0 |
| no_bet | LONGSHOT | 0.0 | 0.0 | 0.0 | 0 |
| kelly_half | BALANCED | 0.004259 | 82.477083 | -0.993852 | 7 |
| kelly_half | DEEP_LONGSHOT | 0.001998 | 37.358062 | -0.40251 | 27 |
| kelly_half | FAVORITE_TO_BALANCED | 0.000944 | 17.376512 | 2.970101 | 1 |
| kelly_half | LONGSHOT | 0.002141 | 38.831199 | -0.948546 | 35 |
| aggressive | BALANCED | 9e-06 | 0.164077 | -0.999911 | 1 |
| aggressive | DEEP_LONGSHOT | 0.001743 | 33.450939 | 0.67232 | 11 |
| aggressive | FAVORITE_TO_BALANCED | 0.0 | 0.0 | 0.0 | 0 |
| aggressive | LONGSHOT | 0.003638 | 70.157392 | -0.933333 | 23 |
| defensive | BALANCED | 0.0 | 0.0 | 0.0 | 0 |
| defensive | DEEP_LONGSHOT | 0.0 | 0.0 | 0.0 | 0 |
| defensive | FAVORITE_TO_BALANCED | 0.0 | 0.0 | 0.0 | 0 |
| defensive | LONGSHOT | 0.0 | 0.0 | 0.0 | 0 |
| regime_no_bet | BALANCED | 0.004869 | 93.960044 | -0.993526 | 6 |
| regime_no_bet | DEEP_LONGSHOT | 0.002326 | 43.21456 | -0.380176 | 25 |
| regime_no_bet | FAVORITE_TO_BALANCED | 0.0 | 0.0 | 0.0 | 0 |
| regime_no_bet | LONGSHOT | 0.002207 | 39.64012 | -0.939516 | 34 |
| calibration_stop | BALANCED | 0.00488 | 94.860059 | -0.99145 | 5 |
| calibration_stop | DEEP_LONGSHOT | 0.002582 | 47.459723 | -0.247491 | 25 |
| calibration_stop | FAVORITE_TO_BALANCED | 0.0 | 0.0 | 0.0 | 0 |
| calibration_stop | LONGSHOT | 0.002946 | 52.440642 | -0.93904 | 33 |