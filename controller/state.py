import sqlite3

class StateStore:
    def __init__(self, path="autoscaler.db"):
        self.conn = sqlite3.connect(path)
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS apps (
            name TEXT PRIMARY KEY,
            type TEXT,
            image TEXT,
            ports TEXT,
            scaling TEXT
        )""")
        self.conn.commit()

    def save_app(self, name, spec):
        cur = self.conn.cursor()
        cur.execute("INSERT OR REPLACE INTO apps VALUES (?, ?, ?, ?, ?)", 
                    (name, spec["type"], spec["image"], str(spec["ports"]), str(spec["scaling"])))
        self.conn.commit()

    def get_app(self, name):
        cur = self.conn.cursor()
        row = cur.execute("SELECT * FROM apps WHERE name=?", (name,)).fetchone()
        return row

