import {PhotoComparison} from '../common/SmartPanels';
import {taipeiToday} from '../common/scheduleDates';
import { useState } from "react";
import CameraCapture from '../common/CameraCapture';
import {api,type PhotoObservation} from '../../services/api';
import type { AnimalInput } from "../../types";

const defaults: AnimalInput = {
  name: "",
  species: "dog",
  breed: null,
  age_months: null,
  sex: "unknown",
  health_status: "unknown",
  vaccinated: "unknown",
  sterilized: "unknown",
  dewormed: "unknown",
  intake_date: new Date().toISOString().slice(0, 10),
  photo_url: null,
};

export default function AnimalForm({ initial, onSubmit, photoCacheId, animalId }: { initial?: AnimalInput; onSubmit: (animal: AnimalInput) => Promise<void>; photoCacheId?:string; animalId?:number }) {
  const [values, setValues] = useState<AnimalInput>(initial || defaults);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [analysis,setAnalysis]=useState<PhotoObservation>();
  const [analyzing,setAnalyzing]=useState(false);
  const [photoError,setPhotoError]=useState('');
  const dataPhoto=values.photo_url?.startsWith('data:image/jpeg;base64,')?values.photo_url.split(',')[1]:null;
  const update = (key: keyof AnimalInput, value: AnimalInput[keyof AnimalInput]) => setValues((prev) => ({ ...prev, [key]: value }));

  return (
    <form className="panel grid md:grid-cols-2 gap-4" onSubmit={async (event) => {
      event.preventDefault();
      setBusy(true);
      setError("");
      try {
        if(!values.name.trim())throw Error('請填寫動物名稱');
        if(values.intake_date>taipeiToday())throw Error('入所日期不能晚於今日');
        await onSubmit({...values,name:values.name.trim()});
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    }}>
      <label>名稱<input required value={values.name} onChange={(event) => update("name", event.target.value)} /></label>
      <label>種類<select value={values.species} onChange={(event) => update("species", event.target.value as AnimalInput["species"])}>{["dog", "cat", "other"].map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>品種<input value={values.breed || ""} onChange={(event) => update("breed", event.target.value || null)} /></label>
      <label>年齡（月）<input type="number" min="0" value={values.age_months ?? ""} onChange={(event) => update("age_months", event.target.value === "" ? null : Number(event.target.value))} /></label>
      <label>性別<select value={values.sex} onChange={(event) => update("sex", event.target.value as AnimalInput["sex"])}>{["unknown", "male", "female"].map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>健康狀況<select value={values.health_status} onChange={(event) => update("health_status", event.target.value)}>{["unknown", "healthy", "needs_review", "serious"].map((item) => <option key={item}>{item}</option>)}</select></label>
      {(["vaccinated", "sterilized", "dewormed"] as const).map((key) => (
        <label key={key}>{key}
          <select value={values[key]} onChange={(event) => update(key, event.target.value as AnimalInput["vaccinated"])}>
            <option value="unknown">未知</option>
            <option value="yes">是</option>
            <option value="no">否</option>
          </select>
        </label>
      ))}
      <label>入所日期<input required type="date" max={taipeiToday()} value={values.intake_date} onChange={(event) => update("intake_date", event.target.value)} /></label>
      <div className="md:col-span-2 space-y-2">
       <label>照片 URL（選填）<input value={dataPhoto?'':values.photo_url||''} disabled={busy||analyzing} onChange={event=>{update('photo_url',event.target.value||null);setAnalysis(undefined);setPhotoError('');}} /></label>
       <CameraCapture disabled={busy||analyzing} onPhoto={photo=>{update('photo_url',photo);setAnalysis(undefined);setPhotoError('');}}/>
       {dataPhoto&&<><img className="rounded-lg max-w-xs w-full" src={values.photo_url||''} alt="動物照片預覽"/>
        <div className="flex flex-wrap gap-2">
         <button type="button" className="secondary" disabled={busy||analyzing} onClick={async()=>{setAnalyzing(true);setPhotoError('');setAnalysis(undefined);try{setAnalysis(await api.analyzePhoto(dataPhoto));}catch(e){setPhotoError(e instanceof Error?e.message:String(e));}finally{setAnalyzing(false);}}}>{analyzing?'AI 分析中…':'Gemini 辨識外觀'}</button>
         <button type="button" className="secondary" disabled={busy||analyzing} onClick={()=>{update('photo_url',null);setAnalysis(undefined);setPhotoError('');}}>移除照片</button>
        </div></>}
       {photoError&&<p role="alert">{photoError}</p>}
       {analysis&&<div className="rounded-lg border p-3 space-y-2"><strong>AI 外觀建議（須人工確認）</strong>
        <p>種類：{analysis.species} · 可能品種：{analysis.breed||'不確定'} · 毛色：{analysis.coat_color||'不確定'}</p>
        <p>{analysis.observation}</p><p>照片品質：{analysis.image_quality}</p>
        <button type="button" className="secondary" disabled={busy||analysis.image_quality==='unusable'} onClick={()=>{const species=analysis.species;setValues(v=>({...v,species:species==='unknown'?v.species:species,breed:analysis.breed||v.breed}));}}>套用種類與品種建議</button>
        <p className="muted">毛色僅作觀察提示；不由照片判斷健康、年齡、性別或醫療紀錄。</p>
       </div>}
      </div>
      {photoCacheId&&<PhotoComparison cacheId={photoCacheId} currentPhoto={values.photo_url} animalId={animalId} embedded/>}
      <div className="md:col-span-2">
        {error && <p role="alert" className="text-red-700">{error}</p>}
        <button disabled={busy||analyzing}>{busy ? "儲存中…" : "儲存動物"}</button>
      </div>
    </form>
  );
}
