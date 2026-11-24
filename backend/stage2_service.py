"""Read-only inference adapter for user-supplied stage2_training (trusted pickle only)."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache
from pathlib import Path
import json, pickle
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent / 'stage2_training'
CAT_COLS = ['species','breed','size_class','age_group','health_at_intake','sex_at_intake']
NUM_COLS = ['age_years_at_intake','estimated_weight_kg']

def require(path):
    if not path.is_file(): raise FileNotFoundError(f'模型資料不存在：{path.relative_to(ROOT)}')
    return path

def read_json(path):return json.loads(require(path).read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def hazard_bundle():
    # Never load untrusted pickle. Only deploy personally verified stage2_training ZIPs.
    with require(ROOT/'outputs/lightgbm_hazard/best_models.pkl').open('rb') as f: obj=pickle.load(f)
    if not obj.get('models') or not obj.get('categories') or not obj.get('max_day'):
        raise ValueError('LightGBM model bundle missing required keys')
    return obj

@lru_cache(maxsize=1)
def count_models():
    from catboost import CatBoostRegressor
    out={}
    for target in ('intake_count','exit_count'):
        m=CatBoostRegressor();m.load_model(str(require(ROOT/f'outputs/catboost/{target}/best_model.cbm')))
        out[target]=m
    return out

@lru_cache(maxsize=1)
def daily_training():
    d=pd.read_csv(require(ROOT/'inputs/catboost_daily.csv'),parse_dates=['date']).sort_values('date')
    return d

@lru_cache(maxsize=1)
def resource_table():
    return pd.read_csv(require(ROOT/'inputs/resource_by_condition.csv'))

def species_name(value):
    if str(value).lower()=='dog':return 'Dog'
    if str(value).lower()=='cat':return 'Cat'
    if str(value).lower()=='other':return 'Other'
    return str(value or 'Unknown').title()  # Unknown species must not silently inherit Other rates.

def _sex(v):return {'male':'Male','female':'Female'}.get(str(v).lower(),'Unknown')
def _age_group(years):
    if years<1:return 'young'
    if years>=8:return 'senior'
    return 'adult'

def _profile(animal, resource):
    species=species_name(animal.get('species'))
    years=(animal.get('age_months') or 24)/12
    breed=animal.get('breed') or ''
    sub=resource[resource.species.str.casefold()==species.casefold()]
    if breed:
        match=sub[sub.breed.fillna('').str.casefold()==breed.casefold()]
        if len(match):sub=match
    if len(sub):
        ag=sub[sub.age_group.fillna('').str.casefold()==_age_group(years)]
        if len(ag):sub=ag
        # Respect the health-specific resource rows provided by the user.
        # An unknown condition must not silently be treated as needs_care.
        health_key=str(animal.get('health_status') or 'unknown').strip().casefold()
        conditions={'healthy':'healthy','good':'healthy','normal':'healthy',
                    'sick':'needs_care','injured':'needs_care','serious':'needs_care',
                    'critical':'needs_care','needs_care':'needs_care',
                    'unknown':'unknown' }
        condition=conditions.get(health_key,health_key)
        matched_health=sub[sub.health_condition.fillna('').str.casefold()==condition]
        if len(matched_health):sub=matched_health
        else:
            unknown=sub[sub.health_condition.fillna('').str.casefold()=='unknown']
            if len(unknown):sub=unknown
        r=sub.iloc[0]
        food=float(r['estimated_food_g_per_day'])/1000
        care=(float(r['estimated_basic_work_min_per_day'])+float(r['estimated_extra_care_min_per_day']))/60
        size=str(r['size_class']);weight=float(r['estimated_weight_kg'])
    else:
        food=care=0.0;size='other';weight=-1.
    health=str(animal.get('health_status') or 'unknown')
    return dict(species=species,breed=breed or 'unknown',size_class=size,age_group=_age_group(years),health_at_intake=health,sex_at_intake=_sex(animal.get('sex')),age_years_at_intake=years,estimated_weight_kg=weight),food,care,bool(len(sub))

def resource_rate_for_animal(animal, resource):
    """Prefer real SQLite rates; fill each absent field using the existing species
    / breed / age / health resource crosswalk. Never silently replace a failure by 0.
    """
    _,table_food,table_care,matched=_profile(animal,resource)
    def measured(key):
        try:
            raw=animal.get(key)
            val=float(raw) if raw is not None else float('nan')
            return val if np.isfinite(val) and val>0 else None
        except (TypeError,ValueError):return None
    db_food=measured('food_grams_per_day')
    db_care=measured('routine_care_hours_per_day')
    if db_food is None or db_care is None:
        if not matched or not np.isfinite([table_food,table_care]).all() or table_food<=0 or table_care<=0:
            raise ValueError(f"動物 #{animal.get('id')} 的物種／年齡／健康條件缺少可用的資源對照表數值，無法完成需求估算")
    food=(db_food/1000) if db_food is not None else table_food
    care=db_care if db_care is not None else table_care
    source=('SQLite 個體參數' if db_food is not None and db_care is not None else
            'SQLite + 資源對照表補值' if db_food is not None or db_care is not None else
            '資源對照表補值（依物種／品種／年齡／健康）')
    return food,care,source

def _hazards(rows, days):
    bundle=hazard_bundle(); cats=bundle['categories'];models=bundle['models'];n=len(rows)
    if not n:return {},np.empty((0,len(days)))
    x=pd.DataFrame(rows)[CAT_COLS+NUM_COLS]
    length=len(days)
    x=x.loc[x.index.repeat(length)].reset_index(drop=True)
    for c in CAT_COLS:x[c]=pd.Categorical(x[c].fillna('unknown').astype(str),categories=cats[c]).codes.astype('int32')
    for c in NUM_COLS:x[c]=pd.to_numeric(x[c],errors='coerce').fillna(-1)
    x['day']=np.tile(days,n).astype('int32');x['log_day']=np.log1p(x['day'])
    preds={k:np.asarray(m.predict_proba(x)[:,1]).reshape(n,length) for k,m in models.items()}
    total=np.sum(list(preds.values()),axis=0)
    scale=np.maximum(total,1.0)
    return {k:v/scale for k,v in preds.items()},total/scale

def _conditional_survival(rows, ages, days):
    """Daily conditional S(d+t)/S(d), with an explicitly unvalidated constant-hazard tail.

    The trained discrete-time LightGBM only supports days <= max_day. Beyond it,
    keep the day feature at max_day (piecewise-exponential terminal hazard). This
    is a mathematical tail extension, NOT a newly trained or validated model.
    Computing forward probabilities directly avoids S(d) floating-point underflow.
    """
    if not rows:
        return np.empty((0,days)), {}, []
    max_day = int(hazard_bundle()['max_day'])
    future_days = np.stack([np.minimum(np.arange(age+1,age+days+1),max_day)
                            for age in ages])
    # Batch groups of equal ages to preserve per-row day input; for arbitrary
    # ages this reshapes the per-row time grid without constructing huge histories.
    stacked=[]
    for i,row in enumerate(rows):
        stacked.extend([row]*days)
    raw=pd.DataFrame(stacked)[CAT_COLS+NUM_COLS]
    for col in CAT_COLS:
        raw[col]=pd.Categorical(raw[col].fillna('unknown').astype(str),categories=hazard_bundle()['categories'][col]).codes.astype('int32')
    for col in NUM_COLS:raw[col]=pd.to_numeric(raw[col],errors='coerce').fillna(-1.)
    raw['day']=future_days.flatten().astype('int32')
    raw['log_day']=np.log1p(raw['day'])
    risks={cause:np.asarray(model.predict_proba(raw)[:,1]).reshape(len(rows),days)
           for cause,model in hazard_bundle()['models'].items()}
    total=np.sum(np.stack(list(risks.values())),axis=0)
    # Competing causes are conditional hazards within the SAME risk set.
    # Rescale only when their sum > 1, not independently normalized CIFs.
    denom=np.maximum(1.,total)
    risks={k:v/denom for k,v in risks.items()}
    total=np.clip(total/denom,0.,1.)
    conditional=np.cumprod(np.clip(1.-total,0.,1.),axis=1)
    return conditional,risks,[age+days>max_day for age in ages]


def animal_probabilities(animal,as_of,days=30):
    if not 1<=days<=30:raise ValueError('個體預測限定 1–30 天')
    max_day=int(hazard_bundle()['max_day'])
    age=max(0,(as_of-date.fromisoformat(str(animal['intake_date'])[:10])).days)
    row,_,_,_=_profile(animal,resource_table())
    surv,risks,extended=_conditional_survival([row],[age],days)
    previous=1.;cifs={k:0. for k in risks};result=[]
    for index in range(days):
        daily={cause:float(values[0,index]*previous) for cause,values in risks.items()}
        for cause,value in daily.items():cifs[cause]+=value
        previous=float(surv[0,index])
        result.append({'day':index+1,'survival_probability':previous,
             'daily_event_probabilities':daily.copy(),
             'cumulative_event_probabilities':cifs.copy()})
    return {'animal_id':animal['id'],'days_in_shelter':age,'as_of_date':as_of.isoformat(),
            'max_day':max_day,'predictions':result,'model':'LightGBM discrete-time competing risks',
            'conditional_formula':'S(d+t)/S(d)',
            'tail_extrapolated':extended[0],
            'warning':('此預測超出主要訓練資料範圍，可靠度未驗證；超過 '+str(max_day)+' 天的條件風險採末日固定 Hazard 延伸，並非新訓練模型。' if extended[0] else None)}

def predict_counts(days=30, species=None, as_of=None):
    models=count_models();df=daily_training()
    kinds=[species] if species else sorted(df.species.unique())
    all_rows=[]
    as_of=as_of or datetime.now(ZoneInfo("Asia/Taipei")).date()
    for kind in kinds:
        hist=df[(df.species==kind)&(df.date.dt.date<=as_of)].sort_values('date')
        if hist.empty:raise ValueError(f'資料沒有此物種：{kind}')
        # Split and calendar come from actual CSV. Future lags use recursive *predictions*.
        ins=list(hist.intake_count.astype(float));outs=list(hist.exit_count.astype(float));start=hist.date.max().date()
        warmup=max(0,(as_of-start).days)
        for k in range(1,warmup+days+1):
            dt=start+timedelta(days=k)
            features={'species':kind,'day_of_week':dt.weekday(),'month':dt.month,'day_of_year':dt.timetuple().tm_yday}
            for label,vals in [('intake',ins),('exit',outs)]:
                for lag in (1,7,14):features[f'{label}_lag_{lag}']=vals[-lag] if len(vals)>=lag else 0.
                for window in (7,30):features[f'{label}_rolling_{window}']=float(np.mean(vals[-window:])) if vals else 0.
            values={}
            for target in ('intake_count','exit_count'):
                model=models[target];frame=pd.DataFrame([features])[model.feature_names_]
                values[target]=max(0.,float(model.predict(frame)[0]))
            ins.append(values['intake_count']);outs.append(values['exit_count'])
            if dt>as_of:all_rows.append({'day':(dt-as_of).days,'date':dt.isoformat(),'species':kind,**values})
    return all_rows

@lru_cache(maxsize=1)
def training_duration_diagnostics():
    """Describe observable training coverage, NOT a long-stay calibration validation."""
    usecols=['split','duration_days','event_observed']
    df=pd.read_csv(require(ROOT/'inputs/lightgbm_hazard.csv'),usecols=usecols)
    train=df[df['split'].eq('train')]
    durations=pd.to_numeric(train['duration_days'],errors='coerce').dropna()
    if durations.empty:return {'warning':'訓練在所天數資料無法讀取'}
    return {'training_events':int(len(train)),
            'duration_percentiles':{'p50':float(durations.quantile(.5)),
                                    'p90':float(durations.quantile(.9)),
                                    'p95':float(durations.quantile(.95)),
                                    'p99':float(durations.quantile(.99))},
            'at_risk_by_day':{str(day):int((durations>=day).sum()) for day in (30,60,90,120,150,180)},
            'limitations':'存活至該天數的訓練樣本量不是長期分組 Brier Score；長期分組校準尚未驗證'}

@lru_cache(maxsize=1)
def long_stay_brier_diagnostics():
    """IPCW all-cause 30-day survival Brier at several landmark ages.

    Test subjects at risk at the landmark receive conditional predictions.
    Inverse probability of censoring weights use TRAIN-set Kaplan-Meier G.
    Empty risk sets are deliberately reported as unverified, not scored.
    """
    cols=['split','duration_days','event_observed']+CAT_COLS+NUM_COLS
    df=pd.read_csv(require(ROOT/'inputs/lightgbm_hazard.csv'),usecols=cols)
    train=df.loc[df['split'].eq('train')];test=df.loc[df['split'].eq('test')]
    tdur=pd.to_numeric(train.duration_days,errors='coerce').to_numpy(float)
    tcensor=(pd.to_numeric(train.event_observed,errors='coerce').to_numpy(float)==0)
    valid=np.isfinite(tdur)
    tdur=tdur[valid];tcensor=tcensor[valid]
    ordering=np.argsort(tdur);tdur=tdur[ordering];tcensor=tcensor[ordering]
    times,starts,counts=np.unique(tdur,return_index=True,return_counts=True)
    # G(t) = estimated probability of not being censored by t.
    at_risk=len(tdur)-starts
    censored=np.add.reduceat(tcensor.astype(int),starts)
    g_values=np.cumprod(1-censored/np.maximum(at_risk,1))
    def g(time):
        idx=np.searchsorted(times,np.asarray(time),side='right')-1
        return np.where(idx>=0,g_values[np.clip(idx,0,len(g_values)-1)],1.)
    out=[]
    durations=pd.to_numeric(test.duration_days,errors='coerce')
    observed=pd.to_numeric(test.event_observed,errors='coerce').eq(1)
    for landmark in (30,60,90,120,150,180):
        subset=test.loc[durations>=landmark]
        n=len(subset);future=landmark+30
        outcome=pd.to_numeric(subset.duration_days,errors='coerce').to_numpy(float)
        event=pd.to_numeric(subset.event_observed,errors='coerce').to_numpy(float)==1
        usable=(outcome>future)|((outcome<=future)&event)
        if n<30 or int(usable.sum())<30:
            out.append({'landmark_day':landmark,'forecast_days':30,'at_risk_test_n':n,
                        'observable_uncensored_n':int(usable.sum()),'brier_30d':None,
                        'status':'無足夠獨立測試樣本，分組 Brier 尚未驗證'})
            continue
        rows=subset[CAT_COLS+NUM_COLS].fillna('unknown').to_dict('records')
        survival,_,extended=_conditional_survival(rows,[landmark]*n,30)
        predicted=survival[:,-1]
        y=(outcome>future).astype(float)
        baseline=float(g(landmark))
        weights=np.zeros(n)
        weights[outcome>future]=baseline/max(float(g(future)),1e-12)
        ended=(outcome<=future)&event
        weights[ended]=baseline/np.maximum(g(outcome[ended]),1e-12)
        score=float(np.mean(weights*(y-predicted)**2))
        out.append({'landmark_day':landmark,'forecast_days':30,'at_risk_test_n':n,
                    'observable_uncensored_n':int(usable.sum()),'brier_30d':score,
                    'status':'測試集 IPCW 全原因存活 Brier（非各離所原因 CIF Brier）'})
    return out

def metrics_report(cause=None,species=None,horizon=30):
    report={'horizon_days':horizon,'model_status':{},'warnings':[], 'training_duration_diagnostics':training_duration_diagnostics(), 'long_stay_brier':long_stay_brier_diagnostics()}
    base=ROOT/'outputs/lightgbm_hazard';p=base/'metrics_by_cause.csv';cal=base/'calibration.csv'
    model=base/'best_models.pkl'
    if all(x.is_file() for x in (p,cal,model)):
        # Model/metrics provenance cannot be proven by timestamps alone.
        d=pd.read_csv(p); d=d[d.cause==cause] if cause else d
        report['lightgbm']={'metrics':d.replace({np.nan:None}).to_dict('records'),'scope':'整體獨立測試集；沒有物種個別 C-index / IBS', 'calibration':pd.read_csv(cal).query('horizon == @horizon'+(' and cause == @cause' if cause else '')).replace({np.nan:None}).to_dict('records'),'run_summary':read_json(base/'run_summary.json') if (base/'run_summary.json').exists() else None}
        if not report['lightgbm']['calibration']:report['warnings'].append(f'缺少 {horizon} 天的對應校準紀錄，不能宣稱已完成校準')
        if p.stat().st_mtime<model.stat().st_mtime or cal.stat().st_mtime<model.stat().st_mtime:report['warnings'].append('部分評估檔案早於模型檔案，需確認版本一致')
        report['warnings'].append('無模型與評估資料的共同雜湊／版本識別，僅可視為同一輸出資料夾的評估結果，無法完全證明版本吻合')
    else:report['warnings'].append('LightGBM 模型或評估檔案缺失')
    report['catboost']={}
    for target in ('intake_count','exit_count'):
        out=ROOT/'outputs/catboost'/target
        try:
            overall=read_json(out/'metrics.json')['metrics'];by=pd.read_csv(require(out/'metrics_by_species.csv'))
            if species:by=by[by.species.str.casefold()==species.casefold()]
            report['catboost'][target]={'overall_test':overall,'species_test':by.replace({np.nan:None}).to_dict('records'),'scope':'歷史 lag 單步測試，不能代表多日遞迴預測誤差'}
            if species and by.empty:report['warnings'].append(f'{target} 沒有物種 {species} 的個別評估指標')
        except (FileNotFoundError,KeyError) as exc:report['warnings'].append(str(exc))
    try:
        quality=read_json(ROOT/'inputs/data_report.json'); report['data_quality']=quality
    except (FileNotFoundError,ValueError):report['warnings'].append('缺少資料品質報告')
    return report

def resource_forecast(animals, as_of, days=30, simulations=600, seed=20261023):
    """Thirty-day food/care scenario: surviving current cohort plus net NEW arrivals.

    Exit forecasts are applied ONLY to new-arrival cohort, not existing survivors,
    otherwise the same departure is subtracted twice. Ranges are uncalibrated
    Monte Carlo quantiles, not independently validated prediction intervals.
    """
    if not 1 <= days <= 30: raise ValueError('資源需求限 1–30 天')
    resource=resource_table();max_day=int(hazard_bundle()['max_day']);warnings=[]
    coverage=training_duration_diagnostics()
    p95=coverage.get('duration_percentiles',{}).get('p95',float('inf'))
    rows=[];ages=[];rates=[];long_count=0;imputed_count=0;individual=[]
    # Fail explicitly on invalid animal records; reporting a fake 80/80 is forbidden.
    for a in animals:
        row,_,_,_=_profile(a,resource)
        try:
            intake=date.fromisoformat(str(a.get('intake_date') or '')[:10])
            if intake>as_of:raise ValueError('入所日期晚於預測基準日')
            age=(as_of-intake).days
        except (ValueError,TypeError) as exc:
            raise ValueError(f"動物 #{a.get('id')} 入所日期無效 ({a.get('intake_date')!r})：{exc}") from exc
        food,care,source=resource_rate_for_animal(a,resource)
        if source!='SQLite 個體參數':imputed_count+=1
        if age+days>max_day:
            long_count+=1
            warnings.append(f"#{a['id']} 在所 {age} 天：超出訓練最大天數 {max_day}；以末日 Hazard 尾端外推，未經驗證")
        elif age+days>p95:
            long_count+=1
            warnings.append(f"#{a['id']} 在所 {age} 天：超過訓練資料 P95，可靠度未經長期驗證")
        rows.append(row);rates.append((food,care));ages.append(age)
        individual.append({'animal_id':a['id'],'animal_name':a.get('name'),
                           'days_in_shelter':age,'food_kg_per_day':round(food,5),
                           'care_hours_per_day':round(care,5),'resource_source':source,
                           'tail_extrapolated':age+days>max_day})
    survivors,_,extended=_conditional_survival(rows,ages,days)
    for i,record in enumerate(individual):
        record['conditional_survival_30d']=float(survivors[i,-1])
        record['conditional_survival_by_day']=[float(x) for x in survivors[i]]
    rng=np.random.default_rng(seed)
    current_food=np.asarray([r[0] for r in rates]);current_care=np.asarray([r[1] for r in rates])
    # One uniform per animal per simulation preserves monotonic survival trajectories.
    retained=(rng.random((simulations,len(rows),1))<survivors[None,:,:]) if rows else np.zeros((simulations,0,days),dtype=bool)
    food_sample=np.einsum('snt,n->st',retained,current_food)
    care_sample=np.einsum('snt,n->st',retained,current_care)
    food_mean=survivors.T@current_food if rows else np.zeros(days)
    care_mean=survivors.T@current_care if rows else np.zeros(days)
    # Species-specific proxy rates come from actual parameter table and its sample counts.
    # No future entrant profile is known; these are documented simulation assumptions.
    typical={}
    for sp,group in resource.groupby('species'):
        typical[str(sp)]=(float(group.estimated_food_g_per_day.mean())/1000,
                          float((group.estimated_basic_work_min_per_day+group.estimated_extra_care_min_per_day).mean())/60)
    counts=predict_counts(days,as_of=as_of)
    by_species={}
    for rec in counts:by_species.setdefault(rec['species'],{})[rec['day']]=rec
    missing=[k for k in by_species if k not in typical]
    if missing: warnings.append(f'缺少以下物種的資源係數：{missing}；未加入其新入所需求')
    # Cumulative new cohort: sum predicted intakes minus exits, clipped at zero.
    # This is a modeling approximation, not a calibrated joint generative model.
    flow_food=np.zeros(days);flow_care=np.zeros(days)
    for sp,lookup in by_species.items():
        if sp not in typical:continue
        f,c=typical[sp];arr=np.array([max(0.,lookup[d]['intake_count']) for d in range(1,days+1)])
        gross_dep=np.array([max(0.,lookup[d]['exit_count']) for d in range(1,days+1)])
        # CatBoost predicts exits from ALL animals. Current animals' departures are
        # already counted by LightGBM conditional survival. Deduct that part first;
        # only the residual exits can reduce the predicted NEW-arrival cohort.
        species_index=[j for j,row in enumerate(rows) if row['species'].casefold()==sp.casefold()]
        existing_survival=survivors[species_index,:] if species_index else np.zeros((0,days))
        previous=np.concatenate([np.ones((len(species_index),1)),existing_survival[:,:-1]],axis=1)
        existing_daily_departures=(previous-existing_survival).sum(axis=0)
        dep=np.maximum(0.,gross_dep-existing_daily_departures)
        mu=np.zeros(days)
        running=0.
        for t in range(days):
            running=max(0.,running+arr[t]-dep[t]);mu[t]=running
        flow_food+=mu*f;flow_care+=mu*c
        sample_arr=rng.poisson(arr[None,:],size=(simulations,days))
        gross_sample_dep=rng.poisson(gross_dep[None,:],size=(simulations,days))
        # Paired simulated existing exits prevent subtracting the same departure
        # once via conditional survival and again via new-cohort flow.
        if species_index:
            kept=retained[:,species_index,:]
            previous_kept=np.concatenate([np.ones((simulations,len(species_index),1),dtype=bool),kept[:,:,:-1]],axis=2)
            simulated_existing_exits=np.sum(previous_kept & ~kept,axis=1)
        else:
            simulated_existing_exits=np.zeros((simulations,days))
        sample_dep=np.maximum(0.,gross_sample_dep-simulated_existing_exits)
        sample_cohort=np.zeros(simulations)
        for t in range(days):
            sample_cohort=np.maximum(0,sample_cohort+sample_arr[:,t]-sample_dep[:,t])
            food_sample[:,t]+=sample_cohort*f
            care_sample[:,t]+=sample_cohort*c
    food_mean+=flow_food;care_mean+=flow_care
    points=[]
    for j in range(days):
        food_lo,food_hi=np.quantile(food_sample[:,j],[.05,.95]);care_lo,care_hi=np.quantile(care_sample[:,j],[.05,.95])
        points.append({'date':(as_of+timedelta(days=j+1)).isoformat(),
            'expected_food_kg':round(float(food_mean[j]),2),
            'food_lower_kg':round(float(food_lo),2),'food_upper_kg':round(float(food_hi),2),
            'expected_care_hours':round(float(care_mean[j]),2),
            'care_lower_hours':round(float(care_lo),2),'care_upper_hours':round(float(care_hi),2)})
    all_rates=[_profile(a,resource) for a in animals]
    return {'mode':'hazard_survival_plus_catboost_net_new_cohort_monte_carlo',
      'forecast':points,'daily_food_kg':round(sum(x[1] for x in all_rates if x[3]),2),
      'daily_care_hours':round(sum(x[2] for x in all_rates if x[3]),2),
      'animal_count':len(animals),'estimated_animals':len(rows),'extrapolated_or_sparse_animals':long_count,
      'imputed_animals':imputed_count,'individual_predictions':individual,
      'start_date':(as_of+timedelta(days=1)).isoformat(),
      'monte_carlo':{'simulations':simulations,'seed':seed,'quantiles':[.05,.95],
         'assumptions':'存活伯努利抽樣 + 各物種每日入所／離所獨立 Poisson；物種平均資源係數；未經回測校準'},
      'note':f'{(as_of+timedelta(days=1)).isoformat()} 起 {days} 天：已在所個體條件存活率×個體資源 + 各物種累積預測入所×物種平均資源 − 各物種新增群體累積預測離所×物種平均資源（總離所先扣除現有群體預期離所，避免重複扣除）；Monte Carlo 600 次，第5–95百分位為模擬情境帶，非95%信賴區間。現有個體有資源參數者 {len(rows)}/{len(animals)} 隻，其中 {long_count} 隻涉及稀疏／未驗證尾端延伸、{imputed_count} 隻使用資源對照表補值；缺漏動物不代表零需求。',
      'warnings':warnings,
      'training_duration_diagnostics':coverage,
      'metrics':metrics_report(horizon=days)}
