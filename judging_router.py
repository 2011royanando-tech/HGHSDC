import datetime
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db, log_audit
from app.auth import get_current_user, require_admin, require_judge_or_admin
from app.models import JudgeAssignRequest

router = APIRouter(prefix="/api/judging", tags=["Judging & Assignments"])

@router.get("/judges")
def list_judges(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, school_organization, role_status
        FROM users
        WHERE role = 'JUDGE' OR (applied_role = 'JUDGE' AND role_status = 'APPROVED')
        ORDER BY full_name ASC
    """)
    judges = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"judges": judges}

@router.get("/assignments/{match_id}")
def get_match_judges(match_id: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.full_name, u.school_organization
        FROM judge_assignments ja
        JOIN users u ON ja.judge_id = u.id
        WHERE ja.match_id = ?
    """, (match_id,))
    rows = cursor.fetchall()
    conn.close()
    return {"assigned_judges": [dict(r) for r in rows]}

@router.post("/check-clashes")
def check_clashes(req: JudgeAssignRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.team1_id, m.team2_id,
               t1.name AS team1_name, t1.school_organization AS team1_school,
               t1.leader_id AS t1_leader, t1.speaker1_id AS t1_s1, t1.speaker2_id AS t1_s2, t1.speaker3_id AS t1_s3,
               t2.name AS team2_name, t2.school_organization AS team2_school,
               t2.leader_id AS t2_leader, t2.speaker1_id AS t2_s1, t2.speaker2_id AS t2_s2, t2.speaker3_id AS t2_s3
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        WHERE m.id = ?
    """, (req.match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    team_schools = set()
    if match["team1_school"]:
        team_schools.add(match["team1_school"].strip().lower())
    if match["team2_school"]:
        team_schools.add(match["team2_school"].strip().lower())

    t1_members = {match["t1_leader"], match["t1_s1"], match["t1_s2"], match["t1_s3"]} - {None}
    t2_members = {match["t2_leader"], match["t2_s1"], match["t2_s2"], match["t2_s3"]} - {None}

    clashes = []
    for j_id in req.judge_ids:
        cursor.execute("SELECT id, full_name, school_organization FROM users WHERE id = ?", (j_id,))
        judge = cursor.fetchone()
        if not judge:
            continue

        if j_id in t1_members or j_id in t2_members:
            comp_team = match["team1_name"] if j_id in t1_members else match["team2_name"]
            clashes.append({
                "judge_id": j_id,
                "judge_name": judge["full_name"],
                "is_personal_conflict": True,
                "reason": f"ব্যক্তিগত সংঘাত (Direct Conflict): বিচারক '{judge['full_name']}' প্রতিযোগী দল '{comp_team}'-এর সক্রিয় সদস্য/দলনেতা।"
            })
            continue

        j_school = (judge["school_organization"] or "").strip().lower()
        if j_school and j_school in team_schools:
            matched_team = match["team1_name"] if j_school == (match["team1_school"] or "").strip().lower() else match["team2_name"]
            clashes.append({
                "judge_id": j_id,
                "judge_name": judge["full_name"],
                "is_personal_conflict": False,
                "reason": f"Institutional clash: Judge belongs to '{judge['school_organization']}', which matches competing team '{matched_team}'."
            })

    conn.close()
    return {"has_clashes": len(clashes) > 0, "clashes": clashes}

@router.post("/assign")
def assign_judges(req: JudgeAssignRequest, admin: dict = Depends(require_admin)):
    # Up to 3 judges (highest 3)
    if len(req.judge_ids) > 3 or len(req.judge_ids) < 1:
        raise HTTPException(status_code=400, detail="Each match can have at most 3 assigned judges (1 to 3).")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.id, m.match_number, m.team1_id, m.team2_id,
               t1.name AS team1_name, t1.school_organization AS team1_school,
               t1.leader_id AS t1_leader, t1.speaker1_id AS t1_s1, t1.speaker2_id AS t1_s2, t1.speaker3_id AS t1_s3,
               t2.name AS team2_name, t2.school_organization AS team2_school,
               t2.leader_id AS t2_leader, t2.speaker1_id AS t2_s1, t2.speaker2_id AS t2_s2, t2.speaker3_id AS t2_s3,
               rm.name AS room_name
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN rooms rm ON m.room_id = rm.id
        WHERE m.id = ?
    """, (req.match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    # Collect team member IDs for personal conflict detection
    t1_members = {match["t1_leader"], match["t1_s1"], match["t1_s2"], match["t1_s3"]} - {None}
    t2_members = {match["t2_leader"], match["t2_s1"], match["t2_s2"], match["t2_s3"]} - {None}

    team_schools = set()
    if match["team1_school"]:
        team_schools.add(match["team1_school"].strip().lower())
    if match["team2_school"]:
        team_schools.add(match["team2_school"].strip().lower())

    personal_conflicts = []
    institutional_clashes = []
    for j_id in req.judge_ids:
        cursor.execute("SELECT id, full_name, school_organization FROM users WHERE id = ?", (j_id,))
        judge = cursor.fetchone()
        if not judge:
            continue

        # HARD BLOCK: Personal conflict — judge is a debater or leader of either competing team
        if j_id in t1_members or j_id in t2_members:
            comp_team = match["team1_name"] if j_id in t1_members else match["team2_name"]
            personal_conflicts.append(f"বিচারক '{judge['full_name']}' প্রতিযোগী দল '{comp_team}'-এর সক্রিয় সদস্য/দলনেতা।")
            continue

        # SOFT BLOCK: Institutional clash (can be overridden)
        j_school = (judge["school_organization"] or "").strip().lower()
        if j_school and j_school in team_schools:
            institutional_clashes.append(f"Judge {judge['full_name']} belongs to '{judge['school_organization']}'")

    # Personal conflicts are never overridable
    if personal_conflicts:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"ব্যক্তিগত সংঘাত (Direct Conflict): {'; '.join(personal_conflicts)} — এই নিয়োগ সম্পূর্ণরূপে নিষিদ্ধ।"
        )

    if institutional_clashes and not req.override_clashes:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"Clash Warning: {', '.join(institutional_clashes)}. Please adjust judges or set override_clashes=True."
        )

    # Save assignments
    cursor.execute("DELETE FROM judge_assignments WHERE match_id = ?", (req.match_id,))
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t1_name = match["team1_name"] or "Team 1"
    t2_name = match["team2_name"] or "Team 2"
    room_name = match["room_name"] or "Main Room"

    for j_id in req.judge_ids:
        cursor.execute("INSERT INTO judge_assignments (match_id, judge_id, created_at) VALUES (?, ?, ?)",
                       (req.match_id, j_id, now_str))
        # Insert congratulatory notification
        notif_msg = f"Congratulations! You have been appointed as an official adjudicator for Match {match['match_number']}: {t1_name} vs {t2_name} ({room_name})."
        cursor.execute("""
            INSERT INTO judge_notifications (judge_id, match_id, message, is_read, created_at)
            VALUES (?, ?, ?, 0, ?)
        """, (j_id, req.match_id, notif_msg, now_str))

    log_audit(conn, admin["id"], admin["full_name"], "ASSIGN_JUDGES", "MATCH", req.match_id,
              f"Assigned {len(req.judge_ids)} judges to match {req.match_id} (Override: {req.override_clashes})")
    conn.commit()
    conn.close()

    return {"success": True, "message": f"{len(req.judge_ids)} judge(s) assigned successfully. Notifications delivered."}

@router.get("/notifications")
def get_judge_notifications(user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, match_id, message, is_read, created_at
        FROM judge_notifications
        WHERE judge_id = ?
        ORDER BY id DESC
        LIMIT 10
    """, (user["id"],))
    notifs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"notifications": notifs}

@router.post("/notifications/{notif_id}/read")
def mark_notification_read(notif_id: int, user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE judge_notifications SET is_read = 1 WHERE id = ? AND judge_id = ?", (notif_id, user["id"]))
    conn.commit()
    conn.close()
    return {"success": True}

@router.post("/rounds/{round_number}/start")
def start_round(round_number: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, status, motion_en, motion_bn FROM rounds WHERE round_number = ?", (round_number,))
    rnd = cursor.fetchone()
    if not rnd:
        conn.close()
        raise HTTPException(status_code=404, detail="Round not found.")

    # 1. CRITICAL LOGIC: Round Motion must be defined!
    motion_en = (rnd["motion_en"] or "").strip()
    motion_bn = (rnd["motion_bn"] or "").strip()
    if not motion_en and not motion_bn:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="লজিক ত্রুটি: রাউন্ডের কোনো মোশন (বিতর্কের প্রস্তাবনা) নির্ধারণ করা হয়নি! অনুগ্রহ করে 'Rounds & Motions' ট্যাবে গিয়ে বিষয় ইনপুট দিন।"
        )

    # 2. CRITICAL LOGIC: Check matches & team assignments in this round
    cursor.execute("SELECT id, match_number, team1_id, team2_id FROM matches WHERE round_id = ?", (rnd["id"],))
    matches = cursor.fetchall()
    if not matches:
        conn.close()
        raise HTTPException(status_code=400, detail="এই রাউন্ডে কোনো ম্যাচ তৈরি হয়নি। আগে ব্র্যাকেট লক/তৈরি করুন।")

    for m in matches:
        if not m["team1_id"] or not m["team2_id"]:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"লজিক ত্রুটি: ম্যাচ #{m['match_number']} এ দল নির্ধারিত নেই! আগের রাউন্ড শেষ করে বিজয়ী নির্ধারণ করুন অথবা ব্র্যাকেটে দল নির্ধারণ করুন।"
            )

    # 3. CRITICAL LOGIC: Check judge assignments for all matches in this round
    cursor.execute("""
        SELECT m.match_number, COUNT(ja.id) as judge_count
        FROM matches m
        LEFT JOIN judge_assignments ja ON ja.match_id = m.id
        WHERE m.round_id = ?
        GROUP BY m.id
    """, (rnd["id"],))
    unassigned = [str(r["match_number"]) for r in cursor.fetchall() if r["judge_count"] == 0]
    if unassigned:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"লজিক ত্রুটি: ম্যাচ {', '.join(unassigned)} এ কোনো বিচারক নিয়োগ করা হয়নি! রাউন্ড শুরু করার পূর্বে বিচারক নির্ধারণ করুন।"
        )

    if round_number > 1:
        cursor.execute("SELECT status FROM rounds WHERE round_number = ?", (round_number - 1,))
        prev_rnd = cursor.fetchone()
        if not prev_rnd or prev_rnd["status"] not in ("COMPLETED", "PUBLISHED", "RESULT_READY"):
            conn.close()
            raise HTTPException(status_code=400, detail=f"Previous round {round_number - 1} must be completed before starting this round.")

    cursor.execute("UPDATE rounds SET status = 'STARTED' WHERE id = ?", (rnd["id"],))
    cursor.execute("UPDATE matches SET status = 'LIVE' WHERE round_id = ? AND status != 'COMPLETED'", (rnd["id"],))
    cursor.execute("UPDATE tournament SET status = 'IN_PROGRESS' WHERE status = 'BRACKET_LOCKED'")

    log_audit(conn, admin["id"], admin["full_name"], "START_ROUND", "ROUND", round_number,
              f"Round {round_number} officially started. Judging access activated.")
    conn.commit()
    conn.close()

    return {"success": True, "message": f"Round {round_number} is now LIVE. Judging access has been unlocked for assigned judges."}

@router.post("/rounds/{round_number}/undo-start")
def undo_start_round(round_number: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, status FROM rounds WHERE round_number = ?", (round_number,))
    rnd = cursor.fetchone()
    if not rnd:
        conn.close()
        raise HTTPException(status_code=404, detail="Round not found.")

    prev_status = "READY" if round_number == 1 else "DRAFT"
    cursor.execute("UPDATE rounds SET status = ? WHERE id = ?", (prev_status, rnd["id"]))
    cursor.execute("UPDATE matches SET status = 'READY' WHERE round_id = ? AND status = 'LIVE'", (rnd["id"],))

    log_audit(conn, admin["id"], admin["full_name"], "UNDO_START_ROUND", "ROUND", round_number,
              f"Admin undid start for Round {round_number}. Match statuses reverted to READY.")
    conn.commit()
    conn.close()

    return {"success": True, "message": f"Round {round_number} start undone. Status reverted to {prev_status}."}

@router.post("/matches/{match_id}/undo-start")
def undo_start_match(match_id: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, match_number, round_id, status FROM matches WHERE id = ?", (match_id,))
    m = cursor.fetchone()
    if not m:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    cursor.execute("UPDATE matches SET status = 'READY' WHERE id = ?", (match_id,))

    log_audit(conn, admin["id"], admin["full_name"], "UNDO_START_MATCH", "MATCH", match_id,
              f"Admin undid start for Match {m['match_number']}. Status reverted to READY.")
    conn.commit()
    conn.close()

    return {"success": True, "message": f"Match {m['match_number']} start undone. Status reverted to READY."}

@router.get("/my-assignment")
def get_my_judge_assignment(user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()

    # Find matches assigned to this judge in currently active/started rounds
    cursor.execute("""
        SELECT m.id, m.round_id, m.match_number, m.bracket_position, m.half,
               m.team1_id, m.team2_id, m.room_id, m.status AS match_status,
               r.name AS round_name, r.round_number, r.status AS round_status,
               r.motion_en, r.motion_bn, r.prep_time_minutes, r.speaking_time_seconds,
               rm.name AS room_name,
               t1.name AS team1_name, t1.custom_name AS team1_custom_name, t1.seed_number AS team1_seed, t1.status AS team1_status, t1.school_organization AS team1_school,
               t2.name AS team2_name, t2.custom_name AS team2_custom_name, t2.seed_number AS team2_seed, t2.status AS team2_status, t2.school_organization AS team2_school
        FROM judge_assignments ja
        JOIN matches m ON ja.match_id = m.id
        JOIN rounds r ON m.round_id = r.id
        LEFT JOIN rooms rm ON m.room_id = rm.id
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        WHERE ja.judge_id = ? AND r.status IN ('STARTED', 'SCORING', 'REVIEW')
        ORDER BY r.round_number ASC, m.match_number ASC
        LIMIT 1
    """, (user["id"],))
    row = cursor.fetchone()

    # If user is ADMIN and no judge assignment, allow Admin to pick any active match to score!
    if not row and user.get("role") == "ADMIN":
        cursor.execute("""
            SELECT m.id, m.round_id, m.match_number, m.bracket_position, m.half,
                   m.team1_id, m.team2_id, m.room_id, m.status AS match_status,
                   r.name AS round_name, r.round_number, r.status AS round_status,
                   r.motion_en, r.motion_bn, r.prep_time_minutes, r.speaking_time_seconds,
                   rm.name AS room_name,
                   t1.name AS team1_name, t1.custom_name AS team1_custom_name, t1.seed_number AS team1_seed, t1.status AS team1_status, t1.school_organization AS team1_school,
                   t2.name AS team2_name, t2.custom_name AS team2_custom_name, t2.seed_number AS team2_seed, t2.status AS team2_status, t2.school_organization AS team2_school
            FROM matches m
            JOIN rounds r ON m.round_id = r.id
            LEFT JOIN rooms rm ON m.room_id = rm.id
            LEFT JOIN teams t1 ON m.team1_id = t1.id
            LEFT JOIN teams t2 ON m.team2_id = t2.id
            WHERE r.status IN ('STARTED', 'SCORING', 'REVIEW', 'READY')
            ORDER BY m.match_number ASC
            LIMIT 1
        """)
        row = cursor.fetchone()

    if not row:
        cursor.execute("""
            SELECT r.name, r.round_number, r.status
            FROM judge_assignments ja
            JOIN matches m ON ja.match_id = m.id
            JOIN rounds r ON m.round_id = r.id
            WHERE ja.judge_id = ? AND r.status != 'COMPLETED'
            LIMIT 1
        """, (user["id"],))
        pending_rnd = cursor.fetchone()
        conn.close()
        if pending_rnd:
            return {
                "active": False,
                "locked": True,
                "message": f"Judging access is currently inactive. Round '{pending_rnd['name']}' has not been started by Admin yet."
            }
        return {
            "active": False,
            "locked": False,
            "message": "Judging access is currently inactive. You have no pending match assignments."
        }

    match_info = dict(row)

    def get_speakers(t_id):
        if not t_id:
            return []
        cursor.execute("""
            SELECT t.speaker1_id, u1.full_name AS speaker1_name, u1.whatsapp_number AS speaker1_phone, u1.photo_url AS speaker1_photo, t.speaker1_name_custom,
                   t.speaker2_id, u2.full_name AS speaker2_name, u2.whatsapp_number AS speaker2_phone, u2.photo_url AS speaker2_photo, t.speaker2_name_custom,
                   t.speaker3_id, u3.full_name AS speaker3_name, u3.whatsapp_number AS speaker3_phone, u3.photo_url AS speaker3_photo, t.speaker3_name_custom,
                   t.leader_id, ul.full_name AS leader_name, ul.whatsapp_number AS leader_phone, ul.photo_url AS leader_photo
            FROM teams t
            LEFT JOIN users u1 ON t.speaker1_id = u1.id
            LEFT JOIN users u2 ON t.speaker2_id = u2.id
            LEFT JOIN users u3 ON t.speaker3_id = u3.id
            LEFT JOIN users ul ON t.leader_id = ul.id
            WHERE t.id = ?
        """, (t_id,))
        t_row = cursor.fetchone()
        if not t_row:
            return []
        sp1 = t_row["speaker1_name"] or t_row["speaker1_name_custom"] or "Speaker 1"
        sp2 = t_row["speaker2_name"] or t_row["speaker2_name_custom"] or "Speaker 2"
        sp3 = t_row["speaker3_name"] or t_row["speaker3_name_custom"] or "Speaker 3"
        
        is_sp1_leader = (t_row["leader_id"] and t_row["leader_id"] == t_row["speaker1_id"])
        is_sp2_leader = (t_row["leader_id"] and t_row["leader_id"] == t_row["speaker2_id"])
        is_sp3_leader = (t_row["leader_id"] and t_row["leader_id"] == t_row["speaker3_id"])
        
        lead_phone = t_row["leader_phone"] or ""
        return [
            {"position": 1, "role_code": "L" if is_sp1_leader else "1", "id": t_row["speaker1_id"], "name": sp1, "phone": t_row["speaker1_phone"] or lead_phone, "photo_url": t_row["speaker1_photo"] or ""},
            {"position": 2, "role_code": "L" if is_sp2_leader else "2", "id": t_row["speaker2_id"], "name": sp2, "phone": t_row["speaker2_phone"] or lead_phone, "photo_url": t_row["speaker2_photo"] or ""},
            {"position": 3, "role_code": "L" if is_sp3_leader else "3", "id": t_row["speaker3_id"], "name": sp3, "phone": t_row["speaker3_phone"] or lead_phone, "photo_url": t_row["speaker3_photo"] or ""}
        ]

    team1_speakers = get_speakers(match_info["team1_id"])
    team2_speakers = get_speakers(match_info["team2_id"])

    # Fetch or create scorecard for this judge
    cursor.execute("""
        SELECT id, status, team1_total, team2_total, tie_choice_team_id
        FROM scorecards
        WHERE match_id = ? AND judge_id = ?
    """, (match_info["id"], user["id"]))
    sc_row = cursor.fetchone()

    scorecard_id = None
    scorecard_status = "DRAFT"
    if sc_row:
        scorecard_id = sc_row["id"]
        scorecard_status = sc_row["status"]
    else:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO scorecards (match_id, judge_id, status, created_at)
            VALUES (?, ?, 'DRAFT', ?)
        """, (match_info["id"], user["id"], now_str))
        scorecard_id = cursor.lastrowid
        conn.commit()

        default_criteria = [
            ("Logic & Arguments", "যুক্তি ও তথ্য", 30.0),
            ("Facts & Evidence", "উপাত্ত ও প্রমাণ", 25.0),
            ("Style & Delivery", "উপস্থাপন ও বাচনভঙ্গি", 25.0),
            ("Language & Voice", "ভাষা ও উচ্চারণ", 20.0)
        ]
        for idx, (en, bn, max_m) in enumerate(default_criteria):
            cursor.execute("""
                INSERT INTO score_criteria (scorecard_id, name, name_bn, max_marks, sort_order)
                VALUES (?, ?, ?, ?, ?)
            """, (scorecard_id, en, bn, max_m, idx))
        conn.commit()

    conn.close()

    return {
        "active": True,
        "match": match_info,
        "scorecard_id": scorecard_id,
        "scorecard_status": scorecard_status,
        "team1_speakers": team1_speakers,
        "team2_speakers": team2_speakers
    }
