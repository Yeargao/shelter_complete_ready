"""Fetch 162 distinct Austin Animal Center intakes from 2026-10-23 onward.

Run from project root: python tools/import_austin_162.py
Then inspect the CSV and explicitly apply: python tools/import_austin_162.py --apply
Requires internet; Python standard library only. --apply backs up SQLite first.
"""
import argparse, csv, json, shutil, sqlite3, urllib.parse, urllib.request
from pathlib import Path
from datetime import date
import ssl
import certifi

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'austin_intakes_2026-10-23_162.csv'
DB = ROOT/'showcase.sqlite3'
FIELDS=['id','source_date','animal_id','type','name_at_intake','sex','primary_breed','intake_health_condition','date_of_birth','ispreviouslyspayedneutered']

def download():
    params={'$where':"source_date >= '2026-10-23T00:00:00'",'$order':'source_date ASC, id ASC','$limit':'5000','$select':','.join(FIELDS)}
    url='https://data.austintexas.gov/resource/pyqf-r2dc.json?'+urllib.parse.urlencode(params)
    context = ssl.create_default_context(
        cafile=certifi.where()
    )

    with urllib.request.urlopen(
            urllib.request.Request(
                url,
                headers={'User-Agent': 'ShelterAI-academic-demo/1.0'}
            ),
            timeout=45,
            context=context
    ) as r:
        data = json.load(r)
    seen=set(); selected=[]
    for item in data:
        animal_id=item.get('animal_id')
        if not animal_id or animal_id in seen: continue
        seen.add(animal_id); selected.append(item)
        if len(selected)==162:break
    if len(selected)<162:raise RuntimeError(f'官方資料符合條件的不同動物僅 {len(selected)} 隻；未產生或覆蓋任何檔案')
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows([{k:r.get(k,'') for k in FIELDS} for r in selected])
    print(f'已下載 {len(selected)} 筆至 {OUT}')
    return selected

def apply(rows):
    if not DB.exists():raise FileNotFoundError(f'找不到 {DB}，請先啟動後端建立資料庫')
    backup=DB.with_name('showcase.before_austin_import.sqlite3')
    shutil.copy2(DB,backup)
    with sqlite3.connect(DB) as con:
        con.execute('DELETE FROM assignment_snapshot');con.execute('DELETE FROM task_overrides');con.execute('DELETE FROM animals')
        for r in rows:
            kind=(r.get('type') or '').lower()
            species='dog' if 'dog' in kind else 'cat' if 'cat' in kind else 'other'
            sexraw=(r.get('sex') or '').lower()
            sex='female' if 'female' in sexraw else 'male' if 'male' in sexraw else 'unknown'
            healthraw=(r.get('intake_health_condition') or '').lower()
            health='healthy' if healthraw in ('normal','healthy') else 'needs_review' if healthraw else 'unknown'
            dob=(r.get('date_of_birth') or '')[:10];intake=(r.get('source_date') or '')[:10]
            months=None
            try:
                d0=date.fromisoformat(dob);d1=date.fromisoformat(intake);months=max(0,(d1.year-d0.year)*12+d1.month-d0.month-(d1.day<d0.day))
            except ValueError:pass
            sterilized='yes' if str(r.get('ispreviouslyspayedneutered','')).lower()=='true' else 'unknown'
            con.execute('INSERT INTO animals (name,species,breed,age_months,sex,health_status,vaccinated,sterilized,dewormed,intake_date,photo_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (r.get('name_at_intake') or r['animal_id'],species,r.get('primary_breed') or '',months,sex,health,'unknown',sterilized,'unknown',intake,None))
    print(f'已備份 {backup}；已匯入 162 筆，請重新啟動後端')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    rows=download()
    if args.apply:apply(rows)
    else:print('尚未更動資料庫。檢查 CSV 後加 --apply 才會覆蓋原動物清單。')
