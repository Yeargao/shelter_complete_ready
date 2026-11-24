"""Read-only preview of ambiguous historical injury-treatment task episodes.

Run from the project root:
  python backend/tools/audit_injury_task_duplicates.py
The tool NEVER deletes, updates or backs up the database (no writes occur).
"""
import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DEFAULT_DB=Path(__file__).resolve().parents[1]/'showcase.sqlite3'

def inspect(db:Path):
    # Opening explicitly read-only also prevents accidentally creating a new SQLite file.
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        groups=defaultdict(list)
        for r in conn.execute("SELECT task_id,animal_id,label,date,staff_id,locked FROM assignment_snapshot WHERE label='優先確認健康狀況' ORDER BY animal_id,date,task_id"):
            groups[r['animal_id']].append(dict(r))
        new_counts=defaultdict(list)
        for r in conn.execute("SELECT task_id,animal_id,created_at FROM generated_tasks WHERE label='優先確認健康狀況' ORDER BY animal_id,created_at"):
            new_counts[r['animal_id']].append(dict(r))
        result=[]
        for animal_id in sorted(set(groups)|set(new_counts)):
            assigned=groups[animal_id];created=new_counts[animal_id]
            if len(assigned)<=1 and len(created)<=1:continue
            result.append({'animal_id':animal_id,'snapshot_rows':assigned,'generated_rows':created,'classification':'待確認：無健康事件 ID，不能依任務名稱或日期直接判定重複；未刪除'})
        return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='唯讀檢查傷病治療歷史任務的跨日期重複候選')
    parser.add_argument('--db',type=Path,default=DEFAULT_DB)
    args=parser.parse_args()
    print(json.dumps({'database':str(args.db),'ambiguous_animals':inspect(args.db)},ensure_ascii=False,indent=2))
