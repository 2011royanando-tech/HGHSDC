import datetime
from app.database import get_db, init_db
from app.auth import hash_pin

def seed_demo_data(clean_test_users: bool = True):
    """Ensures solely the clean Tab Director Admin account exists."""
    init_db()
    conn = get_db()
    cursor = conn.cursor()

    if clean_test_users:
        cursor.execute("PRAGMA foreign_keys = OFF;")
        cursor.execute("DELETE FROM speaker_scores")
        cursor.execute("DELETE FROM scorecards")
        cursor.execute("DELETE FROM judge_assignments")
        cursor.execute("DELETE FROM judge_notifications")
        cursor.execute("DELETE FROM matches")
        cursor.execute("DELETE FROM teams")
        cursor.execute("UPDATE rounds SET status = 'DRAFT', motion_en = '', motion_bn = ''")
        cursor.execute("UPDATE tournament SET status = 'SETUP', bracket_balance_score = 0.0, bracket_details = ''")
        cursor.execute("DELETE FROM sessions WHERE user_id NOT IN (SELECT id FROM users WHERE role = 'ADMIN')")
        cursor.execute("DELETE FROM users WHERE whatsapp_number != 'HGHSDC' AND role != 'ADMIN'")
        cursor.execute("PRAGMA foreign_keys = ON;")
        conn.commit()

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    pin_hash, salt = hash_pin("129417#")

    cursor.execute("SELECT id FROM users WHERE whatsapp_number = 'HGHSDC' OR role = 'ADMIN'")
    admin = cursor.fetchone()
    if not admin:
        cursor.execute("""
            INSERT INTO users (full_name, whatsapp_number, username, pin_hash, salt, role, applied_role, role_status, school_organization, photo_url, created_at)
            VALUES ('Tab Director (HGHSDC)', 'HGHSDC', 'hghsdc', ?, ?, 'ADMIN', 'ADMIN', 'APPROVED', 'Habiganj Govt. High School (HGHSDC)', '', ?)
        """, (pin_hash, salt, now_str))
        conn.commit()

    # Pre-seed 16 official numbered teams (Team 1 - Team 16)
    cursor.execute("SELECT COUNT(*) FROM teams;")
    if cursor.fetchone()[0] < 16:
        for i in range(1, 17):
            t_name = f"Team {i}"
            cursor.execute("SELECT id FROM teams WHERE name = ?", (t_name,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO teams (name, school_organization, rating, is_official, status, seed_number, created_at)
                    VALUES (?, 'Habiganj Govt. High School (HGHS)', 'B', 1, 'APPROVED', ?, ?)
                """, (t_name, i, now_str))
        conn.commit()

    # Ensure senior segment row
    cursor.execute("SELECT COUNT(*) FROM senior_segment;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO senior_segment (title, title_bn, team1_name, team2_name, status, created_at)
            VALUES ('Class 10 Master Championship', 'ক্লাস ১০ মাস্টার বিতর্ক প্রতিযোগিতা ২০২৬', 'Class 10 Master Team Alpha', 'Class 10 Master Team Beta', 'SCHEDULED', ?)
        """, (now_str,))
        conn.commit()

    conn.close()
    print("Database ready with solely Admin: HGHSDC / 129417#")

if __name__ == "__main__":
    seed_demo_data()
