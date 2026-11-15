import sqlite3

conn = sqlite3.connect('kb_review/books/data_structure/kb.sqlite')
tables = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
for t, sql in tables:
    print('TABLE:', t)
    print(sql)
    print('-'*50)
