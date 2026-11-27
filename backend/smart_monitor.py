"""Run a reminder/workflow scan from cron or Windows Task Scheduler.
Use the same SHELTER_DB_PATH and auth configuration as the API process.
"""
from main import connect, lock
from smart_tools import scan

if __name__ == '__main__':
    with lock, connect() as db:
        db.execute('BEGIN IMMEDIATE')
        inbox=scan(db)
    print(f'Pending notifications: {len(inbox)}')
