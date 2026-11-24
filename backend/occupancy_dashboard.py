"""Dashboard-only forecast adapter. Does not change resource or Stage 2 APIs.

Multi-step rolling-origin coverage is NOT established. The scenario band comes
from resampling the dated single-step *test* net-count residuals in 7-day blocks.
It is not a calibrated predictive interval or a claimed confidence interval.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent.parent

@lru_cache(maxsize=1)
def _test_residuals():
    paths=ROOT/'stage2_training'/'outputs'/'catboost'
    intake=pd.read_csv(paths/'intake_count'/'test_predictions.csv',parse_dates=['date'])
    exit_=pd.read_csv(paths/'exit_count'/'test_predictions.csv',parse_dates=['date'])
    a=intake.groupby('date',as_index=True).apply(lambda g:float((g['intake_count']-g['prediction']).sum()),include_groups=False)
    b=exit_.groupby('date',as_index=True).apply(lambda g:float((g['exit_count']-g['prediction']).sum()),include_groups=False)
    joined=pd.concat([a.rename('intake'),b.rename('exit')],axis=1,join='inner').dropna().sort_index()
    if len(joined)<35:raise ValueError('單步測試殘差日期不足，無法產生有依據的情境帶')
    return (joined['intake']-joined['exit']).to_numpy(float)

def scenario_margins(days:int, repetitions=1500):
    """Correlated block bootstrap of summed daily net residuals; uncalibrated."""
    residuals=_test_residuals()
    block=7
    blocks=np.array([residuals[i:i+block] for i in range(len(residuals)-block+1)])
    rng=np.random.default_rng(20261120)
    n_blocks=(days+block-1)//block
    idx=rng.integers(0,len(blocks),size=(repetitions,n_blocks))
    paths=blocks[idx].reshape(repetitions,n_blocks*block)[:,:days]
    cumulative=np.cumsum(paths,axis=1)
    low=np.quantile(cumulative,0.05,axis=0)
    high=np.quantile(cumulative,0.95,axis=0)
    return low,high

def dashboard_forecast(days:int, current_count:int, baseline_date:date|None=None):
    from stage2_service import predict_counts,daily_training
    if days not in (7,14,30):raise ValueError('僅支援 7、14、30 天')
    baseline_date=baseline_date or datetime.now(ZoneInfo("Asia/Taipei")).date()
    models=predict_counts(days=days,as_of=baseline_date)
    grouped={}
    for rec in models:
        bucket=grouped.setdefault(rec['date'],{'in':0.0,'out':0.0})
        bucket['in']+=max(0.0,float(rec['intake_count']))
        bucket['out']+=max(0.0,float(rec['exit_count']))
    low,high=scenario_margins(days)
    running=float(current_count);points=[]
    for i in range(days):
        dt=(baseline_date+timedelta(days=i+1)).isoformat()
        flow=grouped.get(dt)
        if flow is None:raise ValueError('Stage 2 預測缺少日期 '+dt)
        running=max(0.,running+flow['in']-flow['out'])
        estimate=max(0,int(round(running)))
        lower=max(0,int(np.floor(running+low[i])))
        upper=max(0,int(np.ceil(running+high[i])))
        points.append({'date':dt,'expected_occupancy':estimate,
                       'lower_bound':min(estimate,lower),'upper_bound':max(estimate,upper),
                       'predicted_intakes':round(flow['in'],2),'predicted_outcomes':round(flow['out'],2)})
    daily=daily_training()
    return {'mock':False,'mode':'trained_catboost_recursive','demo':True,
            'current_count':int(current_count),'horizon_days':days,
            'forecast_baseline_date':baseline_date.isoformat(),
            'training_cutoff_date':str(daily.loc[daily['split'].eq('train'),'date'].max().date()),
            'observed_data_cutoff_date':str(daily['date'].max().date()),
            'forecast':points,
            'model_version':'stage2_training/outputs/catboost/{intake_count,exit_count}/best_model.cbm',
            'interval_method':'從留出測試集的每日入所－離所單步殘差，使用 7 日連續區塊自助抽樣累計並取 5%／95% 分位；未經多步回測校正。',
            'interval_label':'未校正預測情境帶',
            'warnings':['歷史資料末日之後至預測基準日的輸入特徵，以模型遞迴生成，不代表有實際入離所量。',
                        '此數量預測模型受訓資料的收容量尺度可能不同於目前 80 隻展示名單；以 SQLite 在所數為起點僅是條件情境推估。',
                        '上下界使用單步測試殘差區塊抽樣，尚未經多步滾動回測校正，不能視為已驗證的 90% 預測區間。']}
