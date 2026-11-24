"""Idempotent, additive SQLite migration. Run against backend/showcase.sqlite3.
Never drops historical work, reports or animals. Makes an online backup first.
"""
from pathlib import Path
import sqlite3
from contextlib import closing

DB = Path(__file__).resolve().parents[1] / 'showcase.sqlite3'

def migrate(db=DB):
    db=Path(db)
    if not db.is_file():
        raise SystemExit(f'資料庫不存在，請先檢查路徑：{db}（不會自動生成示範資料）')
    backup=db.with_name(db.name+'.pre_schedule.bak')
    with closing(sqlite3.connect(db)) as conn, conn:
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as dest, dest: conn.backup(dest)
        conn.execute("CREATE TABLE IF NOT EXISTS vaccination_records (id INTEGER PRIMARY KEY, animal_id INTEGER NOT NULL, vaccine_type TEXT NOT NULL DEFAULT 'general', administered_date TEXT NOT NULL, next_due_date TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'staff_report', UNIQUE(animal_id,vaccine_type,administered_date))")
        vaccine_cols={r[1] for r in conn.execute('PRAGMA table_info(vaccination_records)')}
        if 'animal_id' not in vaccine_cols:
            raise RuntimeError('vaccination_records 缺少 animal_id；請使用備份檢查舊資料庫')
        # Additive legacy-schema upgrade; unknown dates stay NULL (do not guess).
        for column,kind in [('vaccine_type',"TEXT NOT NULL DEFAULT 'general'"),
                            ('administered_date','TEXT'),('next_due_date','TEXT'),
                            ('source',"TEXT NOT NULL DEFAULT 'legacy'")]:
            if column not in vaccine_cols:
                conn.execute(f'ALTER TABLE vaccination_records ADD COLUMN {column} {kind}')
        conn.execute("CREATE TABLE IF NOT EXISTS deworming_events (animal_id INTEGER NOT NULL, intake_date TEXT NOT NULL, completed_date TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'staff_report', PRIMARY KEY(animal_id,intake_date))")
        conn.execute("CREATE TABLE IF NOT EXISTS task_metadata (task_id TEXT PRIMARY KEY, source TEXT NOT NULL DEFAULT 'rule', is_new INTEGER NOT NULL DEFAULT 0, due_date TEXT, vaccine_type TEXT DEFAULT 'general')")
        staff_cols={r[1] for r in conn.execute('PRAGMA table_info(staff)')}
        for col,kind in [('shift_start',"TEXT NOT NULL DEFAULT '09:00'"),('shift_end',"TEXT NOT NULL DEFAULT '17:00'"),('break_start','TEXT'),('break_end','TEXT')]:
            if staff_cols and col not in staff_cols:conn.execute(f'ALTER TABLE staff ADD COLUMN {col} {kind}')
        columns={r[1] for r in conn.execute('PRAGMA table_info(assignment_snapshot)')}
        if not columns:
            raise RuntimeError('找不到 assignment_snapshot；確認此 SQLite 屬於原專案')
        for column,kind in [('start_time','TEXT'),('end_time','TEXT'),('locked','INTEGER NOT NULL DEFAULT 0')]:
            if column not in columns:conn.execute(f'ALTER TABLE assignment_snapshot ADD COLUMN {column} {kind}')
    print(f'完成：{db}；原始備份：{backup}')

if __name__=='__main__':migrate()
