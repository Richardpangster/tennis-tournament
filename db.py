import sqlite3
import os

DB_PATH = os.getenv("DATABASE_PATH") or os.path.join(os.path.dirname(__file__), 'tournament.db')

# Ensure parent directory exists (for Railway volume mounts)
os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('U8','U10','U12','U14')),
            birth_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            stage TEXT NOT NULL,
            group_name TEXT,
            round INTEGER,
            match_order INTEGER,
            player1_id INTEGER,
            player2_id INTEGER,
            score1 INTEGER,
            score2 INTEGER,
            tb_score1 INTEGER,
            tb_score2 INTEGER,
            winner_id INTEGER,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (player1_id) REFERENCES players(id),
            FOREIGN KEY (player2_id) REFERENCES players(id)
        );
    """
    )
    # Migration: add tb columns if they don't exist
    try:
        conn.execute("ALTER TABLE matches ADD COLUMN tb_score1 INTEGER")
    except:
        pass
    try:
        conn.execute("ALTER TABLE matches ADD COLUMN tb_score2 INTEGER")
    except:
        pass
    conn.commit()
    conn.close()


# ── Player CRUD ──

def add_player(name: str, phone: str, category: str, birth_date: str = None) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO players (name, phone, category, birth_date) VALUES (?, ?, ?, ?)",
        (name, phone, category, birth_date),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def get_players(category: str = None) -> list[dict]:
    conn = get_db()
    if category:
        rows = conn.execute(
            "SELECT * FROM players WHERE category=? ORDER BY id", (category,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM players ORDER BY category, id"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_player(player_id: int):
    conn = get_db()
    conn.execute("DELETE FROM players WHERE id=?", (player_id,))
    conn.commit()
    conn.close()


def update_player(player_id: int, name: str = None, phone: str = None, birth_date: str = None) -> bool:
    """Update player fields. Only provided (non-None) fields are changed.
    Returns True if the player was updated, False if no matching player found."""
    conn = get_db()
    fields = []
    values = []
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if phone is not None:
        fields.append("phone=?")
        values.append(phone)
    if birth_date is not None:
        fields.append("birth_date=?")
        values.append(birth_date if birth_date != "" else None)
    updated = False
    if fields:
        values.append(player_id)
        cur = conn.execute(f"UPDATE players SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        updated = cur.rowcount > 0
    conn.close()
    return updated


def get_player_count(category: str) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM players WHERE category=?", (category,)
    ).fetchone()
    conn.close()
    return row["cnt"]


# ── Match CRUD ──

def create_matches_batch(match_list: list[dict]) -> list[int]:
    """Insert multiple matches. Each dict: category, stage, group_name?, round?, match_order, player1_id, player2_id"""
    conn = get_db()
    ids = []
    for m in match_list:
        cur = conn.execute(
            """INSERT INTO matches (category, stage, group_name, round, match_order, player1_id, player2_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                m["category"],
                m["stage"],
                m.get("group_name"),
                m.get("round"),
                m.get("match_order"),
                m.get("player1_id"),
                m.get("player2_id"),
            ),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def get_matches(category: str, stage: str = None) -> list[dict]:
    conn = get_db()
    base = """SELECT m.*, p1.name AS player1_name, p2.name AS player2_name,
                     w.name AS winner_name
              FROM matches m
              LEFT JOIN players p1 ON m.player1_id = p1.id
              LEFT JOIN players p2 ON m.player2_id = p2.id
              LEFT JOIN players w  ON m.winner_id  = w.id"""
    if stage:
        rows = conn.execute(
            f"{base} WHERE m.category=? AND m.stage=? ORDER BY m.match_order, m.id",
            (category, stage),
        ).fetchall()
    else:
        rows = conn.execute(
            f"{base} WHERE m.category=? ORDER BY m.stage, m.match_order, m.id",
            (category,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_match(match_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        """SELECT m.*, p1.name AS player1_name, p2.name AS player2_name
           FROM matches m
           LEFT JOIN players p1 ON m.player1_id = p1.id
           LEFT JOIN players p2 ON m.player2_id = p2.id
           WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_match_score(match_id: int, score1: int, score2: int, winner_id: int | None,
                       tb_score1: int = None, tb_score2: int = None):
    conn = get_db()
    conn.execute(
        "UPDATE matches SET score1=?, score2=?, winner_id=?, status='completed', tb_score1=?, tb_score2=? WHERE id=?",
        (score1, score2, winner_id, tb_score1, tb_score2, match_id),
    )
    conn.commit()
    conn.close()


def update_match_player(match_id: int, slot: str, player_id: int | None):
    """Update player slot in a knockout match (for auto-advancement)"""
    conn = get_db()
    conn.execute(
        f"UPDATE matches SET {slot}=? WHERE id=?",
        (player_id, match_id),
    )
    conn.commit()
    conn.close()


def clear_matches(category: str, stage: str = None):
    conn = get_db()
    if stage:
        conn.execute(
            "DELETE FROM matches WHERE category=? AND stage=?", (category, stage)
        )
    else:
        conn.execute("DELETE FROM matches WHERE category=?", (category,))
    conn.commit()
    conn.close()


# ── State checks ──

def has_group_stage(category: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM matches WHERE category=? AND stage='group'",
        (category,),
    ).fetchone()
    conn.close()
    return row["cnt"] > 0


def all_group_matches_done(category: str) -> bool:
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM matches WHERE category=? AND stage='group'",
        (category,),
    ).fetchone()["cnt"]
    done = conn.execute(
        "SELECT COUNT(*) as cnt FROM matches WHERE category=? AND stage='group' AND status='completed'",
        (category,),
    ).fetchone()["cnt"]
    conn.close()
    return total > 0 and total == done


def has_knockout_stage(category: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM matches WHERE category=? AND stage!='group'",
        (category,),
    ).fetchone()
    conn.close()
    return row["cnt"] > 0


# ── Standings ──

def get_group_standings(category: str) -> dict:
    """Return {group_name: [{player_id, player_name, mp, wins, losses, pf, pa, pd}, ...]} sorted by wins→pd"""
    conn = get_db()
    all_matches = conn.execute(
        "SELECT * FROM matches WHERE category=? AND stage='group'", (category,)
    ).fetchall()
    completed = [m for m in all_matches if m["status"] == "completed" and m["winner_id"]]
    players = {
        p["id"]: p["name"]
        for p in conn.execute(
            "SELECT id, name FROM players WHERE category=?", (category,)
        ).fetchall()
    }
    conn.close()

    # Build group→players from all matches (including pending)
    gp = {}
    for m in all_matches:
        g = m["group_name"]
        gp.setdefault(g, set())
        if m["player1_id"]:
            gp[g].add(m["player1_id"])
        if m["player2_id"]:
            gp[g].add(m["player2_id"])

    standings = {}
    for g, pids in gp.items():
        stats = []
        for pid in pids:
            s = {
                "player_id": pid,
                "player_name": players.get(pid, "?"),
                "mp": 0, "wins": 0, "losses": 0,
                "pf": 0, "pa": 0, "pd": 0,
            }
            for m in completed:
                if m["group_name"] != g:
                    continue
                if m["player1_id"] == pid:
                    s["mp"] += 1
                    s["pf"] += m["score1"] or 0
                    s["pa"] += m["score2"] or 0
                    s["wins" if m["winner_id"] == pid else "losses"] += 1
                elif m["player2_id"] == pid:
                    s["mp"] += 1
                    s["pf"] += m["score2"] or 0
                    s["pa"] += m["score1"] or 0
                    s["wins" if m["winner_id"] == pid else "losses"] += 1
            s["pd"] = s["pf"] - s["pa"]
            stats.append(s)
        stats.sort(key=lambda x: (x["wins"], x["pd"]), reverse=True)
        standings[g] = stats

    return standings
