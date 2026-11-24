export function Loading() {
  return <p className="muted" role="status">載入中…</p>;
}

export function ErrorView({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return <p role="alert" className="text-red-700">發生錯誤：{message}</p>;
}

export function Empty({ text = "目前沒有資料" }: { text?: string }) {
  return <p className="muted">{text}</p>;
}

export function MockFlag({ mock, mode, mlStatus }: { mock?: boolean; mode?: string; mlStatus?: string }) {
  if (mode === "rule_based") {
    return (
      <span className="inline-flex gap-2">
        <span role="status" className="bg-sky-100 text-sky-900 px-2 py-1 rounded text-xs">照護規則評估可使用</span>
        {mlStatus === "real" && <span role="status" className="bg-emerald-100 text-emerald-900 px-2 py-1 rounded text-xs">機器學習健康分類已啟用</span>}
        {(mlStatus === "unavailable" || mlStatus === "not_trained") && <span role="status" className="bg-slate-200 text-slate-800 px-2 py-1 rounded text-xs">機器學習健康分類尚未啟用</span>}
      </span>
    );
  }
  if (mlStatus === "unavailable") return <span role="status" className="bg-slate-200 text-slate-800 px-2 py-1 rounded text-xs">UNAVAILABLE：沒有機器學習模型</span>;
  const isMock = mock || mode === "mock";
  if (isMock) return <span role="status" className="bg-amber-100 text-amber-900 px-2 py-1 rounded text-xs">MOCK：非模型預測</span>;
  return <span role="status" className="bg-emerald-100 text-emerald-900 px-2 py-1 rounded text-xs">REAL：模型已執行，不代表已經驗證準確</span>;
}

export function Warnings({ items }: { items?: string[] }) {
  if (!items?.length) return null;
  return (
    <ul className="muted list-disc pl-5">
      {items.map((item) => <li key={item}>{item}</li>)}
    </ul>
  );
}
