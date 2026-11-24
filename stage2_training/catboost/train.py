import argparse,json,sys
from pathlib import Path
import numpy as np,pandas as pd,optuna
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error,mean_squared_error
ROOT=Path(__file__).resolve().parents[1]
TARGETS=['intake_count','exit_count']
def scores(y,p):
    y=np.asarray(y);p=np.maximum(np.asarray(p),0)
    return {'MAE':float(mean_absolute_error(y,p)),'RMSE':float(np.sqrt(mean_squared_error(y,p))),'WAPE':float(np.sum(np.abs(y-p))/np.sum(np.abs(y))*100) if np.sum(np.abs(y))>0 else None,'bias':float(np.mean(p-y))}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--trials',type=int,default=50);ap.add_argument('--output',default=str(ROOT/'outputs/catboost'));a=ap.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(ROOT/'inputs/catboost_daily.csv');df=df.sort_values('date');features=[c for c in df if c not in ['date','split']+TARGETS]
    df['species']=df.species.fillna('Unknown').astype(str)
    train=df[df.split=='train'];val=df[df.split=='val'];test=df[df.split=='test'];result={};interrupted=False
    for target in TARGETS:
        od=out/target;od.mkdir(exist_ok=True)
        study=optuna.create_study(direction='minimize',study_name=target,storage=f'sqlite:///{(od/"optuna.db").as_posix()}',load_if_exists=True)
        def objective(t):
            pars=dict(iterations=t.suggest_int('iterations',200,700),depth=t.suggest_int('depth',4,8),learning_rate=t.suggest_float('learning_rate',.02,.15,log=True),l2_leaf_reg=t.suggest_float('l2_leaf_reg',1,12,log=True))
            model=CatBoostRegressor(loss_function='Poisson',verbose=False,thread_count=4,random_seed=42,**pars)
            model.fit(train[features],train[target],cat_features=['species'],eval_set=(val[features],val[target]),early_stopping_rounds=50,verbose=False)
            return mean_absolute_error(val[target],np.maximum(0,model.predict(val[features])))
        try:study.optimize(objective,n_trials=a.trials)
        except KeyboardInterrupt:interrupted=True
        study.trials_dataframe().to_csv(od/'optuna_trials.csv',index=False)
        done=[t for t in study.trials if t.state==optuna.trial.TrialState.COMPLETE]
        if not done:result[target]={'status':'no_completed_trial'};continue
        best=study.best_trial
        combined=pd.concat([train,val]);model=CatBoostRegressor(loss_function='Poisson',verbose=False,thread_count=4,random_seed=42,**best.params)
        model.fit(combined[features],combined[target],cat_features=['species'],verbose=False)
        model.save_model(str(od/'best_model.cbm'))
        p=np.maximum(model.predict(test[features]),0)
        pred=test[['date','species',target]].copy();pred['prediction']=p;pred.to_csv(od/'test_predictions.csv',index=False)
        overall=scores(test[target],p);per=[]
        for species,part in pred.groupby('species'):
            per.append({'species':species,**scores(part[target],part.prediction)})
        pd.DataFrame(per).to_csv(od/'metrics_by_species.csv',index=False)
        pd.DataFrame({'feature':features,'importance':model.feature_importances_}).sort_values('importance',ascending=False).to_csv(od/'feature_importance.csv',index=False)
        result[target]={'metrics':overall,'best_trial':best.number,'best_validation_MAE':best.value,'best_parameters':best.params,'completed_trials_total':len(done)}
        (od/'metrics.json').write_text(json.dumps(result[target],indent=2))
        if interrupted:break
    (out/'run_summary.json').write_text(json.dumps({'interrupted':interrupted,'targets':result},indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
