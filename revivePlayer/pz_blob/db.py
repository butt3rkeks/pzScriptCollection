"""SQLite database helpers for the networkPlayers table."""

import sys
from pathlib import Path


def load_player_from_db(db_path: str, identifier: str, player_index: int):
    """Load player row from SQLite. Returns (conn, row) or exits."""
    import sqlite3

    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, x, y, z, data, worldversion, isDead, name FROM networkPlayers "
        "WHERE (username=? OR steamid=?) AND playerIndex=?",
        (identifier, identifier, player_index)
    )
    row = cursor.fetchone()

    if not row:
        print(f"ERROR: No player found for identifier '{identifier}' with playerIndex={player_index}")
        cursor.execute("SELECT username, steamid, name, isDead, playerIndex FROM networkPlayers")
        rows = cursor.fetchall()
        if rows:
            print("\nAvailable players:")
            for r in rows:
                print(f"  username={r[0]}, steamid={r[1]}, name={r[2]}, isDead={r[3]}, index={r[4]}")
        conn.close()
        sys.exit(1)

    return conn, row
