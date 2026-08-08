import sqlite3
import os

db_path = 'newsroom.db'
if not os.path.exists(db_path):
    print("Database not found:", db_path)
else:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT title, available_from, status FROM events WHERE source='playstation_plus'")
    rows = c.fetchall()
    print("Total PS Plus rows:", len(rows))
    for row in rows:
        print(row)
