import {PhotoComparison} from '../common/SmartPanels';
import {taipeiToday} from '../common/scheduleDates';
import { useState } from "react";
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
      <label>照片 URL（選填）<input value={values.photo_url || ""} onChange={(event) => update("photo_url", event.target.value || null)} /></label>
      {photoCacheId&&<PhotoComparison cacheId={photoCacheId} currentPhoto={values.photo_url} animalId={animalId} embedded/>}
      <div className="md:col-span-2">
        {error && <p role="alert" className="text-red-700">{error}</p>}
        <button disabled={busy}>{busy ? "儲存中…" : "儲存動物"}</button>
      </div>
    </form>
  );
}
