import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "app.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id_id
ON chat_messages (session_id, id);
""")

conn.commit()
conn.close()

print("✅ Index created successfully")
