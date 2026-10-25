import os
 
try:
    from dotenv import load_dotenv
 
    load_dotenv()
except ImportError:
    pass
 
from database import get_connection, init_db
 
print("DATABASE_URL set:", bool(os.environ.get("DATABASE_URL")))
 
init_db()
print("init_db OK (tables created or already exist)")
 
with get_connection() as db:
    version = db.execute("SELECT version() AS v").fetchone()["v"]
    print("Connected to:", version[:40])
 
    tables = db.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    ).fetchall()
    print("Tables:", [t["table_name"] for t in tables])
 
    users = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    print("Users in database:", users)
 
print("All good.")
 