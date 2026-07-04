import sqlite3
import os

path = os.path.join(os.path.dirname(__file__), '..', 'data', 'tarikgaji-live.db')
print('DB:', path)
conn = sqlite3.connect(path)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
print('tables=', cur.fetchall())
for tbl in ['admins','pegawai','user_accounts','transactions','app_settings','users']:
    print('\nTABLE', tbl)
    try:
        cur.execute("PRAGMA table_info('%s')" % tbl)
        print('schema=')
        for row in cur.fetchall():
            print(row)
    except Exception as e:
        print('schema error', e)
    try:
        cur.execute("SELECT * FROM %s LIMIT 3" % tbl)
        print('rows=')
        for row in cur.fetchall():
            print(row)
    except Exception as e:
        print('sample error', e)
conn.close()
