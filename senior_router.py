import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.database import get_db, log_audit
from app.auth import require_admin, require_judge_or_admin, get_current_user_optional, get_current_user

router = APIRouter(prefix="/api/senior", tags=["Senior Master Segment"])

class SeniorTeamsRequest(BaseModel):
    team1_name: Optional[str] = None
    team2_name: Optional[str] = None
    team1_speaker1: Optional[str] = ""
    team1_speaker2: Optional[str] = ""
    team1_speaker3: Optional[str] = ""
    team2_speaker1: Optional[str] = ""
    team2_speaker2: Optional[str] = ""
    team2_speaker3: Optional[str] = ""
    team1_speakers: Optional[str] = ""
    team2_speakers: Optional[str] = ""
    team1_leader_id: Optional[int] = None
    team1_speaker1_id: Optional[int] = None
    team1_speaker2_id: Optional[int] = None
    team1_speaker3_id: Optional[int] = None
    team2_leader_id: Optional[int] = None
    team2_speaker1_id: Optional[int] = None
    team2_speaker2_id: Optional[int] = None
    team2_speaker3_id: Optional[int] = None
    chief_judge_id: Optional[int] = None
    panel_judge1_id: Optional[int] = None
    panel_judge2_id: Optional[int] = None
    adjudicators: Optional[str] = ""

class SeniorMotionRequest(BaseModel):
    motion: Optional[str] = ""
    motion_en: Optional[str] = ""
    motion_bn: Optional[str] = ""
    room_name: Optional[str] = "Central Auditorium"

class SeniorScoreRequest(BaseModel):
    team1_score: Optional[float] = None
    team2_score: Optional[float] = None
    winner_team: Optional[str] = ""
    winner_name: Optional[str] = ""

def fetch_user_detail(cursor, uid):
    if not uid:
        return None
    cursor.execute("SELECT id, full_name, username, whatsapp_number, role, school_organization, photo_url FROM users WHERE id = ?", (uid,))
    row = cursor.fetchone()
    return dict(row) if row else None

@router.get("/status")
def get_senior_status(user: dict = Depends(get_current_user_optional)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM senior_segment ORDER BY id ASC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO senior_segment (title, title_bn, team1_name, team2_name, status, created_at)
            VALUES ('Class 10 Master Championship', 'ক্লাস 10 মাস্টার বিতর্ক প্রতিযোগিতা 2026', 'Class 10 Master Team Alpha', 'Class 10 Master Team Beta', 'SCHEDULED', ?)
        """, (now_str,))
        conn.commit()
        cursor.execute("SELECT * FROM senior_segment ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()

    d = dict(row)

    # Fetch user objects for speakers
    u_t1_lead = fetch_user_detail(cursor, d.get("team1_leader_id"))
    u_t1_s1 = fetch_user_detail(cursor, d.get("team1_speaker1_id"))
    u_t1_s2 = fetch_user_detail(cursor, d.get("team1_speaker2_id"))
    u_t1_s3 = fetch_user_detail(cursor, d.get("team1_speaker3_id"))

    u_t2_lead = fetch_user_detail(cursor, d.get("team2_leader_id"))
    u_t2_s1 = fetch_user_detail(cursor, d.get("team2_speaker1_id"))
    u_t2_s2 = fetch_user_detail(cursor, d.get("team2_speaker2_id"))
    u_t2_s3 = fetch_user_detail(cursor, d.get("team2_speaker3_id"))

    # Fetch user objects for judges
    u_chief = fetch_user_detail(cursor, d.get("chief_judge_id"))
    u_pj1 = fetch_user_detail(cursor, d.get("panel_judge1_id"))
    u_pj2 = fetch_user_detail(cursor, d.get("panel_judge2_id"))

    conn.close()

    def make_spk_info(u, pos, fallback_name):
        full_name = u["full_name"] if u else (fallback_name or f"Speaker {pos}")
        phone = u.get("whatsapp_number", "") if u else ""
        return {
            "id": u["id"] if u else (8010 + pos),
            "position": pos,
            "name": full_name,
            "full_name": full_name,
            "username": u.get("username", "") if u else "",
            "phone": phone,
            "whatsapp_number": phone,
            "role_code": "1" if pos == 1 else ("2" if pos == 2 else "3"),
            "school_organization": u.get("school_organization", "") if u else "Class 10, HGHS",
            "photo_url": u.get("photo_url", "") if u else ""
        }

    t1_speakers_list = [
        make_spk_info(u_t1_s1, 1, d.get("team1_speaker1")),
        make_spk_info(u_t1_s2, 2, d.get("team1_speaker2")),
        make_spk_info(u_t1_s3, 3, d.get("team1_speaker3")),
    ]

    t2_speakers_list = [
        make_spk_info(u_t2_s1, 1, d.get("team2_speaker1")),
        make_spk_info(u_t2_s2, 2, d.get("team2_speaker2")),
        make_spk_info(u_t2_s3, 3, d.get("team2_speaker3")),
    ]

    d["team1_speaker1_phone"] = t1_speakers_list[0]["phone"]
    d["team1_speaker2_phone"] = t1_speakers_list[1]["phone"]
    d["team1_speaker3_phone"] = t1_speakers_list[2]["phone"]
    d["team2_speaker1_phone"] = t2_speakers_list[0]["phone"]
    d["team2_speaker2_phone"] = t2_speakers_list[1]["phone"]
    d["team2_speaker3_phone"] = t2_speakers_list[2]["phone"]

    d["team1_speaker1"] = t1_speakers_list[0]["name"]
    d["team1_speaker2"] = t1_speakers_list[1]["name"]
    d["team1_speaker3"] = t1_speakers_list[2]["name"]
    d["team2_speaker1"] = t2_speakers_list[0]["name"]
    d["team2_speaker2"] = t2_speakers_list[1]["name"]
    d["team2_speaker3"] = t2_speakers_list[2]["name"]

    d["team1_speakers_list"] = t1_speakers_list
    d["team2_speakers_list"] = t2_speakers_list
    d["team1_leader"] = u_t1_lead
    d["team2_leader"] = u_t2_lead

    d["chief_judge"] = u_chief
    d["panel_judges"] = [u for u in [u_pj1, u_pj2] if u]
    d["chief_judge_id"] = d.get("chief_judge_id")
    d["panel_judge1_id"] = d.get("panel_judge1_id")
    d["panel_judge2_id"] = d.get("panel_judge2_id")

    d["motion"] = d.get("motion_bn") or d.get("motion_en") or ""
    d["winner_name"] = d.get("winner_team") or ""
    d["adjudicators"] = (u_chief["full_name"] if u_chief else None) or d.get("room_name") or "Class 10 Senior Adjudicators Panel"
    spk1 = [d.get("team1_speaker1"), d.get("team1_speaker2"), d.get("team1_speaker3")]
    d["team1_speakers"] = ", ".join([s for s in spk1 if s])
    spk2 = [d.get("team2_speaker1"), d.get("team2_speaker2"), d.get("team2_speaker3")]
    d["team2_speakers"] = ", ".join([s for s in spk2 if s])

    cur_uid = user.get("id") if user else None
    cur_role = user.get("role") if user else None
    is_admin = cur_role == "ADMIN"
    can_edit_team1 = is_admin or bool(cur_uid and cur_uid == d.get("team1_leader_id"))
    can_edit_team2 = is_admin or bool(cur_uid and cur_uid == d.get("team2_leader_id"))
    can_configure = can_edit_team1 or can_edit_team2

    assigned_judge_ids = {d.get("chief_judge_id"), d.get("panel_judge1_id"), d.get("panel_judge2_id")} - {None}
    is_assigned_judge = bool(cur_uid and cur_uid in assigned_judge_ids)
    can_score = is_admin or is_assigned_judge

    return {
        "success": True,
        "segment": d,
        "senior": d,
        "can_configure": can_configure,
        "can_edit_team1": can_edit_team1,
        "can_edit_team2": can_edit_team2,
        "can_score": can_score,
        "is_assigned_judge": is_assigned_judge,
        "is_admin": is_admin
    }

@router.get("/eligible-speakers")
def get_eligible_senior_speakers(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, username, whatsapp_number, role, school_organization, photo_url
        FROM users
        WHERE role != 'ADMIN'
        ORDER BY full_name ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return {"eligible_speakers": [dict(r) for r in rows]}

@router.get("/eligible-judges")
def get_eligible_senior_judges(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, username, whatsapp_number, role, school_organization, photo_url
        FROM users
        WHERE role IN ('JUDGE', 'ADMIN')
        ORDER BY full_name ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return {"eligible_judges": [dict(r) for r in rows]}

@router.post("/save-teams")
def save_senior_teams(req: SeniorTeamsRequest, user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM senior_segment ORDER BY id ASC LIMIT 1")
    current_seg = cursor.fetchone()
    if not current_seg:
        conn.close()
        raise HTTPException(status_code=404, detail="Senior segment not found.")

    curr = dict(current_seg)
    is_admin = user.get("role") == "ADMIN"
    is_t1_leader = user.get("id") == curr.get("team1_leader_id")
    is_t2_leader = user.get("id") == curr.get("team2_leader_id")

    if not (is_admin or is_t1_leader or is_t2_leader):
        conn.close()
        raise HTTPException(
            status_code=403,
            detail="অনুমতি নেই: শুধুমাত্র ট্যাব পরিচালক বা সিনিয়র টিম লিডার দল কনফিগার করতে পারেন। (Forbidden: Only Tab Director or Senior Team Leaders can configure senior teams.)"
        )

    def get_user_name(uid):
        if not uid:
            return ""
        cursor.execute("SELECT full_name FROM users WHERE id = ?", (uid,))
        r = cursor.fetchone()
        return r[0] if r else ""

    updates = {}

    # TEAM 1
    if is_admin or is_t1_leader:
        if req.team1_name and req.team1_name.strip():
            updates["team1_name"] = req.team1_name.strip()
        
        if req.team1_speaker1_id is not None:
            updates["team1_speaker1_id"] = req.team1_speaker1_id
            nm = get_user_name(req.team1_speaker1_id)
            if nm: updates["team1_speaker1"] = nm
            if is_admin and req.team1_leader_id is None:
                updates["team1_leader_id"] = req.team1_speaker1_id

        if req.team1_speaker2_id is not None:
            updates["team1_speaker2_id"] = req.team1_speaker2_id
            nm = get_user_name(req.team1_speaker2_id)
            if nm: updates["team1_speaker2"] = nm

        if req.team1_speaker3_id is not None:
            updates["team1_speaker3_id"] = req.team1_speaker3_id
            nm = get_user_name(req.team1_speaker3_id)
            if nm: updates["team1_speaker3"] = nm

        if req.team1_leader_id is not None and is_admin:
            updates["team1_leader_id"] = req.team1_leader_id

        # Backward compatibility for text speaker inputs
        if req.team1_speaker1 and req.team1_speaker1_id is None:
            updates["team1_speaker1"] = req.team1_speaker1.strip()
        if req.team1_speaker2 and req.team1_speaker2_id is None:
            updates["team1_speaker2"] = req.team1_speaker2.strip()
        if req.team1_speaker3 and req.team1_speaker3_id is None:
            updates["team1_speaker3"] = req.team1_speaker3.strip()
        if req.team1_speakers:
            parts = [p.strip() for p in req.team1_speakers.split(",") if p.strip()]
            if len(parts) > 0 and req.team1_speaker1_id is None: updates["team1_speaker1"] = parts[0]
            if len(parts) > 1 and req.team1_speaker2_id is None: updates["team1_speaker2"] = parts[1]
            if len(parts) > 2 and req.team1_speaker3_id is None: updates["team1_speaker3"] = parts[2]

    # TEAM 2
    if is_admin or is_t2_leader:
        if req.team2_name and req.team2_name.strip():
            updates["team2_name"] = req.team2_name.strip()

        if req.team2_speaker1_id is not None:
            updates["team2_speaker1_id"] = req.team2_speaker1_id
            nm = get_user_name(req.team2_speaker1_id)
            if nm: updates["team2_speaker1"] = nm
            if is_admin and req.team2_leader_id is None:
                updates["team2_leader_id"] = req.team2_speaker1_id

        if req.team2_speaker2_id is not None:
            updates["team2_speaker2_id"] = req.team2_speaker2_id
            nm = get_user_name(req.team2_speaker2_id)
            if nm: updates["team2_speaker2"] = nm

        if req.team2_speaker3_id is not None:
            updates["team2_speaker3_id"] = req.team2_speaker3_id
            nm = get_user_name(req.team2_speaker3_id)
            if nm: updates["team2_speaker3"] = nm

        if req.team2_leader_id is not None and is_admin:
            updates["team2_leader_id"] = req.team2_leader_id

        # Backward compatibility for text speaker inputs
        if req.team2_speaker1 and req.team2_speaker1_id is None:
            updates["team2_speaker1"] = req.team2_speaker1.strip()
        if req.team2_speaker2 and req.team2_speaker2_id is None:
            updates["team2_speaker2"] = req.team2_speaker2.strip()
        if req.team2_speaker3 and req.team2_speaker3_id is None:
            updates["team2_speaker3"] = req.team2_speaker3.strip()
        if req.team2_speakers:
            parts = [p.strip() for p in req.team2_speakers.split(",") if p.strip()]
            if len(parts) > 0 and req.team2_speaker1_id is None: updates["team2_speaker1"] = parts[0]
            if len(parts) > 1 and req.team2_speaker2_id is None: updates["team2_speaker2"] = parts[1]
            if len(parts) > 2 and req.team2_speaker3_id is None: updates["team2_speaker3"] = parts[2]

    # JUDGES (Admin only)
    if is_admin:
        if req.chief_judge_id is not None:
            updates["chief_judge_id"] = req.chief_judge_id
            nm = get_user_name(req.chief_judge_id)
            if nm and not req.adjudicators:
                updates["room_name"] = nm
        if req.panel_judge1_id is not None:
            updates["panel_judge1_id"] = req.panel_judge1_id
        if req.panel_judge2_id is not None:
            updates["panel_judge2_id"] = req.panel_judge2_id

    if is_admin and req.adjudicators is not None:
        updates["room_name"] = req.adjudicators.strip()

    if updates:
        set_clauses = [f"{k} = ?" for k in updates.keys()]
        values = list(updates.values())
        values.append(curr["id"])
        cursor.execute(f"UPDATE senior_segment SET {', '.join(set_clauses)} WHERE id = ?", values)
        log_audit(conn, user["id"], user["full_name"], "UPDATE_SENIOR_TEAMS", "SENIOR_SEGMENT", curr["id"], f"Updated senior teams/judges: {list(updates.keys())}")
        conn.commit()

    conn.close()
    return {"success": True, "message": "Senior master configuration updated successfully."}

@router.post("/update-motion")
def update_senior_motion(req: SeniorMotionRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    m_en = req.motion_en or req.motion or ""
    m_bn = req.motion_bn or req.motion or ""
    cursor.execute("""
        UPDATE senior_segment
        SET motion_en = ?, motion_bn = ?, room_name = COALESCE(NULLIF(?, ''), room_name)
        WHERE id = (SELECT id FROM senior_segment ORDER BY id ASC LIMIT 1)
    """, (m_en.strip(), m_bn.strip(), (req.room_name or "").strip()))
    log_audit(conn, admin["id"], admin["full_name"], "UPDATE_SENIOR_MOTION", "SENIOR_SEGMENT", 1, f"Updated senior motion: {m_bn or m_en}")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Senior debate motion updated."}

@router.post("/score")
def score_senior_match(req: SeniorScoreRequest, user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT chief_judge_id, panel_judge1_id, panel_judge2_id FROM senior_segment ORDER BY id ASC LIMIT 1")
    seg = cursor.fetchone()
    is_admin = user.get("role") == "ADMIN"
    assigned_ids = {seg["chief_judge_id"], seg["panel_judge1_id"], seg["panel_judge2_id"]} if seg else set()
    if not is_admin and user.get("id") not in assigned_ids:
        conn.close()
        raise HTTPException(status_code=403, detail="অনুমতি নেই: শুধুমাত্র নিযুক্ত সিনিয়র বিচারক বা ট্যাব পরিচালক স্কোর দিতে পারেন। (Forbidden: Only assigned Senior Judge or Tab Director can score.)")

    winner = req.winner_name or req.winner_team or ""
    cursor.execute("""
        UPDATE senior_segment
        SET team1_score = ?, team2_score = ?, winner_team = ?, status = 'COMPLETED'
        WHERE id = (SELECT id FROM senior_segment ORDER BY id ASC LIMIT 1)
    """, (req.team1_score, req.team2_score, winner.strip()))
    log_audit(conn, user["id"], user["full_name"], "SCORE_SENIOR_MATCH", "SENIOR_SEGMENT", 1, f"Scored senior debate: {winner} won")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Senior match scored successfully."}

@router.post("/publish")
def publish_senior_match(user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE senior_segment
        SET is_published = 1, status = 'PUBLISHED'
        WHERE id = (SELECT id FROM senior_segment ORDER BY id ASC LIMIT 1)
    """, ())
    log_audit(conn, user["id"], user["full_name"], "PUBLISH_SENIOR_MATCH", "SENIOR_SEGMENT", 1, "Published senior master debate result.")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Senior master result published successfully."}

@router.post("/reset")
def reset_senior_match(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE senior_segment
        SET team1_score = 0.0, team2_score = 0.0, winner_team = '', is_published = 0, status = 'SCHEDULED'
        WHERE id = (SELECT id FROM senior_segment ORDER BY id ASC LIMIT 1)
    """, ())
    log_audit(conn, admin["id"], admin["full_name"], "RESET_SENIOR_MATCH", "SENIOR_SEGMENT", 1, "Reset senior master debate.")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Senior debate reset to scheduled state."}
