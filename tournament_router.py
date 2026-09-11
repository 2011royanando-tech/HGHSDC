import json
import datetime
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db, log_audit
from app.auth import get_current_user, require_admin, get_current_user_optional
from typing import Optional, List
from app.bracket_algo import generate_balanced_bracket, generate_random_bracket, calculate_bracket_metrics
from app.models import BracketManualSwapRequest, RoundUpdateRequest, RoomCreateRequest, ManualBracketSetupRequest
from pydantic import BaseModel

router = APIRouter(prefix="/api/tournament", tags=["Tournament & Bracket"])

@router.get("/status")
def get_tournament_status(user: dict = Depends(get_current_user_optional)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, date, status, bracket_balance_score, created_at FROM tournament ORDER BY id DESC LIMIT 1")
    tourn = cursor.fetchone()

    is_admin = user and user.get("role") == "ADMIN"
    stats = {}

    if is_admin:
        cursor.execute("SELECT COUNT(*) FROM teams WHERE status = 'APPROVED'")
        approved_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM teams WHERE is_official = 1 AND status = 'APPROVED'")
        official_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE applied_role = 'LEADER' AND role_status = 'PENDING_APPROVAL'")
        pending_leaders = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE applied_role = 'JUDGE' AND role_status = 'PENDING_APPROVAL'")
        pending_judges = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM teams WHERE status = 'PENDING_ADMIN_APPROVAL'")
        pending_teams = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM matches WHERE status = 'LIVE'")
        active_matches = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM scorecards WHERE status = 'DRAFT'")
        pending_ballots = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM matches WHERE is_published = 0 AND team1_aggregate IS NOT NULL")
        pending_publications = cursor.fetchone()[0]

        stats = {
            "approved_teams": approved_count,
            "official_teams": official_count,
            "total_users": total_users,
            "pending_leaders": pending_leaders,
            "pending_judges": pending_judges,
            "pending_teams": pending_teams,
            "active_matches": active_matches,
            "pending_ballots": pending_ballots,
            "pending_publications": pending_publications
        }

    conn.close()

    return {
        "tournament": dict(tourn) if tourn else None,
        "stats": stats
    }

@router.post("/bracket/generate")
def auto_generate_bracket(mode: Optional[str] = "random", admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    # Check tournament status
    cursor.execute("SELECT status FROM tournament ORDER BY id DESC LIMIT 1")
    tourn = cursor.fetchone()
    if tourn and tourn["status"] == "BRACKET_LOCKED":
        conn.close()
        raise HTTPException(status_code=400, detail="Bracket is locked. Modification requires explicit unlocking or override.")

    # Fetch official teams (must be exactly 16)
    cursor.execute("""
        SELECT id, name, school_organization, rating, is_official
        FROM teams
        WHERE is_official = 1 AND status = 'APPROVED'
        ORDER BY name ASC
    """)
    teams = [dict(r) for r in cursor.fetchall()]

    if len(teams) > 16:
        teams = teams[:16]
    elif len(teams) < 16:
        # Check if there are at least 16 approved teams we can auto-mark as official
        cursor.execute("SELECT id, name, school_organization, rating, is_official FROM teams WHERE status = 'APPROVED' ORDER BY name ASC")
        all_approved = [dict(r) for r in cursor.fetchall()]
        if len(all_approved) >= 16:
            cursor.execute("UPDATE teams SET is_official = 0")
            top16_ids = [t["id"] for t in all_approved[:16]]
            cursor.execute(f"UPDATE teams SET is_official = 1 WHERE id IN ({','.join('?'*16)})", top16_ids)
            conn.commit()
            teams = all_approved[:16]
        else:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"16 official teams are required before the tournament can be locked. (Currently approved: {len(all_approved)}, official: {len(teams)})"
            )

    if mode == "balanced":
        matches_data, metrics = generate_balanced_bracket(teams)
    else:
        matches_data, metrics = generate_random_bracket(teams)

    # Get round IDs (re-seed if missing)
    cursor.execute("SELECT id, round_number FROM rounds")
    rounds_map = {r["round_number"]: r["id"] for r in cursor.fetchall()}
    if not all(k in rounds_map for k in (1, 2, 3, 4)):
        cursor.executescript("""
            INSERT OR IGNORE INTO rounds (round_number, name, name_bn, status) VALUES
            (1, 'Round of 16', 'রাউন্ড অব 16', 'DRAFT'),
            (2, 'Quarter Final', 'কোয়ার্টার ফাইনাল', 'DRAFT'),
            (3, 'Semi Final', 'সেমি ফাইনাল', 'DRAFT'),
            (4, 'Final', 'ফাইনাল', 'DRAFT');
        """)
        cursor.execute("SELECT id, round_number FROM rounds")
        rounds_map = {r["round_number"]: r["id"] for r in cursor.fetchall()}

    # Get available rooms
    cursor.execute("SELECT id FROM rooms ORDER BY id ASC")
    room_ids = [r["id"] for r in cursor.fetchall()]

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Delete existing matches to regenerate
    cursor.execute("DELETE FROM speaker_scores"); cursor.execute("DELETE FROM score_criteria"); cursor.execute("DELETE FROM scorecards"); cursor.execute("DELETE FROM judge_assignments"); cursor.execute("DELETE FROM matches")

    # Insert R16 matches (1 to 8)
    for m in matches_data:
        m_num = m['match_number']
        room_id = room_ids[(m_num - 1) % len(room_ids)] if room_ids else None
        cursor.execute("""
            INSERT INTO matches (round_id, match_number, bracket_position, half, team1_id, team2_id, room_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'SCHEDULED', ?)
        """, (rounds_map[1], m_num, m_num, m['half'], m['team1_id'], m['team2_id'], room_id, now_str))

    # Insert QF matches (9 to 12)
    # Match 9: winner of 1 vs winner of 2
    # Match 10: winner of 3 vs winner of 4
    # Match 11: winner of 5 vs winner of 6
    # Match 12: winner of 7 vs winner of 8
    qf_sources = [(1, 2), (3, 4), (5, 6), (7, 8)]
    for idx, (s1, s2) in enumerate(qf_sources):
        m_num = 9 + idx
        half = 'LEFT' if m_num <= 10 else 'RIGHT'
        room_id = room_ids[(m_num - 1) % len(room_ids)] if room_ids else None
        cursor.execute("""
            INSERT INTO matches (round_id, match_number, bracket_position, half, source_match1_id, source_match2_id, room_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'SCHEDULED', ?)
        """, (rounds_map[2], m_num, m_num, half, s1, s2, room_id, now_str))

    # Insert SF matches (13 to 14)
    # Match 13: winner of 9 vs winner of 10 (Left Finalist)
    # Match 14: winner of 11 vs winner of 12 (Right Finalist)
    cursor.execute("""
        INSERT INTO matches (round_id, match_number, bracket_position, half, source_match1_id, source_match2_id, room_id, status, created_at)
        VALUES (?, 13, 13, 'LEFT', 9, 10, ?, 'SCHEDULED', ?)
    """, (rounds_map[3], room_ids[0] if room_ids else None, now_str))
    cursor.execute("""
        INSERT INTO matches (round_id, match_number, bracket_position, half, source_match1_id, source_match2_id, room_id, status, created_at)
        VALUES (?, 14, 14, 'RIGHT', 11, 12, ?, 'SCHEDULED', ?)
    """, (rounds_map[3], room_ids[1] if len(room_ids) > 1 else None, now_str))

    # Insert Final match (15)
    # Match 15: winner of 13 vs winner of 14
    cursor.execute("""
        INSERT INTO matches (round_id, match_number, bracket_position, half, source_match1_id, source_match2_id, room_id, status, created_at)
        VALUES (?, 15, 15, 'FINAL', 13, 14, ?, 'SCHEDULED', ?)
    """, (rounds_map[4], room_ids[0] if room_ids else None, now_str))

    cursor.execute("""
        UPDATE tournament
        SET status = 'BRACKET_GENERATED', bracket_balance_score = ?, bracket_details = ?
    """, (metrics["balance_score"], metrics["explanation"]))

    log_audit(conn, admin["id"], admin["full_name"], "GENERATE_BRACKET", "TOURNAMENT", "BRACKET", metrics["explanation"])
    conn.commit()
    conn.close()

    return {
        "success": True,
        "metrics": metrics,
        "message": "Balanced bracket generated successfully."
    }

@router.post("/bracket/manual-setup")
def manual_setup_bracket(req: ManualBracketSetupRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM tournament ORDER BY id DESC LIMIT 1")
    tourn = cursor.fetchone()
    if tourn and tourn["status"] == "BRACKET_LOCKED":
        conn.close()
        raise HTTPException(status_code=400, detail="Bracket is locked. Modification requires explicit unlocking or override.")

    if not req.matches or len(req.matches) != 8:
        conn.close()
        raise HTTPException(status_code=400, detail="Exactly 8 matches (Match 1 to Match 8) must be provided for the Round of 16.")

    selected_team_ids = []
    for m in req.matches:
        if not m.team1_id or not m.team2_id:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Both Team 1 and Team 2 must be selected for Match {m.match_number}.")
        if m.team1_id == m.team2_id:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Match {m.match_number} has the same team selected as both sides.")
        selected_team_ids.extend([m.team1_id, m.team2_id])

    if len(selected_team_ids) != len(set(selected_team_ids)):
        conn.close()
        raise HTTPException(status_code=400, detail="Each team can only be assigned to one match in the Round of 16. Duplicate teams detected.")

    cursor.execute("SELECT id, round_number FROM rounds")
    rounds_map = {r["round_number"]: r["id"] for r in cursor.fetchall()}
    if not all(k in rounds_map for k in (1, 2, 3, 4)):
        cursor.executescript("""
            INSERT OR IGNORE INTO rounds (round_number, name, name_bn, status) VALUES
            (1, 'Round of 16', 'রাউন্ড অব 16', 'DRAFT'),
            (2, 'Quarter Final', 'কোয়ার্টার ফাইনাল', 'DRAFT'),
            (3, 'Semi Final', 'সেমি ফাইনাল', 'DRAFT'),
            (4, 'Final', 'ফাইনাল', 'DRAFT');
        """)
        cursor.execute("SELECT id, round_number FROM rounds")
        rounds_map = {r["round_number"]: r["id"] for r in cursor.fetchall()}

    cursor.execute("SELECT id FROM rooms ORDER BY id ASC")
    room_ids = [r["id"] for r in cursor.fetchall()]

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    cursor.execute("DELETE FROM speaker_scores")
    cursor.execute("DELETE FROM score_criteria")
    cursor.execute("DELETE FROM scorecards")
    cursor.execute("DELETE FROM judge_assignments")
    cursor.execute("DELETE FROM matches")

    sorted_matches = sorted(req.matches, key=lambda x: x.match_number)
    for m in sorted_matches:
        m_num = m.match_number
        half = 'LEFT' if m_num <= 4 else 'RIGHT'
        room_id = room_ids[(m_num - 1) % len(room_ids)] if room_ids else None
        cursor.execute("""
            INSERT INTO matches (round_id, match_number, bracket_position, half, team1_id, team2_id, room_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'SCHEDULED', ?)
        """, (rounds_map[1], m_num, m_num, half, m.team1_id, m.team2_id, room_id, now_str))

    qf_sources = [(1, 2), (3, 4), (5, 6), (7, 8)]
    for idx, (s1, s2) in enumerate(qf_sources):
        m_num = 9 + idx
        half = 'LEFT' if m_num <= 10 else 'RIGHT'
        room_id = room_ids[(m_num - 1) % len(room_ids)] if room_ids else None
        cursor.execute("""
            INSERT INTO matches (round_id, match_number, bracket_position, half, source_match1_id, source_match2_id, room_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'SCHEDULED', ?)
        """, (rounds_map[2], m_num, m_num, half, s1, s2, room_id, now_str))

    cursor.execute("""
        INSERT INTO matches (round_id, match_number, bracket_position, half, source_match1_id, source_match2_id, room_id, status, created_at)
        VALUES (?, 13, 13, 'LEFT', 9, 10, ?, 'SCHEDULED', ?)
    """, (rounds_map[3], room_ids[0] if room_ids else None, now_str))
    cursor.execute("""
        INSERT INTO matches (round_id, match_number, bracket_position, half, source_match1_id, source_match2_id, room_id, status, created_at)
        VALUES (?, 14, 14, 'RIGHT', 11, 12, ?, 'SCHEDULED', ?)
    """, (rounds_map[3], room_ids[1] if len(room_ids) > 1 else None, now_str))

    cursor.execute("""
        INSERT INTO matches (round_id, match_number, bracket_position, half, source_match1_id, source_match2_id, room_id, status, created_at)
        VALUES (?, 15, 15, 'FINAL', 13, 14, ?, 'SCHEDULED', ?)
    """, (rounds_map[4], room_ids[0] if room_ids else None, now_str))

    cursor.execute("UPDATE teams SET is_official = 0")
    cursor.execute(f"UPDATE teams SET is_official = 1 WHERE id IN ({','.join('?'*16)})", selected_team_ids)

    cursor.execute("""
        UPDATE tournament
        SET status = 'BRACKET_GENERATED', bracket_balance_score = 100.0,
            bracket_details = 'ম্যানুয়াল কাস্টম পেয়ারিং দ্বারা ব্র্যাকেট নির্ধারিত হয়েছে (Manual Custom Bracket Setup)'
    """)

    log_audit(conn, admin["id"], admin["full_name"], "MANUAL_BRACKET_SETUP", "TOURNAMENT", "BRACKET", "Configured custom manual bracket pairs for Round of 16")
    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "ম্যানুয়াল ব্র্যাকেট সফলভাবে সংরক্ষিত ও প্রস্তুত করা হয়েছে! (Manual bracket applied successfully!)"
    }

@router.post("/bracket/manual-swap")
def manual_swap_bracket(req: BracketManualSwapRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM tournament ORDER BY id DESC LIMIT 1")
    tourn = cursor.fetchone()
    if tourn and tourn["status"] == "BRACKET_LOCKED":
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot manually adjust a locked bracket without explicit unlock.")

    # Get match 1 and match 2
    cursor.execute("SELECT id, team1_id, team2_id, match_number FROM matches WHERE match_number = ?", (req.match_id_1,))
    m1 = cursor.fetchone()
    cursor.execute("SELECT id, team1_id, team2_id, match_number FROM matches WHERE match_number = ?", (req.match_id_2,))
    m2 = cursor.fetchone()

    if not m1 or not m2:
        conn.close()
        raise HTTPException(status_code=404, detail="One or both matches not found.")

    team1 = m1[f"team{req.slot_1}_id"]
    team2 = m2[f"team{req.slot_2}_id"]

    prev_swap_data = {
        "match_id_1": req.match_id_1, "slot_1": req.slot_1, "team1_id": team1,
        "match_id_2": req.match_id_2, "slot_2": req.slot_2, "team2_id": team2
    }
    cursor.execute(f"UPDATE matches SET team{req.slot_1}_id = ? WHERE match_number = ?", (team2, req.match_id_1))
    cursor.execute(f"UPDATE matches SET team{req.slot_2}_id = ? WHERE match_number = ?", (team1, req.match_id_2))

    log_audit(conn, admin["id"], admin["full_name"], "BRACKET_MANUAL_SWAP", "MATCHES",
              f"{req.match_id_1}:{req.slot_1} <-> {req.match_id_2}:{req.slot_2}",
              f"Swapped team {team1} and team {team2}", previous_data=prev_swap_data)
    conn.commit()
    conn.close()

    return {"success": True, "message": "Teams swapped successfully."}

@router.post("/bracket/unlock")
def unlock_bracket(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM tournament ORDER BY id DESC LIMIT 1")
    tourn = cursor.fetchone()
    if not tourn:
        conn.close()
        raise HTTPException(status_code=404, detail="Tournament not found.")

    # Unlock tournament bracket
    cursor.execute("UPDATE tournament SET status = 'BRACKET_GENERATED'")
    cursor.execute("UPDATE rounds SET status = 'DRAFT' WHERE round_number = 1")
    cursor.execute("UPDATE matches SET status = 'SCHEDULED' WHERE match_number BETWEEN 1 AND 8 AND status = 'READY'")

    log_audit(conn, admin["id"], admin["full_name"], "UNLOCK_BRACKET", "TOURNAMENT", "BRACKET", "Tournament bracket unlocked by Tab Director")
    conn.commit()
    conn.close()

    return {"success": True, "message": "Tournament bracket unlocked. You can now adjust pairings, swap teams, or regenerate."}

@router.post("/bracket/lock")
def lock_bracket(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    # Verify exactly 16 official teams exist
    cursor.execute("SELECT COUNT(*) FROM teams WHERE is_official = 1 AND status = 'APPROVED'")
    official_count = cursor.fetchone()[0]
    if official_count > 16:
        # Ensure only the 16 teams assigned to R16 are marked official
        cursor.execute("SELECT DISTINCT team1_id FROM matches WHERE match_number BETWEEN 1 AND 8 UNION SELECT DISTINCT team2_id FROM matches WHERE match_number BETWEEN 1 AND 8")
        assigned_ids = [r[0] for r in cursor.fetchall() if r[0] is not None]
        if len(assigned_ids) == 16:
            cursor.execute("UPDATE teams SET is_official = 0")
            cursor.execute(f"UPDATE teams SET is_official = 1 WHERE id IN ({','.join('?'*16)})", assigned_ids)
            conn.commit()
            official_count = 16
        else:
            conn.close()
            raise HTTPException(status_code=400, detail="16 official teams are required before the tournament can be locked.")
    elif official_count < 16:
        conn.close()
        raise HTTPException(status_code=400, detail="16 official teams are required before the tournament can be locked.")

    # Verify all 8 R16 matches have 2 teams assigned
    cursor.execute("SELECT COUNT(*) FROM matches WHERE match_number BETWEEN 1 AND 8 AND team1_id IS NOT NULL AND team2_id IS NOT NULL")
    ready_r16 = cursor.fetchone()[0]
    if ready_r16 != 8:
        conn.close()
        raise HTTPException(status_code=400, detail="All 8 Round-of-16 matches must have assigned teams before locking.")

    cursor.execute("UPDATE tournament SET status = 'BRACKET_LOCKED'")
    cursor.execute("UPDATE rounds SET status = 'READY' WHERE round_number = 1")
    cursor.execute("UPDATE matches SET status = 'READY' WHERE match_number BETWEEN 1 AND 8")

    log_audit(conn, admin["id"], admin["full_name"], "LOCK_BRACKET", "TOURNAMENT", "BRACKET", "Bracket officially locked")
    conn.commit()
    conn.close()

    return {"success": True, "message": "Tournament bracket locked. Round of 16 is now READY."}

@router.get("/bracket")
def get_bracket(user: dict = Depends(get_current_user_optional)):
    """
    Returns full visual bracket (15 matches: R16, QF, SF, Final).
    Strictly enforces Silent Result system:
    - If a match is NOT published, non-admins and unauthorized users do not see scores or unpublished winner!
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.id, m.round_id, m.match_number, m.bracket_position, m.half,
               m.team1_id, m.team2_id, m.source_match1_id, m.source_match2_id,
               m.room_id, m.status, m.winner_id, m.team1_aggregate, m.team2_aggregate,
               m.tie_status, m.is_published,
               t1.name AS team1_name, t1.custom_name AS team1_custom_name, t1.seed_number AS team1_seed, t1.status AS team1_status, t1.school_organization AS team1_school,
               t2.name AS team2_name, t2.custom_name AS team2_custom_name, t2.seed_number AS team2_seed, t2.status AS team2_status, t2.school_organization AS team2_school,
               w.name AS winner_name, w.custom_name AS winner_custom_name, w.seed_number AS winner_seed, w.status AS winner_status,
               r.name AS round_name, r.round_number,
               rm.name AS room_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN teams w ON m.winner_id = w.id
        LEFT JOIN rounds r ON m.round_id = r.id
        LEFT JOIN rooms rm ON m.room_id = rm.id
        ORDER BY m.match_number ASC
    """)
    rows = cursor.fetchall()

    is_admin = user and user.get("role") == "ADMIN"
    user_id = user.get("id") if user else None

    # Find matches where this user is an assigned judge
    assigned_match_ids = set()
    if user_id:
        cursor.execute("SELECT match_id FROM judge_assignments WHERE judge_id = ?", (user_id,))
        assigned_match_ids = {r[0] for r in cursor.fetchall()}

    cursor.execute("SELECT * FROM tournament ORDER BY id DESC LIMIT 1")
    tourn = cursor.fetchone()
    conn.close()

    matches = []
    for r in rows:
        m_dict = dict(r)
        can_see_private = is_admin or (m_dict["id"] in assigned_match_ids)
        if not m_dict["is_published"] and not can_see_private:
            # Silent Result enforcement
            m_dict["team1_aggregate"] = None
            m_dict["team2_aggregate"] = None
            m_dict["winner_id"] = None
            m_dict["winner_name"] = None
            m_dict["winner_custom_name"] = None
            m_dict["winner_seed"] = None
            m_dict["winner_status"] = None
            if m_dict["status"] in ("SILENT", "PUBLISHED", "COMPLETED"):
                m_dict["status"] = "REVIEW"

        matches.append(m_dict)

    return {
        "tournament": dict(tourn) if tourn else None,
        "matches": matches
    }

@router.get("/rounds")
def get_rounds():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rounds ORDER BY round_number ASC")
    rounds = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"rounds": rounds}

@router.put("/rounds/{round_number}")
def update_round(round_number: int, req: RoundUpdateRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE rounds
        SET motion_en = ?, motion_bn = ?, prep_time_minutes = ?, speaking_time_seconds = ?
        WHERE round_number = ?
    """, (req.motion_en, req.motion_bn, req.prep_time_minutes, req.speaking_time_seconds, round_number))
    log_audit(conn, admin["id"], admin["full_name"], "UPDATE_ROUND_MOTION", "ROUND", round_number,
              f"Updated motion for round {round_number}")
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Round {round_number} updated."}

@router.get("/rooms")
def get_rooms():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rooms ORDER BY name ASC")
    rooms = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"rooms": rooms}

@router.post("/rooms")
def create_room(req: RoomCreateRequest, admin: dict = Depends(require_admin)):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Room name is required.")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO rooms (name, description) VALUES (?, ?)", (req.name.strip(), (req.description or "").strip()))
    room_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"success": True, "room_id": room_id, "name": req.name.strip()}

class GranularResetRequest(BaseModel):
    reset_users: bool = False
    user_roles: Optional[List[str]] = None
    selected_user_ids: Optional[List[int]] = None
    reset_rounds: bool = False
    selected_round_ids: Optional[List[int]] = None
    reset_judging: bool = False
    selected_judge_ids: Optional[List[int]] = None
    reset_teams: bool = False
    reset_messages: bool = False
    reset_audit: bool = False
    reset_senior: bool = False

@router.get("/granular-reset-options")
def get_granular_reset_options(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, full_name, username, whatsapp_number, role, school_organization
        FROM users
        WHERE role != 'ADMIN' AND id != 1 AND username NOT IN ('admin', 'hghsdc') AND whatsapp_number NOT IN ('01700000000', 'HGHSDC')
        ORDER BY role ASC, full_name ASC
    """)
    users = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT id, round_number, name, name_bn, status FROM rounds ORDER BY round_number ASC")
    rounds = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT u.id, u.full_name, u.username, u.whatsapp_number,
               (SELECT COUNT(*) FROM scorecards sc WHERE sc.judge_id = u.id AND sc.status = 'SUBMITTED') AS submitted_ballots_count
        FROM users u
        WHERE u.role = 'JUDGE'
        ORDER BY u.full_name ASC
    """)
    judges = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "users": users,
        "rounds": rounds,
        "judges": judges
    }

@router.post("/granular-reset")
def execute_granular_reset(req: GranularResetRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    audit_actions = []

    # 1. USERS RESET (TAB DIRECTOR ADMIN IS PERMANENTLY PROTECTED)
    if req.reset_users:
        user_query = """
            SELECT id, role, full_name FROM users
            WHERE role != 'ADMIN' AND id != 1 AND username NOT IN ('admin', 'hghsdc') AND whatsapp_number NOT IN ('01700000000', 'HGHSDC')
        """
        params = []
        if req.selected_user_ids:
            placeholders = ",".join("?" * len(req.selected_user_ids))
            user_query += f" AND id IN ({placeholders})"
            params.extend(req.selected_user_ids)
        elif req.user_roles:
            placeholders = ",".join("?" * len(req.user_roles))
            user_query += f" AND role IN ({placeholders})"
            params.extend(req.user_roles)

        cursor.execute(user_query, params)
        target_users = cursor.fetchall()
        del_ids = [u["id"] for u in target_users]

        if del_ids:
            p_str = ",".join("?" * len(del_ids))
            # Clear foreign references in teams
            cursor.execute(f"UPDATE teams SET speaker1_id = NULL WHERE speaker1_id IN ({p_str})", del_ids)
            cursor.execute(f"UPDATE teams SET speaker2_id = NULL WHERE speaker2_id IN ({p_str})", del_ids)
            cursor.execute(f"UPDATE teams SET speaker3_id = NULL WHERE speaker3_id IN ({p_str})", del_ids)
            cursor.execute(f"UPDATE teams SET leader_id = NULL WHERE leader_id IN ({p_str})", del_ids)

            # Clear judge assignments & notifications
            cursor.execute(f"DELETE FROM judge_assignments WHERE judge_id IN ({p_str})", del_ids)
            cursor.execute(f"DELETE FROM judge_notifications WHERE judge_id IN ({p_str})", del_ids)
            cursor.execute(f"DELETE FROM user_notes WHERE user_id IN ({p_str})", del_ids)

            # Delete speaker scores for ballots by these judges
            cursor.execute(f"DELETE FROM speaker_scores WHERE scorecard_id IN (SELECT id FROM scorecards WHERE judge_id IN ({p_str}))", del_ids)
            cursor.execute(f"DELETE FROM scorecards WHERE judge_id IN ({p_str})", del_ids)

            # Delete users
            cursor.execute(f"DELETE FROM users WHERE id IN ({p_str})", del_ids)
            audit_actions.append(f"Reset {len(del_ids)} users (Tab Director protected)")

    # 2. ROUNDS & MATCHES RESET
    if req.reset_rounds:
        if req.selected_round_ids:
            p_str = ",".join("?" * len(req.selected_round_ids))
            cursor.execute(f"SELECT id FROM matches WHERE round_id IN ({p_str})", req.selected_round_ids)
            m_ids = [r[0] for r in cursor.fetchall()]
            if m_ids:
                mp_str = ",".join("?" * len(m_ids))
                cursor.execute(f"DELETE FROM speaker_scores WHERE scorecard_id IN (SELECT id FROM scorecards WHERE match_id IN ({mp_str}))", m_ids)
                cursor.execute(f"DELETE FROM scorecards WHERE match_id IN ({mp_str})", m_ids)
                cursor.execute(f"DELETE FROM judge_assignments WHERE match_id IN ({mp_str})", m_ids)
                cursor.execute(f"""
                    UPDATE matches
                    SET team1_aggregate = NULL, team2_aggregate = NULL, winner_id = NULL, tie_status = 'NONE', is_published = 0, status = 'SCHEDULED'
                    WHERE id IN ({mp_str})
                """, m_ids)
            cursor.execute(f"UPDATE rounds SET status = 'DRAFT' WHERE id IN ({p_str})", req.selected_round_ids)
            audit_actions.append(f"Reset rounds: {req.selected_round_ids}")
        else:
            # Reset all rounds
            cursor.execute("DELETE FROM speaker_scores")
            cursor.execute("DELETE FROM scorecards")
            cursor.execute("DELETE FROM judge_assignments")
            cursor.execute("UPDATE matches SET team1_aggregate = NULL, team2_aggregate = NULL, winner_id = NULL, tie_status = 'NONE', is_published = 0, status = 'SCHEDULED'")
            cursor.execute("UPDATE rounds SET status = 'DRAFT'")
            cursor.execute("UPDATE tournament SET status = 'SETUP', bracket_balance_score = NULL")
            audit_actions.append("Reset all tournament rounds and matches")

    # 3. JUDGING & SCORECARDS RESET
    if req.reset_judging:
        if req.selected_judge_ids:
            p_str = ",".join("?" * len(req.selected_judge_ids))
            cursor.execute(f"SELECT DISTINCT match_id FROM scorecards WHERE judge_id IN ({p_str})", req.selected_judge_ids)
            affected_match_ids = [r[0] for r in cursor.fetchall()]

            cursor.execute(f"DELETE FROM speaker_scores WHERE scorecard_id IN (SELECT id FROM scorecards WHERE judge_id IN ({p_str}))", req.selected_judge_ids)
            cursor.execute(f"DELETE FROM scorecards WHERE judge_id IN ({p_str})", req.selected_judge_ids)
            cursor.execute(f"DELETE FROM judge_assignments WHERE judge_id IN ({p_str})", req.selected_judge_ids)

            # Revert affected matches
            if affected_match_ids:
                mp_str = ",".join("?" * len(affected_match_ids))
                cursor.execute(f"""
                    UPDATE matches
                    SET team1_aggregate = NULL, team2_aggregate = NULL, winner_id = NULL, tie_status = 'NONE', is_published = 0, status = 'SCORING'
                    WHERE id IN ({mp_str})
                """, affected_match_ids)
            audit_actions.append(f"Reset ballots for judges: {req.selected_judge_ids}")
        else:
            cursor.execute("DELETE FROM speaker_scores")
            cursor.execute("DELETE FROM scorecards")
            cursor.execute("DELETE FROM judge_assignments")
            cursor.execute("UPDATE matches SET team1_aggregate = NULL, team2_aggregate = NULL, winner_id = NULL, tie_status = 'NONE', is_published = 0, status = 'SCHEDULED'")
            audit_actions.append("Reset all judging ballots and assignments")

    # 4. TEAMS RESET
    if req.reset_teams:
        cursor.execute("UPDATE teams SET custom_name = NULL, speaker1_id = NULL, speaker2_id = NULL, speaker3_id = NULL, leader_id = NULL, status = 'APPROVED', is_official = 0")
        audit_actions.append("Reset team custom names, rosters, and official status")

    # 5. MESSAGES RESET
    if req.reset_messages:
        cursor.execute("DELETE FROM judge_admin_messages")
        cursor.execute("DELETE FROM judge_notifications")
        audit_actions.append("Cleared all messages and judge notifications")

    # 6. SENIOR MATCH RESET
    if req.reset_senior:
        cursor.execute("""
            UPDATE senior_segment
            SET team1_score = 0.0, team2_score = 0.0, winner_team = '', is_published = 0, status = 'SCHEDULED'
            WHERE id = (SELECT id FROM senior_segment ORDER BY id ASC LIMIT 1)
        """)
        audit_actions.append("Reset senior master match scores")

    # 7. AUDIT RESET
    if req.reset_audit:
        cursor.execute("DELETE FROM audit_logs")
        audit_actions.append("Cleared audit log")

    if audit_actions and not req.reset_audit:
        log_audit(conn, admin["id"], admin["full_name"], "GRANULAR_RESET", "SYSTEM", 1, "; ".join(audit_actions))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "actions": audit_actions,
        "message": "Granular system reset executed successfully." if audit_actions else "No reset items selected."
    }

