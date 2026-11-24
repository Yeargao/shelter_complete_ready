"""Explicit, backed-up task-only demo reset. Never runs on page refresh/import.

PowerShell (from project root):
    python backend/tools/reset_showcase_tasks.py
    python backend/tools/reset_showcase_tasks.py --apply --confirm RESET_TASKS
"""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
import sqlite3

DEFAULT_DB = Path(__file__).resolve().parents[1] / 'showcase.sqlite3'
RESET_TABLES = (
    'assignment_snapshot', 'generated_tasks', 'task_metadata',
    'task_report_history', 'task_overrides', 'task_animal_baseline',
)


def reset_demo_tasks(db: Path, apply: bool = False, confirm: str = '') -> dict:
    db = Path(db).resolve()
    if not db.is_file():
        raise FileNotFoundError(f'找不到 SQLite：{db}')
    if apply and confirm != 'RESET_TASKS':
        raise ValueError('要執行重設必須同時指定 --apply --confirm RESET_TASKS')
    connection = sqlite3.connect(db, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        existing = {r['name'] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = set(RESET_TABLES) - existing
        if missing or 'animals' not in existing or 'staff' not in existing:
            raise ValueError(f'資料庫結構不符；缺少資料表：{sorted(missing)}')
        before = {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in RESET_TABLES}
        before.update(animals=connection.execute('SELECT COUNT(*) FROM animals').fetchone()[0],
                      staff=connection.execute('SELECT COUNT(*) FROM staff').fetchone()[0])
        if not apply:
            return {'mode': 'dry_run', 'counts_before': before,
                    'message': '僅預覽，沒有修改 SQLite；加上 --apply --confirm RESET_TASKS 才會重設'}
        # A unique backup is made by the SQLite backup API *before* destructive changes.
        backup_dir = db.parent / 'reset_backups'
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup = backup_dir / f'{db.stem}_before_task_reset_{stamp}.sqlite3'
        with sqlite3.connect(backup) as saved:
            connection.backup(saved)
        try:
            connection.execute('BEGIN IMMEDIATE')
            # Undo only animal status fields changed by past task reports; do not
            # erase intake dates, species, resource rates or independent medical events.
            restored = 0
            for baseline in connection.execute('SELECT animal_id,label,column_name,old_value FROM task_animal_baseline'):
                column = baseline['column_name']
                if column not in ('health_status','vaccinated','sterilized','dewormed'):
                    raise ValueError(f'未知的醫療回報欄位：{column}')
                report = connection.execute('SELECT result FROM task_overrides WHERE animal_id=? AND label=?',
                                            (baseline['animal_id'], baseline['label'])).fetchone()
                animal = connection.execute(f'SELECT {column} FROM animals WHERE id=?',
                                            (baseline['animal_id'],)).fetchone()
                if report and animal and animal[column] == report['result']:
                    connection.execute(f'UPDATE animals SET {column}=? WHERE id=?',
                                       (baseline['old_value'], baseline['animal_id']))
                    restored += 1
            for table in RESET_TABLES:
                connection.execute(f'DELETE FROM {table}')
            connection.execute('CREATE TABLE IF NOT EXISTS demo_ui_state (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            connection.execute("INSERT INTO demo_ui_state(key,value) VALUES ('reset_mode','1') ON CONFLICT(key) DO UPDATE SET value='1'")
            problems = connection.execute('PRAGMA foreign_key_check').fetchall()
            if problems:
                raise ValueError(f'外鍵檢查失敗，共 {len(problems)} 筆；已取消資料修改')
            after_animals = connection.execute('SELECT COUNT(*) FROM animals').fetchone()[0]
            after_staff = connection.execute('SELECT COUNT(*) FROM staff').fetchone()[0]
            if after_animals != before['animals'] or after_staff != before['staff']:
                raise RuntimeError('動物／員工數量意外變更，取消重設')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return {'mode': 'reset_applied', 'counts_before': before, 'backup': str(backup),
                'restored_animal_status_fields': restored, 'animals_unchanged': after_animals,
                'staff_unchanged': after_staff,
                'message': '展示派工、任務狀態、回報紀錄已重設。重整一次會由 SQLite 重載；必須手動執行最佳化才會重新派工'}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description='只重設展示任務狀態（預設 dry-run）')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB, help='SQLite 位置（測試／自訂用）')
    parser.add_argument('--apply', action='store_true', help='真正寫入重設')
    parser.add_argument('--confirm', default='', help='輸入 RESET_TASKS 二次確認')
    args = parser.parse_args()
    import json
    print(json.dumps(reset_demo_tasks(args.db, args.apply, args.confirm), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
