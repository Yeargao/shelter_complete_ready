import numpy as np
import pandas as pd

def censor_km(duration, event_observed):
    """Kaplan-Meier for censoring, treating any observed event as non-censoring."""
    d=np.asarray(duration,int); cens=(np.asarray(event_observed)==0)
    times=np.unique(d); at_risk=np.array([(d>=t).sum() for t in times]); n_c=np.array([((d==t)&cens).sum() for t in times]);
    surv=np.cumprod(1-n_c/np.maximum(at_risk,1));return times,surv

def g_at(km,t,strict=False):
    times,sv=km; idx=np.searchsorted(times,t,side='left' if strict else 'right')-1
    return np.where(idx>=0,sv[np.maximum(idx,0)],1.)

def cause_cindex(duration,event,cause,risk):
    """Cause-specific concordance: other causes censored; pairs comparable when earlier event is the target cause."""
    d=np.asarray(duration);e=np.asarray(event);r=np.asarray(risk)
    order=np.argsort(d);d=d[order];e=e[order];r=r[order]
    total=good=0.
    for i in np.where(e==cause)[0]:
        other=r[d>d[i]];total+=len(other);good+=(r[i]>other).sum()+0.5*(r[i]==other).sum()
    return float(good/total) if total else None

def brier_cif(duration,event,event_observed,cause,pred,t,km):
    """IPCW Brier score for cumulative incidence; competing events count as known non-target outcomes."""
    d=np.asarray(duration);e=np.asarray(event);obs=np.asarray(event_observed)
    target=((d<=t)&(e==cause)).astype(float)
    w=np.where((d<=t)&(obs==1),1/np.maximum(g_at(km,d,strict=True),.05),np.where(d>t,1/np.maximum(g_at(km,t),.05),0.))
    return float(np.sum(w*(target-pred)**2)/max(np.sum(w),1))

def calibration_cif(duration,event,event_observed,cause,pred,t,km,bins=5):
    d=np.asarray(duration);e=np.asarray(event);obs=np.asarray(event_observed);p=np.asarray(pred)
    w=np.where((d<=t)&(obs==1),1/np.maximum(g_at(km,d,strict=True),.05),np.where(d>t,1/np.maximum(g_at(km,t),.05),0.))
    y=((d<=t)&(e==cause)).astype(float)
    out=[]
    for ix in np.array_split(np.argsort(p),bins):
        ww=w[ix];out.append(dict(n=int(len(ix)),predicted=float(p[ix].mean()),observed=float(np.sum(ww*y[ix])/np.sum(ww)) if ww.sum()>0 else None))
    return out
