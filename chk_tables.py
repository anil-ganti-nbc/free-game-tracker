import sqlite3
conn = sqlite3.connect('newsroom.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table';")
print(c.fetchall())
c.execute("SELECT title, available_from, status FROM newsevent WHERE source='playstation_plus'")
rows = c.fetchall()
print(f"Total rows: {len(rows)}")
for r in rows: print(r)
