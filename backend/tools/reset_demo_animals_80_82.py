"""Safely reset selected *demo* data, never automatically at backend startup.

From the project root (default is preview / no database changes):
    python backend/tools/reset_demo_animals_80_82.py --scope a  # task completion reports
    python backend/tools/reset_demo_animals_80_82.py --scope b  # intake/exit state: 80/82
    python backend/tools/reset_demo_animals_80_82.py --scope c  # both in ONE transaction

To apply, add --apply and the scope-specific confirmation string printed in preview.
Legacy calls without --scope use b and accept --confirm-demo RESET-DEMO-80-82.

Task-only scope resets completed task states and their report fields, but preserves
existing assignments, new/pending tasks, audit history, and real medical events.
Animal-only scope resets the original 162 demo animal status flags, NOT real
intake/exit history; it refuses databases with actual stay events or unknown IDs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / 'showcase.sqlite3'
MANIFEST = HERE / 'demo_animals_baseline_manifest.json'
SCOPES = {'a': '任務完成狀態', 'b': '出入所狀態', 'c': '全部'}
CONFIRM = {'a': 'RESET-TASK-STATUS', 'b': 'RESET-DEMO-80-82', 'c': 'RESET-DEMO-ALL'}
REPORT_COLUMNS = ('health_status', 'vaccinated', 'sterilized', 'dewormed')


def digest(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=False, separators=(',', ':')).encode()).hexdigest()


def _get_schema(c):
    return {r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _check_demo_animals(c, baseline):
    """For *every* scope, refuse extra/missing animal IDs (possible real data)."""
    originals = {int(a['id']): a for a in baseline['animals']}
    if 'animals' not in _get_schema(c):
        raise ValueError('缺少 animals 資料表')
    cols = {r['name'] for r in c.execute('PRAGMA table_info(animals)')}
    required = set(baseline['fields']) | {'id', 'is_active'}
    if not required.issubset(cols):
        raise ValueError(f'動物表欄位不足：{sorted(required-cols)}')
    rows = {r['id']: r for r in c.execute('SELECT * FROM animals')}
    if set(rows) != set(originals):
        missing = sorted(set(originals)-set(rows))
        extra = sorted(set(rows)-set(originals))
        raise ValueError(f'動物 ID 衝突；缺少 {missing[:10]}；額外/可能真實資料 {extra[:10]}。不會覆蓋。')
    return originals, rows, cols


def _task_plan(c, exists, rows):
    required = {'task_overrides', 'task_animal_baseline'}
    if not required.issubset(exists):
        raise ValueError(f'缺少任務資料表：{sorted(required-exists)}')
    done = c.execute("SELECT animal_id,label,result FROM task_overrides WHERE state='done'").fetchall()
    done_keys = {(r['animal_id'], r['label']) for r in done}
    reports = {(r['animal_id'], r['label']): r for r in done}
    changes = {}
    skipped = []
    for r in c.execute('SELECT animal_id,label,column_name,old_value FROM task_animal_baseline'):
        key = (r['animal_id'], r['label'])
        if key not in done_keys:
            continue
        column = r['column_name']
        if column not in REPORT_COLUMNS:
            raise ValueError(f'未知的任務回報欄位：{column}')
        if r['animal_id'] not in rows:
            raise ValueError(f'任務與動物 ID 不一致：{r["animal_id"]}')
        current = rows[r['animal_id']][column]
        # Completion flags may be reset for a demo; a genuine medical act may not.
        # Never revert a clinical status backed by an independent event record.
        if column == 'vaccinated' and 'vaccination_records' in exists and c.execute(
                'SELECT 1 FROM vaccination_records WHERE animal_id=? LIMIT 1',
                (r['animal_id'],)).fetchone():
            skipped.append((r['animal_id'], column))
            continue
        if column == 'dewormed' and 'deworming_events' in exists and c.execute(
                'SELECT 1 FROM deworming_events WHERE animal_id=? LIMIT 1',
                (r['animal_id'],)).fetchone():
            skipped.append((r['animal_id'], column))
            continue
        if current == reports[key]['result']:
            previous = changes.get((r['animal_id'], column))
            if previous is not None and previous != r['old_value']:
                raise ValueError(f'同一動物欄位有不相容的任務還原值：{r["animal_id"]} {column}')
            changes[(r['animal_id'], column)] = r['old_value']
        else:
            # Do not overwrite a value edited after the task report.
            skipped.append((r['animal_id'], column))
    return done, changes, skipped


def _orphaned_report_followups(c, exists):
    """Find unassigned follow-ups created *only* by staff reports.

    A task reset invalidates the report which spawned them. Do not touch manual
    assignments, rule-based tasks, medical events or audit history.
    """
    if not {'generated_tasks', 'task_metadata', 'assignment_snapshot'}.issubset(exists):
        return []
    return [dict(r) for r in c.execute('''SELECT g.task_id,g.animal_id,g.label
        FROM generated_tasks g
        JOIN task_metadata m ON m.task_id=g.task_id
        LEFT JOIN assignment_snapshot s ON s.task_id=g.task_id
        WHERE m.source='employee_report' AND m.is_new=1
          AND (s.task_id IS NULL OR s.staff_id IS NULL)
        ORDER BY g.task_id''')]


def _animal_plan(c, baseline, originals, rows, cols, exists, projected_changes):
    """Validate old demo baseline, including fields task reset would restore in scope c."""
    changed = []
    for aid, r in rows.items():
        fields = [projected_changes.get((aid, field), r[field]) for field in baseline['fields']]
        if digest(fields) != originals[aid]['sha256']:
            changed.append(aid)
    if changed:
        raise ValueError(f'動物主資料已修改，可能含真實資料：{changed[:20]}。拒絕覆蓋。')
    exit_columns = cols & {'exit_date', 'exit_reason', 'exit_notes'}
    if exit_columns:
        confirmed = [aid for aid, r in rows.items()
                     if any(r[field] is not None for field in exit_columns)]
        if confirmed:
            raise ValueError(f'已存在實際離所資料（動物 {confirmed[:20]}），拒絕覆蓋歷史')
    if 'animal_stays' in exists:
        strange = [dict(r) for r in c.execute('''SELECT animal_id,COUNT(*) AS cnt FROM animal_stays
            GROUP BY animal_id HAVING COUNT(*)!=1''')]
        if strange:
            raise ValueError(f'已存在多段入所歷史或缺失的 stay：{strange[:10]}。拒絕重置')
        stays = c.execute('SELECT animal_id,source,exit_date,exit_reason,exit_notes FROM animal_stays').fetchall()
        if (len(stays) != len(originals) or
                {r['animal_id'] for r in stays} != set(originals) or
                any(r['source'] != 'legacy_import' or
                    any(r[key] is not None for key in ('exit_date','exit_reason','exit_notes'))
                    for r in stays)):
            raise ValueError('存在實際入離所歷史或不完整的示範 stay，拒絕重置')
    if 'animal_stay_audit' in exists and c.execute('SELECT COUNT(*) FROM animal_stay_audit').fetchone()[0]:
        raise ValueError('存在入離所歷史人工修正紀錄，拒絕重置')
    return [(int(originals[aid]['is_active']), aid) for aid, r in rows.items()
            if int(r['is_active']) != int(originals[aid]['is_active'])]


def reset(db: Path, apply: bool=False, confirm: str='', scope: str='b'):
    if scope not in SCOPES:
        raise ValueError('重置範圍必須是 a（任務完成狀態）、b（出入所狀態）或 c（全部）')
    db = Path(db).resolve()
    if db.name != 'showcase.sqlite3' or not db.is_file():
        raise ValueError('只允許存在的 showcase.sqlite3 示範資料庫')
    if apply and confirm != CONFIRM[scope]:
        raise ValueError(f'請提供 --apply --confirm-demo {CONFIRM[scope]}')
    baseline = json.loads(MANIFEST.read_text(encoding='utf-8'))
    with sqlite3.connect(db, timeout=30) as c:
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        exists = _get_schema(c)
        originals, rows, cols = _check_demo_animals(c, baseline)
        done, restorations, skipped = ([], {}, [])
        report_followups = []
        if scope in ('a', 'c'):
            done, restorations, skipped = _task_plan(c, exists, rows)
            report_followups = _orphaned_report_followups(c, exists)
        to_update = []
        if scope in ('b', 'c'):
            to_update = _animal_plan(c, baseline, originals, rows, cols, exists,
                                     restorations if scope == 'c' else {})
        print(f'選擇 {scope}：{SCOPES[scope]}。原始基準 80 在所／82 非在所，共 162 隻。')
        print('目前：在所', sum(r['is_active'] for r in rows.values()),
              '非在所', len(rows)-sum(r['is_active'] for r in rows.values()))
        if scope in ('a', 'c'):
            print(f'將重設完成回報：{len(done)} 筆；恢復由回報改動的動物欄位：{len(restorations)} 項；移除未指派的回報衍生新增任務：{len(report_followups)} 筆。')
            if skipped:
                print(f'略過已被另行修改的欄位：{skipped[:10]}；不會強制覆蓋。')
            print('保留既有員工指派、一般待辦與移除狀態、歷史稽核、實際疫苗/驅蟲事件。')
        if scope in ('b', 'c'):
            print('需要恢復 is_active 狀態：', len(to_update), '隻')
            print('只恢復原始出入所狀態；不捏造任何離所日期、原因或送養事件。')
        if not apply:
            print(f'僅預覽，未修改資料庫。使用 --scope {scope} --apply --confirm-demo {CONFIRM[scope]} 執行。')
            return {'mode': 'preview', 'scope': scope, 'completed': len(done),
                    'new_followups_removed': len(report_followups),
                    'animal_status_changes': len(to_update)}
        backup_dir = db.parent / 'reset_backups'
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / (db.stem + '.before_selective_reset_' + scope + '_' +
                               datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3')
        with sqlite3.connect(backup) as dest:
            c.backup(dest)
        print('完整 SQLite 備份：', backup)
        # Both scopes are committed together or rolled back together.
        try:
            c.execute('BEGIN IMMEDIATE')
            # Revalidate at write time, after obtaining the SQLite writer lock.
            originals, rows, cols = _check_demo_animals(c, baseline)
            fresh_done, fresh_restore, fresh_skipped = ([], {}, [])
            if scope in ('a', 'c'):
                fresh_done, fresh_restore, fresh_skipped = _task_plan(c, exists, rows)
                fresh_followups = _orphaned_report_followups(c, exists)
                if (fresh_followups != report_followups or
                        {(r['animal_id'], r['label']) for r in fresh_done} !=
                        {(r['animal_id'], r['label']) for r in done} or
                        fresh_restore != restorations):
                    raise ValueError('預覽後任務資料有變動，停止並保留備份')
            if scope in ('b', 'c'):
                fresh_update = _animal_plan(c, baseline, originals, rows, cols, exists,
                                            fresh_restore if scope == 'c' else {})
                if fresh_update != to_update:
                    raise ValueError('預覽後動物資料有變動，停止並保留備份')
            if scope in ('a', 'c'):
                for (aid, column), old_value in restorations.items():
                    c.execute(f'UPDATE animals SET {column}=? WHERE id=?',(old_value, aid))
                # Only completed tasks lose completion/report values. Never delete
                # assignments, pending/removed tasks, actual medical events or logs.
                c.execute("""DELETE FROM task_animal_baseline WHERE EXISTS (
                    SELECT 1 FROM task_overrides o
                    WHERE o.animal_id=task_animal_baseline.animal_id
                      AND o.label=task_animal_baseline.label AND o.state='done')""")
                c.execute("""UPDATE task_overrides SET state='pending',result=NULL,
                    resolved=NULL,note=NULL,updated_at=NULL WHERE state='done'""")
                # After the source report is reset, its unassigned follow-up is
                # no longer a valid "new task". An assigned task is preserved.
                for followup in report_followups:
                    task_id, aid, label = (followup['task_id'],
                                           followup['animal_id'], followup['label'])
                    c.execute('DELETE FROM assignment_snapshot WHERE task_id=? AND staff_id IS NULL', (task_id,))
                    c.execute('DELETE FROM generated_tasks WHERE task_id=?', (task_id,))
                    c.execute('DELETE FROM task_metadata WHERE task_id=?', (task_id,))
                    # Keep records of real work (report audit and medical events).
                    # Only remove pending override left by the discarded follow-up.
                    c.execute("DELETE FROM task_overrides WHERE animal_id=? AND label=? AND state='pending'", (aid, label))
            if scope in ('b', 'c'):
                c.executemany('UPDATE animals SET is_active=? WHERE id=?', to_update)
                if 'animal_stays' in exists:
                    c.execute('''UPDATE animal_stays SET is_open=(
                        SELECT a.is_active FROM animals a WHERE a.id=animal_stays.animal_id)
                        WHERE source='legacy_import' ''')
                totals = c.execute('SELECT COUNT(*),SUM(is_active) FROM animals').fetchone()
                if (totals[0], totals[1]) != (162, 80):
                    raise ValueError('80／82／162 核對失敗，重置已回滾')
            problems = c.execute('PRAGMA foreign_key_check').fetchall()
            if problems:
                raise ValueError(f'外鍵檢查失敗，共 {len(problems)} 筆；重置已回滾')
            c.commit()
        except Exception:
            c.rollback()
            raise
        print(f'重置完成（{scope}：{SCOPES[scope]}），未重置其他模組程式與資料。')
        return {'mode': 'applied', 'scope': scope, 'backup': str(backup),
                'completed_reset': len(done), 'new_followups_removed': len(report_followups),
                'animal_status_reset': len(to_update)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--scope', choices=tuple(SCOPES), default=None,
                        help='a 任務完成狀態；b 出入所狀態；c 全部（不指定時提供選單）')
    parser.add_argument('--apply', action='store_true', help='真正套用；預設僅預覽')
    parser.add_argument('--confirm-demo', default='', help='依 scope 對應的確認字串')
    args = parser.parse_args()
    chosen = args.scope
    if chosen is None:
        if sys.stdin.isatty():
            print('請選擇重置範圍：a 任務完成狀態／b 出入所狀態／c 全部')
            chosen = input('請輸入 a、b 或 c（Enter 預設 b）：').strip().lower() or 'b'
        else:
            chosen = 'b'  # Preserve the prior non-interactive default.
    try:
        reset(args.db, args.apply, args.confirm_demo, chosen)
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise SystemExit('安全停止：'+str(exc))


if __name__ == '__main__':
    main()
