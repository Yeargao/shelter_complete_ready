import argparse, json, pickle, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
import optuna
from sklearn.metrics import log_loss
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from common.metrics import censor_km,cause_cindex,brier_cif,calibration_cif
CAUSES=['adoption','transfer','other_exit','death_euthanasia','return_to_owner']
CATS=['species','breed','size_class','age_group','health_at_intake','sex_at_intake']
NUMS=['age_years_at_intake','estimated_weight_kg']

def features(df,days,categories):
    x=df[CATS+NUMS].copy()
    for c in CATS:x[c]=pd.Categorical(x[c].fillna('unknown').astype(str),categories=categories[c]).codes.astype('int32')
    for c in NUMS:x[c]=pd.to_numeric(x[c],errors='coerce').fillna(-1)
    x['day']=days.astype('int32');x['log_day']=np.log1p(days)
    return x

def expanded(df,max_day):
    # Each row contributes until event/censor or horizon. Administrative truncation is treated as censoring.
    lengths=np.clip(df.duration_days.to_numpy(dtype=int),1,max_day)
    ids=np.repeat(np.arange(len(df)),lengths)
    days=np.concatenate([np.arange(1,n+1,dtype=np.int32) for n in lengths]);return ids,days

def build_models(train,val,params,max_day,max_rows,seed):
    cats={c:sorted(set(train[c].fillna('unknown').astype(str))|{'unknown'}) for c in CATS}
    ids,days=expanded(train,max_day)
    if max_rows and len(ids)>max_rows:
        rng=np.random.default_rng(seed);sel=np.sort(rng.choice(len(ids),max_rows,replace=False));ids,days=ids[sel],days[sel]
    x=features(train.iloc[ids].reset_index(drop=True),days,cats)
    models={};y_event=train.event_type.to_numpy();dur=train.duration_days.to_numpy()
    for cause in CAUSES:
        y=((y_event[ids]==cause)&(days==dur[ids])).astype('int8')
        if y.sum()<2:continue
        model=lgb.LGBMClassifier(objective='binary',verbosity=-1,n_jobs=4,random_state=seed,**params)
        model.fit(x,y);models[cause]=model
    return models,cats

def predict(models,cats,df,max_day,batch=150):
    # Predict each day conditional on still at risk, then compute CIF and survival.
    n=len(df); cifs={k:np.zeros((n,max_day),dtype=np.float32) for k in models};surv=np.ones(n,dtype=np.float64)
    for start in range(1,max_day+1,batch):
        stop=min(max_day,start+batch-1);dd=np.arange(start,stop+1,dtype=np.int32)
        ids=np.repeat(np.arange(n),len(dd));day=np.tile(dd,n)
        x=features(df.iloc[ids].reset_index(drop=True),day,cats)
        hz=np.stack([models[k].predict_proba(x)[:,1].reshape(n,len(dd)) for k in models],axis=0)
        hz=hz/np.maximum(hz.sum(axis=0,keepdims=True),1.)
        for j,t in enumerate(dd):
            for ci,k in enumerate(models):
                incr=surv*hz[ci,:,j]
                cifs[k][:,t-1]=incr+(cifs[k][:,t-2] if t>1 else 0)
            surv*=np.maximum(0,1-hz[:,:,j].sum(axis=0))
    return cifs,surv

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--trials',type=int,default=50);ap.add_argument('--max-day',type=int,default=180);ap.add_argument('--trial-rows',type=int,default=120000);ap.add_argument('--output',default=str(ROOT/'outputs/lightgbm_hazard'));a=ap.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(ROOT/'inputs/lightgbm_hazard.csv');df['duration_days']=pd.to_numeric(df.duration_days,errors='coerce').fillna(1).clip(lower=1).astype(int)
    tr=df[df.split=='train'].reset_index(drop=True);va=df[df.split=='val'].reset_index(drop=True);te=df[df.split=='test'].reset_index(drop=True)
    study=optuna.create_study(direction='minimize',study_name='hazard',storage=f'sqlite:///{(out/"optuna.db").as_posix()}',load_if_exists=True)
    def objective(t):
        params=dict(n_estimators=t.suggest_int('n_estimators',80,220),num_leaves=t.suggest_int('num_leaves',8,48),learning_rate=t.suggest_float('learning_rate',.02,.12,log=True),min_child_samples=t.suggest_int('min_child_samples',20,120),colsample_bytree=t.suggest_float('colsample_bytree',.7,1.0))
        models,cats=build_models(tr,va,params,a.max_day,a.trial_rows,42)
        if not models:raise optuna.TrialPruned()
        cif,_=predict(models,cats,va,a.max_day)
        km=censor_km(tr.duration_days,tr.event_observed);scores=[]
        for k,arr in cif.items():
            for h in (30,90):
                if h<=a.max_day:scores.append(brier_cif(va.duration_days,va.event_type,va.event_observed,k,arr[:,h-1],h,km))
        return float(np.mean(scores))
    interrupted=False
    try:study.optimize(objective,n_trials=a.trials,catch=(ValueError,))
    except KeyboardInterrupt:interrupted=True;print('Interrupted; completed trials retained in SQLite')
    trials=study.trials_dataframe();trials.to_csv(out/'optuna_trials.csv',index=False)
    done=[t for t in study.trials if t.state==optuna.trial.TrialState.COMPLETE]
    if not done:
        (out/'run_summary.json').write_text(json.dumps({'interrupted':interrupted,'completed_trials':0,'status':'no_completed_trial'},indent=2));return
    best=study.best_trial;models,cats=build_models(tr,va,best.params,a.max_day,None,42)
    with open(out/'best_models.pkl','wb') as f:pickle.dump({'models':models,'categories':cats,'max_day':a.max_day,'causes':list(models)},f)
    cif,_=predict(models,cats,te,a.max_day);km=censor_km(tr.duration_days,tr.event_observed)
    records=[];cal=[]
    for k,arr in cif.items():
        rec={'cause':k,'cause_specific_c_index':cause_cindex(te.duration_days,te.event_type,k,arr[:,-1])}
        bs=[]
        for h in (7,30,60,90,180):
            if h>a.max_day:continue
            score=brier_cif(te.duration_days,te.event_type,te.event_observed,k,arr[:,h-1],h,km)
            rec[f'brier_{h}d']=score;bs.append((h,score))
            for idx,v in enumerate(calibration_cif(te.duration_days,te.event_type,te.event_observed,k,arr[:,h-1],h,km)):
                cal.append(dict(cause=k,horizon=h,bin=idx+1,**v))
        rec['integrated_brier_score']=float(np.trapezoid([v for _,v in bs],[h for h,_ in bs])/(bs[-1][0]-bs[0][0])) if len(bs)>1 else None
        records.append(rec)
    pd.DataFrame(records).to_csv(out/'metrics_by_cause.csv',index=False)
    pd.DataFrame(cal).to_csv(out/'calibration.csv',index=False)
    summary={'model':'LightGBM discrete-time competing cause-specific hazards','trials_requested_this_run':a.trials,'completed_trials_total':len(done),'interrupted':interrupted,'best_trial':best.number,'best_validation_score':best.value,'best_parameters':best.params,'max_day':a.max_day,'test_size':len(te),'notes':'IBS: time-integrated IPCW Brier for cause-specific cumulative incidence; other causes treated as observed non-target. Cause-specific C-index treats competing events as censored for pair comparability. Calibration IPCW bins.'}
    (out/'run_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
