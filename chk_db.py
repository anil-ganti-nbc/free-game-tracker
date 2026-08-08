import sqlite3
conn = sqlite3.connect('newsroom.db')
c = conn.cursor()
c.execute("SELECT title, available_from, status FROM event WHERE source='playstation_plus'")
rows = c.fetchall()
print(len(rows))
for r in rows:
    print(r)
