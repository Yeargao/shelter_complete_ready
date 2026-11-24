"""Safe, opt-in demo roster adjuster; preserves animal history and existing IDs.

Usage:
    python backend/tools/set_demo_roster_82.py          # preview only
    python backend/tools/set_demo_roster_82.py --apply  # change active demo roster

No existing records are deleted. If fewer than 82 are active, previously
archived animals are reactivated first, then demo placeholders are added.
Do NOT run against production data; it is for the sample database only.
"""
import argparse
import sqlite3
from datetime import date, datetime
from pathlib import Path

DB=Path(__file__).resolve().parents[1]/'showcase.sqlite3'
TARGET=82

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--apply',action='store_true')
 parser.add_argument('--db',type=Path,default=DB)
 args=parser.parse_args()
 if not args.db.exists():raise SystemExit(f'資料庫不存在：{args.db}')
 with sqlite3.connect(args.db) as c:
  cols={r[1] for r in c.execute('PRAGMA table_info(animals)')}
  if 'is_active' not in cols:raise SystemExit('缺少 is_active，請先啟動新版本後端完成結構遷移')
  active=c.execute('SELECT id,health_status FROM animals WHERE is_active=1').fetchall()
  n=len(active)
  print(f'目前在養 {n} 隻，目標 {TARGET} 隻')
  if n>TARGET:
   ordered=sorted(active,key=lambda a:(0 if a[1] in ('needs_review','unknown','serious') else 1,-a[0]))
   archive=[r[0] for r in ordered[:n-TARGET]]
   restore=[];create=0
  else:
   archive=[]
   restore=[r[0] for r in c.execute('SELECT id FROM animals WHERE is_active=0 ORDER BY id DESC LIMIT ?', (TARGET-n,))]
   create=TARGET-n-len(restore)
  print(f'預計封存 {len(archive)}、重新啟用 {len(restore)}、新增示範紀錄 {create}')
  if not args.apply:
   print('僅預覽，未修改。確定是示範資料庫後加 --apply 執行。')
   return
  if not (archive or restore or create):return
  backup=args.db.with_name(args.db.name+'.before_roster82_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.bak')
  with sqlite3.connect(backup) as dest:c.backup(dest)
  with c:
   c.executemany('UPDATE animals SET is_active=0 WHERE id=?',[(x,) for x in archive])
   c.executemany('UPDATE animals SET is_active=1 WHERE id=?',[(x,) for x in restore])
   for i in range(create):
    c.execute('INSERT INTO animals(name,species,breed,age_months,sex,health_status,vaccinated,sterilized,dewormed,intake_date,is_active) VALUES (?,?,?,?,?,?,?,?,?,?,1)',
              (f'示範動物-{date.today():%Y%m%d}-{i+1:03}', 'cat' if i%2 else 'dog','米克斯',24,'female' if i%2 else 'male','healthy','unknown','unknown','unknown',date.today().isoformat()))
  final=c.execute('SELECT COUNT(*) FROM animals WHERE is_active=1').fetchone()[0]
  print(f'完成：{final} 隻。原始資料備份：{backup}')

if __name__=='__main__':main()
