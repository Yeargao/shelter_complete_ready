import type { ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ErrorView, Loading } from "../components/common/States";
import { api } from "../services/api";

type Metric = Record<string, unknown>;

function percent(value: unknown) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
}

function number(value: unknown, digits = 4) {
  return typeof value === "number" ? value.toFixed(digits) : "—";
}

export default function EvaluationPage() {
  const qc = useQueryClient();
  const reset = useMutation({mutationFn:api.resetTasksPending,onSuccess:()=>{void qc.invalidateQueries({queryKey:['tasks']});void qc.invalidateQueries({queryKey:['staff-assignments']});void qc.invalidateQueries({queryKey:['staffAssignments']});}});
  const query = useQuery({ queryKey: ["evaluation"], queryFn: () => api.evaluation() });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorView error={query.error} />;
  const models = (query.data?.models || {}) as Record<string, Metric>;
  const shown = Object.entries(models).filter(([, model]) => model.status === "evaluated");

  return (
    <section className="space-y-5">
      <div>
        <h1 className="mb-2">模型評估</h1>
        <p className="muted">僅呈現已保存、可核對的機器學習測試結果，不重新訓練或填入示意分數。</p>
        <button type="button" className="secondary mt-3" disabled={reset.isPending} onClick={()=>{if(window.confirm("確定重置所有任務為未完成，並清除衍生任務？"))reset.mutate()}}>{reset.isPending?"重置中…":"重置任務（全部未完成）"}</button>
        {reset.isSuccess&&<p role="status">任務已重置，清除 {reset.data.derived_tasks_cleared} 項衍生任務。</p>}
        {reset.error&&<ErrorView error={reset.error}/>}
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        {shown.map(([name, model]) => <Card key={name} name={name} model={model} />)}
      </div>
      <Stage2Evaluation />
    </section>
  );
}

function Card({ name, model }: { name: string; model: Metric }) {
  if (name === "adoption_catboost") return <Adoption model={model} />;
  if (name === "health_catboost") return <Health model={model} />;
  if (name === "occupancy_catboost") return <Occupancy model={model} />;
  return null;
}

function Shell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <article className="panel space-y-3 border-t-4 border-teal-700 shadow-md">
      <div>
        <h2 className="mb-1">{title}</h2>
        <p className="muted">{subtitle}</p>
      </div>
      {children}
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}

function Adoption({ model }: { model: Metric }) {
  return (
    <Shell title="送養速度分類" subtitle="CatBoost · AdoptionSpeed 第 0 到第 4 類，不是天數">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Accuracy" value={percent(model.accuracy)} />
        <Stat label="Macro-F1" value={percent(model.macro_f1)} />
        <Stat label="QWK" value={number(model.quadratic_weighted_kappa)} />
      </div>
      <p className="muted">Accuracy（%）是分類正確比例；Macro-F1（%）是各類別 F1 的平均，兼顧少數類別；QWK（無單位，通常 -1～1）衡量有序類別的一致程度。</p>
      <p className="muted">測試 {String(model.test_rows)} 筆 · 依救援者分組，這頁沒有重新訓練。</p>
    </Shell>
  );
}

function Health({ model }: { model: Metric }) {
  return (
    <Shell title="健康分類" subtitle="CatBoost · PetFinder 健康標籤，不是醫療診斷">
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Accuracy" value={percent(model.accuracy)} />
        <Stat label="Macro-F1" value={percent(model.macro_f1)} />
      </div>
      <p className="muted">Accuracy（%）是正確分類比例。<br/>Macro-F1（%）是各類別 F1 的算術平均，能觀察少數類別表現。</p>
      <p className="muted">測試 {String(model.test_rows)} 筆。Accuracy 受健康標籤多數類影響，請同時看 Macro-F1。{String(model.not_a_diagnosis || "")}</p>
    </Shell>
  );
}

function Occupancy({ model }: { model: Metric }) {
 const rows=Array.isArray(model.metrics)?model.metrics as Metric[]:[];
 return <Shell title="收容數量預測" subtitle="CatBoost + Optuna · 每日入所與離所回歸模型 · 單步測試">
 <table className="data-table"><thead><tr><th>目標</th><th>MAE（隻／日）</th><th>RMSE（隻／日）</th><th>WAPE（%）</th></tr></thead><tbody>{rows.map(r=><tr key={String(r.target)}><td>{r.target==='intakes'?'入所':'離所'}</td><td>{number(r.mae,2)}</td><td>{number(r.rmse,2)}</td><td>{number(r.wape_percent,2)}%</td></tr>)}</tbody></table><p className="muted">MAE（隻／日）：平均絕對誤差，越小越好。<br/>RMSE（隻／日）：均方根誤差，對較大誤差更敏感。<br/>WAPE（%）：絕對誤差總和占實際值總和的比例，越低越好。<br/>數據直接讀取 models/best_params_and_metrics.json；此指標為單步測試，不代表多日遞迴預測誤差。</p></Shell>
}

function Stage2Evaluation(){
 const state=useQuery({queryKey:['stage2-evaluation',30],queryFn:api.stage2Evaluation});
 if(state.isLoading)return <p className="muted">載入 Stage 2 測試結果中…</p>;
 if(state.error)return <p className="muted">Stage 2 指標無法讀取：{String(state.error)}</p>;
 const result=state.data;const metrics=result?.lightgbm?.metrics||[];
 return <div className="space-y-4">
  <Shell title="離所競爭風險模型" subtitle="LightGBM · Discrete-Time Hazard · 獨立測試資料（全物種合併）">
   <div className="overflow-x-auto"><table className="data-table"><thead><tr><th>離所原因</th><th>Cause-specific C-index</th><th>IBS</th><th>30天 Brier</th></tr></thead><tbody>{metrics.map((r:any)=><tr key={r.cause}><td>{r.cause}</td><td>{number(r.cause_specific_c_index)}</td><td>{number(r.integrated_brier_score)}</td><td>{number(r.brier_30d)}</td></tr>)}</tbody></table></div>
   <p className="muted">C-index：特定離所原因的風險排序能力，約 0.5 接近隨機；不是準確率。IBS：指定評估日的 Brier 誤差梯形積分近似，越低通常越好，需要基準比較；30天 Brier：30天預測機率的平方誤差，越小越好。</p>
   <p className="muted">30天 Calibration：共 {result?.lightgbm?.calibration?.length??0} 個原因×分組記錄。應比較各組 predicted、observed 與 n；分組不代表個體機率已精確校準。沒有物種專屬 C-index / IBS。</p>
   <details><summary className="cursor-pointer font-semibold">檢視各離所原因 × 校準分組（實際測試數據）</summary>
    <div className="overflow-x-auto max-h-80 overflow-y-auto"><table className="data-table"><thead><tr><th>事件</th><th>分組</th><th>樣本數</th><th>預測機率</th><th>觀察發生率</th><th>差距</th></tr></thead><tbody>{(result?.lightgbm?.calibration||[]).map((r:any,i:number)=><tr key={i}><td>{r.cause}</td><td>{r.bin}</td><td>{r.n}</td><td>{percent(r.predicted)}</td><td>{percent(r.observed)}</td><td>{typeof r.predicted==='number'&&typeof r.observed==='number'?`${(100*(r.predicted-r.observed)).toFixed(2)} 百分點`:'—'}</td></tr>)}</tbody></table></div>
    <p className="muted">預測機率與觀察發生率越接近，代表分組校準越佳；不代表每一隻動物都能達到相同誤差。必須留意設限處理與分組樣本數。</p>
   </details>
   <details open><summary className="cursor-pointer font-semibold">長期在所資料分布及 30 天分組 Brier 驗證狀態</summary>
    <p className="muted">訓練時間 P95：{result?.training_duration_diagnostics?.duration_percentiles?.p95??'—'} 天；原模型訓練日數上限 180 天。超過 180 天時採末日 Hazard 常數尾端延伸，並非已訓練或已驗證的任意天數模型。</p>
    <div className="overflow-x-auto"><table className="data-table"><thead><tr><th>基準在所天數</th><th>測試集仍在風險數</th><th>30天 Brier</th><th>驗證狀態</th></tr></thead><tbody>{(result?.long_stay_brier||[]).map((r:any)=><tr key={r.landmark_day}><td>{r.landmark_day}</td><td>{r.at_risk_test_n}</td><td>{number(r.brier_30d)}</td><td>{r.status}</td></tr>)}</tbody></table></div>
    <p className="muted">此預測超出主要訓練資料範圍，可靠度未驗證。沒有獨立測試樣本時不能用訓練資料冒充分組 Brier。</p>
   </details>
  </Shell>
  <Shell title="每日出入所數量模型" subtitle="CatBoost · 獨立測試資料 · 歷史 lag 單步測試">
   <table className="data-table"><thead><tr><th>預測目標</th><th>MAE（隻）</th><th>RMSE（隻）</th><th>WAPE（%）</th></tr></thead><tbody>{(['intake_count','exit_count'] as const).map(k=>{const m=result?.catboost?.[k]?.overall_test||{};return <tr key={k}><td>{k==='intake_count'?'入所':'離所'}</td><td>{number(m.MAE,2)}</td><td>{number(m.RMSE,2)}</td><td>{number(m.WAPE,2)}</td></tr>})}</tbody></table>
   <p className="muted">MAE：平均絕對誤差；RMSE：更重視大型誤差；WAPE：總絕對誤差／實際總量，實際總量為零時不適用。均不能換算成準確率；單步測試不代表30天遞迴預測已驗證。</p>
   <details><summary className="cursor-pointer font-semibold">依動物種類顯示測試誤差</summary>
    <div className="overflow-x-auto"><table className="data-table"><thead><tr><th>目標</th><th>種類</th><th>MAE</th><th>RMSE</th><th>WAPE</th></tr></thead><tbody>{(['intake_count','exit_count'] as const).flatMap(k=>(result?.catboost?.[k]?.species_test||[]).map((r:any,i:number)=><tr key={`${k}-${i}`}><td>{k==='intake_count'?'入所':'離所'}</td><td>{r.species}</td><td>{number(r.MAE??r.mae,2)}</td><td>{number(r.RMSE??r.rmse,2)}</td><td>{number(r.WAPE??r.wape,2)}</td></tr>))}</tbody></table></div>
   </details>
  </Shell>
  {(result?.warnings||[]).length>0&&<p className="muted">評估限制：{result.warnings.join('；')}</p>}
 </div>;
}
