"""Estimate individual daily food and routine-care needs for existing demo animals.
Preview by default. Use --apply to update only two resource columns in showcase.sqlite3.
Values are demonstration assumptions, NOT Austin observations or feeding advice.
"""
import argparse, csv, sqlite3, shutil
from pathlib import Path
from datetime import datetime

HERE=Path(__file__).resolve().parent
DB=HERE/'showcase.sqlite3'
CSV=HERE/'austin_intakes_2026-10-23_162.csv'

def estimate(species, breed, age_months, health, stay_days=4):
    s=(species or '').lower(); b=(breed or '').lower(); age=age_months or 24
    if s in ('cat','kitten'):
        food=85 if age<12 else 65
        care=.25
    elif s in ('dog','puppy'):
        size='large' if any(x in b for x in ('husky','retriever','shepherd','great dane','rottweiler','mastiff','labrador')) else 'small' if any(x in b for x in ('chihuahua','pomeranian','terrier','shih','poodle')) else 'medium'
        food={'small':120,'medium':250,'large':420}[size]
        care=.5
    else:
        food=100;care=.5
    if age<12:food*=1.2;care+=.25
    elif age>=96:food*=.95;care+=.25
    if (health or '').lower() in ('sick','injured','serious'):care+=.5
    if stay_days<=3:care+=.25
    return round(food,1),round(care,2)

def main():
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--db',type=Path,default=DB);p.add_argument('--csv',type=Path,default=CSV);p.add_argument('--out',type=Path,default=HERE/'animal_needs_preview.csv');args=p.parse_args()
    with args.csv.open(encoding='utf-8-sig',newline='') as f:source=list(csv.DictReader(f))
    if len(source)!=162:raise SystemExit(f'Expected 162 Austin rows, got {len(source)}')
    with sqlite3.connect(args.db) as db:
        db.row_factory=sqlite3.Row
        animals=[dict(r) for r in db.execute('SELECT * FROM animals ORDER BY id')]
        if len(animals)!=162:raise SystemExit(f'Expected 162 animals in showcase DB, got {len(animals)}. No changes made.')
        cols={r[1] for r in db.execute('PRAGMA table_info(animals)')}
        records=[]
        for i,a in enumerate(animals):
            # Source file provides context for 162-animal demo; DB animals may be synthetic
            # and have no reliable Austin animal-ID correspondence. Never claim a match.
            try:stay=(datetime.now().date()-datetime.fromisoformat(a['intake_date']).date()).days
            except (ValueError,TypeError):stay=4
            food,care=estimate(a['species'],a['breed'],a['age_months'],a['health_status'],max(0,stay))
            records.append({'id':a['id'],'name':a['name'],'species':a['species'],'breed':a['breed'],'age_months':a['age_months'],'health_status':a['health_status'],'food_grams_per_day':food,'routine_care_hours_per_day':care,'source':'rule_based_demo_not_measured'})
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with args.out.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
        if args.apply:
            backup=args.db.with_name(args.db.stem+'.before_needs'+args.db.suffix)
            if not backup.exists():shutil.copy2(args.db,backup)
            for col in ('food_grams_per_day','routine_care_hours_per_day'):
                if col not in cols:db.execute(f'ALTER TABLE animals ADD COLUMN {col} REAL')
            db.executemany('UPDATE animals SET food_grams_per_day=?,routine_care_hours_per_day=? WHERE id=?',[(r['food_grams_per_day'],r['routine_care_hours_per_day'],r['id']) for r in records]);db.commit()
            print(f'Updated {len(records)} animals. Backup: {backup}')
        else:print(f'Preview only; no database changes. Use --apply after review.')
        print(f'CSV: {args.out}; daily food={sum(r["food_grams_per_day"] for r in records)/1000:.2f} kg; daily routine care={sum(r["routine_care_hours_per_day"] for r in records):.2f} h')
if __name__=='__main__':main()
