import sqlite3
import datetime
import shutil
import os
from app.config import DB_PATH, BACKUP_DB_PATH

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=60.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 60000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def sync_backup():
    try:
        if os.path.exists(DB_PATH) and DB_PATH != BACKUP_DB_PATH:
            shutil.copyfile(DB_PATH, BACKUP_DB_PATH)
    except Exception as e:
        pass

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # If backup exists and primary doesn't, restore from backup
    if not os.path.exists(DB_PATH) and os.path.exists(BACKUP_DB_PATH) and DB_PATH != BACKUP_DB_PATH:
        try:
            shutil.copyfile(BACKUP_DB_PATH, DB_PATH)
        except Exception:
            pass

    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        username TEXT UNIQUE,
        whatsapp_number TEXT NOT NULL,
        pin_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'MEMBER',
        applied_role TEXT NOT NULL DEFAULT 'MEMBER',
        role_status TEXT NOT NULL DEFAULT 'APPROVED',
        school_organization TEXT DEFAULT '', photo_url TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        school_organization TEXT DEFAULT '', photo_url TEXT DEFAULT '',
        leader_id INTEGER REFERENCES users(id),
        speaker1_id INTEGER REFERENCES users(id),
        speaker2_id INTEGER REFERENCES users(id),
        speaker3_id INTEGER REFERENCES users(id),
        speaker1_name_custom TEXT DEFAULT '',
        speaker2_name_custom TEXT DEFAULT '',
        speaker3_name_custom TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'DRAFT',
        rating TEXT NOT NULL DEFAULT 'B',
        is_official INTEGER NOT NULL DEFAULT 0,
        seed_number INTEGER,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tournament (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'SETUP',
        bracket_balance_score REAL DEFAULT 0.0,
        bracket_details TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS rounds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        round_number INTEGER UNIQUE NOT NULL,
        name TEXT NOT NULL,
        name_bn TEXT NOT NULL,
        motion_en TEXT DEFAULT '',
        motion_bn TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'DRAFT',
        prep_time_minutes INTEGER DEFAULT 15,
        speaking_time_seconds INTEGER DEFAULT 180
    );

    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        round_id INTEGER NOT NULL REFERENCES rounds(id),
        match_number INTEGER NOT NULL,
        bracket_position INTEGER NOT NULL,
        half TEXT NOT NULL DEFAULT 'LEFT',
        team1_id INTEGER REFERENCES teams(id),
        team2_id INTEGER REFERENCES teams(id),
        source_match1_id INTEGER,
        source_match2_id INTEGER,
        room_id INTEGER REFERENCES rooms(id),
        status TEXT NOT NULL DEFAULT 'SCHEDULED',
        winner_id INTEGER REFERENCES teams(id),
        team1_aggregate REAL DEFAULT NULL,
        team2_aggregate REAL DEFAULT NULL,
        tie_status TEXT NOT NULL DEFAULT 'NONE',
        tie_admin_winner_id INTEGER REFERENCES teams(id),
        tie_admin_reason TEXT DEFAULT NULL,
        is_published INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS judge_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
        judge_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        UNIQUE(match_id, judge_id)
    );

    CREATE TABLE IF NOT EXISTS judge_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        judge_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
        message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS scorecards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
        judge_id INTEGER NOT NULL REFERENCES users(id),
        status TEXT NOT NULL DEFAULT 'DRAFT',
        team1_total REAL DEFAULT 0.0,
        team2_total REAL DEFAULT 0.0,
        tie_choice_team_id INTEGER REFERENCES teams(id),
        submitted_at TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(match_id, judge_id)
    );

    CREATE TABLE IF NOT EXISTS score_criteria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scorecard_id INTEGER NOT NULL REFERENCES scorecards(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        name_bn TEXT DEFAULT '',
        max_marks REAL NOT NULL DEFAULT 30.0,
        sort_order INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS speaker_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scorecard_id INTEGER NOT NULL REFERENCES scorecards(id) ON DELETE CASCADE,
        criterion_id INTEGER NOT NULL REFERENCES score_criteria(id) ON DELETE CASCADE,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        speaker_position INTEGER NOT NULL,
        score REAL NOT NULL DEFAULT 0.0,
        UNIQUE(scorecard_id, criterion_id, team_id, speaker_position)
    );

    CREATE TABLE IF NOT EXISTS timer_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        speaking_time_seconds INTEGER NOT NULL DEFAULT 180,
        warning_1_seconds INTEGER NOT NULL DEFAULT 120,
        warning_2_seconds INTEGER NOT NULL DEFAULT 150,
        final_bell_seconds INTEGER NOT NULL DEFAULT 180,
        sound_enabled INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER REFERENCES users(id),
        actor_name TEXT NOT NULL,
        action TEXT NOT NULL,
        object_type TEXT NOT NULL,
        object_id TEXT NOT NULL,
        details TEXT DEFAULT '',
        previous_data TEXT DEFAULT '',
        is_undone INTEGER DEFAULT 0,
        timestamp TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS judge_admin_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL REFERENCES users(id),
        sender_name TEXT NOT NULL,
        sender_role TEXT NOT NULL,
        message TEXT NOT NULL,
        reply TEXT DEFAULT '',
        replied_at TEXT DEFAULT NULL,
        is_resolved INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS senior_segment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL DEFAULT 'Class 10 Master Championship',
        title_bn TEXT NOT NULL DEFAULT 'ক্লাস 10 মাস্টার বিতর্ক প্রতিযোগিতা 2026',
        team1_name TEXT NOT NULL DEFAULT 'Class 10 Master Team Alpha',
        team2_name TEXT NOT NULL DEFAULT 'Class 10 Master Team Beta',
        team1_leader_id INTEGER REFERENCES users(id),
        team1_speaker1_id INTEGER REFERENCES users(id),
        team1_speaker2_id INTEGER REFERENCES users(id),
        team1_speaker3_id INTEGER REFERENCES users(id),
        team2_leader_id INTEGER REFERENCES users(id),
        team2_speaker1_id INTEGER REFERENCES users(id),
        team2_speaker2_id INTEGER REFERENCES users(id),
        team2_speaker3_id INTEGER REFERENCES users(id),
        chief_judge_id INTEGER REFERENCES users(id),
        panel_judge1_id INTEGER REFERENCES users(id),
        panel_judge2_id INTEGER REFERENCES users(id),
        team1_speaker1 TEXT DEFAULT 'Master Debater 1',
        team1_speaker2 TEXT DEFAULT 'Master Debater 2',
        team1_speaker3 TEXT DEFAULT 'Master Debater 3',
        team2_speaker1 TEXT DEFAULT 'Master Debater 4',
        team2_speaker2 TEXT DEFAULT 'Master Debater 5',
        team2_speaker3 TEXT DEFAULT 'Master Debater 6',
        motion_en TEXT DEFAULT 'This House believes that experienced senior debaters should steer community leadership.',
        motion_bn TEXT DEFAULT 'এই সংসদ বিশ্বাস করে যে অভিজ্ঞ সিনিয়র বিতার্কিকদের সমাজের নেতৃত্ব দেওয়া উচিত।',
        room_name TEXT DEFAULT 'Central Debate Auditorium',
        status TEXT NOT NULL DEFAULT 'SCHEDULED',
        team1_score REAL DEFAULT 0.0,
        team2_score REAL DEFAULT 0.0,
        winner_team TEXT DEFAULT '',
        is_published INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS user_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        text_content TEXT DEFAULT '',
        canvas_data TEXT DEFAULT '',
        table_data TEXT DEFAULT '',
        updated_at TEXT NOT NULL,
        UNIQUE(user_id)
    );
    """)

    # Auto-migrate any existing database
    cursor.execute("PRAGMA table_info(users)")
    user_cols = [r[1] for r in cursor.fetchall()]
    if "username" not in user_cols:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
            cursor.execute("UPDATE users SET username = whatsapp_number WHERE username IS NULL OR username = ''")
        except Exception:
            pass

    cursor.execute("PRAGMA table_info(audit_logs)")
    audit_cols = [r[1] for r in cursor.fetchall()]
    if "previous_data" not in audit_cols:
        cursor.execute("ALTER TABLE audit_logs ADD COLUMN previous_data TEXT DEFAULT ''")
    if "is_undone" not in audit_cols:
        cursor.execute("ALTER TABLE audit_logs ADD COLUMN is_undone INTEGER DEFAULT 0")

    # Seed default rounds if not present
    cursor.execute("SELECT COUNT(*) FROM rounds;")
    if cursor.fetchone()[0] == 0:
        cursor.executescript("""
        INSERT INTO rounds (round_number, name, name_bn, status) VALUES
        (1, 'Round of 16', 'রাউন্ড অব 16', 'DRAFT'),
        (2, 'Quarter Final', 'কোয়ার্টার ফাইনাল', 'DRAFT'),
        (3, 'Semi Final', 'সেমি ফাইনাল', 'DRAFT'),
        (4, 'Final', 'ফাইনাল', 'DRAFT');
        """)

    # Seed default timer settings if not present
    cursor.execute("SELECT COUNT(*) FROM timer_settings;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO timer_settings (speaking_time_seconds, warning_1_seconds, warning_2_seconds, final_bell_seconds, sound_enabled) VALUES (180, 120, 150, 180, 1);")

    # Seed default tournament if not present
    cursor.execute("SELECT COUNT(*) FROM tournament;")
    if cursor.fetchone()[0] == 0:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor.execute("INSERT INTO tournament (name, date, status, created_at) VALUES (?, ?, ?, ?)",
                       ("National Traditional Debate Championship 2026", "2026-09-05", "SETUP", now_str))

    # Seed default rooms if not present
    cursor.execute("SELECT COUNT(*) FROM rooms;")
    if cursor.fetchone()[0] == 0:
        cursor.executescript("""
        INSERT INTO rooms (name, description) VALUES
        ('Room Alpha', 'Main Auditorium Left Wing'),
        ('Room Beta', 'Main Auditorium Right Wing'),
        ('Room Gamma', 'Seminar Hall 1'),
        ('Room Delta', 'Seminar Hall 2'),
        ('Room Epsilon', 'Debate Lab 101'),
        ('Room Zeta', 'Debate Lab 102'),
        ('Room Eta', 'Conference Room A'),
        ('Room Theta', 'Conference Room B');
        """)

    
    # Automatic migration for existing databases
    cursor.execute("PRAGMA table_info(users)")
    u_cols = [c[1] for c in cursor.fetchall()]
    if 'photo_url' not in u_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN photo_url TEXT DEFAULT ''")

    cursor.execute("PRAGMA table_info(teams)")
    t_cols = [c[1] for c in cursor.fetchall()]
    if 'speaker1_name_custom' not in t_cols:
        cursor.execute("ALTER TABLE teams ADD COLUMN speaker1_name_custom TEXT DEFAULT ''")
    if 'speaker2_name_custom' not in t_cols:
        cursor.execute("ALTER TABLE teams ADD COLUMN speaker2_name_custom TEXT DEFAULT ''")
    if 'speaker3_name_custom' not in t_cols:
        cursor.execute("ALTER TABLE teams ADD COLUMN speaker3_name_custom TEXT DEFAULT ''")
    if 'custom_name' not in t_cols:
        cursor.execute("ALTER TABLE teams ADD COLUMN custom_name TEXT DEFAULT ''")
    if 'photo_url' not in t_cols:
        cursor.execute("ALTER TABLE teams ADD COLUMN photo_url TEXT DEFAULT ''")

    # Migrate any team that has seed_number and custom name in name column
    cursor.execute("SELECT id, name, seed_number, custom_name FROM teams WHERE seed_number IS NOT NULL")
    for t_row in cursor.fetchall():
        t_id, t_n, t_s, t_c = t_row[0], t_row[1], t_row[2], t_row[3]
        if not t_c and t_n and not t_n.startswith("Team "):
            cursor.execute("UPDATE teams SET custom_name = ?, name = ? WHERE id = ?", (t_n, f"Team {t_s}", t_id))


    # Seed default 16 numbered teams (Team 1 - Team 16) if less than 16 teams exist
    cursor.execute("SELECT COUNT(*) FROM teams;")
    if cursor.fetchone()[0] < 16:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for i in range(1, 17):
            t_name = f"Team {i}"
            cursor.execute("SELECT id FROM teams WHERE name = ?", (t_name,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO teams (name, school_organization, rating, is_official, status, seed_number, created_at)
                    VALUES (?, 'Habiganj Govt. High School (HGHS)', 'B', 1, 'APPROVED', ?, ?)
                """, (t_name, i, now_str))

    # Auto-migrate senior_segment columns for user linking
    cursor.execute("PRAGMA table_info(senior_segment)")
    s_cols = [c[1] for c in cursor.fetchall()]
    for col in [
        "team1_leader_id", "team1_speaker1_id", "team1_speaker2_id", "team1_speaker3_id",
        "team2_leader_id", "team2_speaker1_id", "team2_speaker2_id", "team2_speaker3_id",
        "chief_judge_id", "panel_judge1_id", "panel_judge2_id"
    ]:
        if col not in s_cols:
            try:
                cursor.execute(f"ALTER TABLE senior_segment ADD COLUMN {col} INTEGER REFERENCES users(id)")
            except Exception:
                pass

    # Seed default senior master segment if empty
    cursor.execute("SELECT COUNT(*) FROM senior_segment;")
    if cursor.fetchone()[0] == 0:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO senior_segment (title, title_bn, team1_name, team2_name, status, created_at)
            VALUES ('Class 10 Master Championship', 'ক্লাস 10 মাস্টার বিতর্ক প্রতিযোগিতা 2026', 'Class 10 Master Team Alpha', 'Class 10 Master Team Beta', 'SCHEDULED', ?)
        """, (now_str,))

    ensure_senior_users(conn)

    conn.commit()
    conn.close()
    sync_backup()

def ensure_senior_users(conn):
    cursor = conn.cursor()
    from app.auth import hash_pin

    default_seniors = [
        # Debaters
        ("সাদমান রহমান (Sadman Rahman)", "sadman10", "01710000001", "LEADER", "LEADER", "Class 10, HGHS"),
        ("তাহমিদ চৌধুরী (Tahmid Chowdhury)", "tahmid10", "01710000002", "MEMBER", "MEMBER", "Class 10, HGHS"),
        ("নাফিস আহমেদ (Nafis Ahmed)", "nafis10", "01710000003", "MEMBER", "MEMBER", "Class 10, HGHS"),
        ("আবরার হাবিব (Abrar Habib)", "abrar10", "01710000004", "LEADER", "LEADER", "Class 10, HGHS"),
        ("সামিউল হক (Samiul Haque)", "samiul10", "01710000005", "MEMBER", "MEMBER", "Class 10, HGHS"),
        ("জুবায়ের হাসান (Zubayer Hasan)", "zubayer10", "01710000006", "MEMBER", "MEMBER", "Class 10, HGHS"),
        # Official Senior Judges
        ("তানভীর হাসান (Tanvir Hasan)", "tanvir_judge", "01710000007", "JUDGE", "JUDGE", "National Adjudication Board / HGHS Alumni"),
        ("ফাহিম মাহমুদ (Fahim Mahmud)", "fahim_judge", "01710000008", "JUDGE", "JUDGE", "Sylhet Divisional Adjudication Panel"),
        ("তাসনিম জাহান (Tasnim Jahan)", "tasnim_judge", "01710000009", "JUDGE", "JUDGE", "National Debate Federation"),
    ]

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    senior_user_ids = {}

    for name, uname, phone, role, app_role, school in default_seniors:
        cursor.execute("SELECT id, full_name, whatsapp_number, username FROM users WHERE LOWER(username) = LOWER(?) OR whatsapp_number = ?", (uname, phone))
        row = cursor.fetchone()
        if not row:
            pin_hash, salt = hash_pin("1234")
            cursor.execute("""
                INSERT INTO users (full_name, username, whatsapp_number, pin_hash, salt, role, applied_role, role_status, school_organization, photo_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'APPROVED', ?, '', ?)
            """, (name, uname, phone, pin_hash, salt, role, app_role, school, now_str))
            senior_user_ids[uname] = cursor.lastrowid
        else:
            cursor.execute("UPDATE users SET username = ?, full_name = ?, role = ?, role_status = 'APPROVED' WHERE id = ?", (uname, name, role, row[0]))
            senior_user_ids[uname] = row[0]

    # Ensure senior_segment record links these users and judges if unassigned
    cursor.execute("SELECT id, team1_leader_id, team1_speaker1_id, chief_judge_id FROM senior_segment ORDER BY id ASC LIMIT 1")
    s_row = cursor.fetchone()
    if s_row:
        seg_id, t1_lead, t1_sp1, c_judge = s_row[0], s_row[1], s_row[2], s_row[3]
        if not t1_lead or not t1_sp1:
            cursor.execute("""
                UPDATE senior_segment
                SET team1_leader_id = ?,
                    team1_speaker1_id = ?,
                    team1_speaker2_id = ?,
                    team1_speaker3_id = ?,
                    team1_speaker1 = ?,
                    team1_speaker2 = ?,
                    team1_speaker3 = ?,
                    team2_leader_id = ?,
                    team2_speaker1_id = ?,
                    team2_speaker2_id = ?,
                    team2_speaker3_id = ?,
                    team2_speaker1 = ?,
                    team2_speaker2 = ?,
                    team2_speaker3 = ?
                WHERE id = ?
            """, (
                senior_user_ids.get("sadman10"),
                senior_user_ids.get("sadman10"),
                senior_user_ids.get("tahmid10"),
                senior_user_ids.get("nafis10"),
                "সাদমান রহমান (Sadman Rahman)",
                "তাহমিদ চৌধুরী (Tahmid Chowdhury)",
                "নাফিস আহমেদ (Nafis Ahmed)",
                senior_user_ids.get("abrar10"),
                senior_user_ids.get("abrar10"),
                senior_user_ids.get("samiul10"),
                senior_user_ids.get("zubayer10"),
                "আবরার হাবিব (Abrar Habib)",
                "সামিউল হক (Samiul Haque)",
                "জুবায়ের হাসান (Zubayer Hasan)",
                seg_id
            ))

        if not c_judge:
            cursor.execute("""
                UPDATE senior_segment
                SET chief_judge_id = ?,
                    panel_judge1_id = ?,
                    panel_judge2_id = ?,
                    room_name = 'Central Debate Auditorium'
                WHERE id = ?
            """, (
                senior_user_ids.get("tanvir_judge"),
                senior_user_ids.get("fahim_judge"),
                senior_user_ids.get("tasnim_judge"),
                seg_id
            ))

def log_audit(conn, actor_id, actor_name, action, object_type, object_id, details="", previous_data=""):
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if isinstance(previous_data, (dict, list)):
        import json
        previous_data = json.dumps(previous_data)
    conn.execute(
        "INSERT INTO audit_logs (actor_id, actor_name, action, object_type, object_id, details, previous_data, is_undone, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (actor_id, actor_name, action, object_type, str(object_id), str(details), str(previous_data or ""), timestamp)
    )
