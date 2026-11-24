"""Optional cleanup of legacy long-stay task records. Dry run unless --apply.
Backs up DB before destructive changes; never deletes animal records.
"""
import argparse,sqlite3,shutil
from pathlib import Path
DB=Path(__file__).resolve().parent/'showcase.sqlite3'
LABELS=('未來長期滯留風險','長期在所動物關懷','長期留所追蹤')
def main():
 p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--db',type=Path,default=DB);args=p.parse_args()
 with sqlite3.connect(args.db) as c:
  for table in ('assignment_snapshot','generated_tasks','task_overrides','task_report_history','task_animal_baseline'):
   exists=c.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone()
   if not exists:continue
   count=c.execute(f'SELECT COUNT(*) FROM {table} WHERE label IN (?,?,?)',LABELS).fetchone()[0]
   print(f'{table}: {count} legacy records')
  if not args.apply:
   print('Dry run; no changes. Pass --apply to remove only legacy long-stay task records.')
   return
  backup=args.db.with_name(args.db.stem+'.before_longstay_cleanup'+args.db.suffix)
  if backup.exists():raise SystemExit(f'Backup already exists: {backup}; refusing overwrite')
  shutil.copy2(args.db,backup)
  for table in ('assignment_snapshot','generated_tasks','task_overrides','task_report_history','task_animal_baseline'):
   if c.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone():
    c.execute(f'DELETE FROM {table} WHERE label IN (?,?,?)',LABELS)
  c.commit();print(f'Cleaned legacy tasks; backup: {backup}')
if __name__=='__main__':main()
