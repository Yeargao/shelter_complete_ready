# Stage 2: LightGBM Discrete-Time Competing-Risk Hazard + CatBoost

Input files in `inputs/` are the provided stage-one outputs. This ZIP contains NO DeepHit code.

## Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python lightgbm_hazard/train.py --trials 50 --max-day 180
python catboost/train.py --trials 50
```

Run commands from this directory. For quick smoke tests use `--trials 1 --trial-rows 10000 --max-day 90` on hazard and `--trials 1` on CatBoost. `--trials` is the number of *additional* trials per study when rerun; CatBoost has one study for each of the two targets.

## Outputs

`outputs/lightgbm_hazard/`: SQLite Optuna study, `optuna_trials.csv`, `best_models.pkl`, `metrics_by_cause.csv` (cause-specific C-index and IPCW integrated Brier score for cause-specific cumulative incidence), `calibration.csv` (predicted vs IPCW observed probabilities by time and quantile), `run_summary.json`.

`outputs/catboost/intake_count/` and `exit_count/`: each includes SQLite study, Optuna trials, best `.cbm` model, `metrics.json` (MAE, RMSE, WAPE, bias), `metrics_by_species.csv`, `feature_importance.csv`, `test_predictions.csv`. Root CatBoost output includes `run_summary.json`.

`inputs/resource_by_condition.csv` is retained for downstream demand forecasts, not used as an observed label. Resource estimates in the hazard CSV are heuristic and are **not** used as survival features, to avoid synthetic-label leakage.

## Modeling and interpretation

Each observed episode is expanded into at-risk day rows until the event/censor date, administratively truncated at `--max-day`. A separate binary LightGBM model is fitted per competing exit cause. Each model estimates the discrete conditional cause-specific hazard. At prediction time, daily cause hazards are proportionally normalized only if their sum exceeds 1; then survival and cumulative incidence are recursively computed. Cause-specific cumulative incidence does not have to reach 100% by the horizon. Days beyond the training horizon are unsupported.

The competing-event cause-specific C-index compares pairs where the earlier event is the target cause (other causes treated as censored for comparability). IBS integrates inverse-censoring-weighted Brier scores for cumulative incidence over the listed horizons; calibration bins are inverse-censoring-weighted. The censoring KM is fitted on training data. These metrics require independent censoring assumptions and are not a replacement for clinical/operational validation.

CatBoost trains separate Poisson count regressors for daily intake and exit counts using stage-one lag features. Evaluation is on held-out rows. For deployment, future lag features must be updated recursively; the test metrics here use observed historical lags, so they are one-step-ahead metrics, **not** a validated recursive 90-day forecast.

## Ctrl+C and resuming

Optuna SQLite records completed trials immediately. On Ctrl+C the scripts attempt to export completed trials and fit/save the best model; a second hard interrupt may prevent this, but trials remain in SQLite. Re-running resumes the same study and adds the requested number of trials. No model is claimed if no trial finished. Keep the outputs directory to resume.

## Caveats

- Data are sourced from uploaded phase-one CSVs, not recomputed.
- Hazard training expansion can be memory- and CPU-intensive, particularly 50 trials across five causes. Optuna trials subsample expanded at-risk rows by default; final models use all rows.
- Discrete-time modeling with fixed baseline features does not automatically update age or health during follow-up.
- The dataset splits and historical source limitations are inherited from stage one; inspect `inputs/data_report.json`.
