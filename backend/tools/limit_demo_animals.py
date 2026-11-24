"""Opt-in demo active roster cap; archives by flag, never deletes animals or tasks.
Run from project root: python backend/tools/limit_demo_animals.py --apply
"""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime
DB=Path(__file__).resolve().parents[1]/'showcase.sqlite3'
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--apply',action='store_true',help='Explicitly archive excess demo animals')
 parser.add_argument('--limit',type=int,default=82)
 args=parser.parse_args()
 if args.limit<1:parser.error('limit must be positive')
 if not DB.exists():raise SystemExit(f'No database: {DB}. Start server once to initialize schema.')
 with closing(sqlite3.connect(DB)) as c, c:
  cols={row[1] for row in c.execute('PRAGMA table_info(animals)')}
  if 'is_active' not in cols:raise SystemExit('is_active missing; start updated backend to run migration first')
  active=c.execute('SELECT id,name,health_status FROM animals WHERE is_active=1 ORDER BY id').fetchall()
  n=max(0,len(active)-args.limit)
  # prioritize archiving health review cases, retain healthy cases and their original IDs
  ordered=sorted(active,key=lambda a:(0 if a[2] in ('needs_review','unknown','serious') else 1,-a[0]))
  ids=[a[0] for a in ordered[:n]]
  print(f'Current active: {len(active)}; limit: {args.limit}; would archive: {len(ids)}')
  if not args.apply:
   print('DRY RUN. No changes made. Re-run with --apply to archive demo roster records.')
   return
  if not ids:return
  backup=DB.with_name(DB.name+'.before_archive_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.bak')
  with closing(sqlite3.connect(backup)) as b, b:c.backup(b)
  c.executemany('UPDATE animals SET is_active=0 WHERE id=?',[(x,) for x in ids])
  print(f'Archived (not deleted) {len(ids)} records; backup at: {backup}')
if __name__=='__main__':main()
