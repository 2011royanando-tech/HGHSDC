import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from app.database import get_db, log_audit
from app.auth import get_current_user, require_admin, require_leader_or_admin
from app.models import TeamCreateRequest, TeamApplyRequest, TeamApprovalRequest, TeamRatingRequest, TeamSelectOfficialRequest, TeamOfficialToggleRequest

router = APIRouter(prefix="/api/teams", tags=["Teams"])

class AdminSaveTeamRequest(BaseModel):
    id: Optional[int] = None
    name: str
    custom_name: Optional[str] = ""
    photo_url: Optional[str] = ""
    school_organization: Optional[str] = "HGHSDC (Habiganj Govt. High School)"
    leader_id: Optional[int] = None
    speaker1_id: Optional[int] = None
    speaker2_id: Optional[int] = None
    speaker3_id: Optional[int] = None
    speaker1_name_custom: Optional[str] = ""
    speaker2_name_custom: Optional[str] = ""
    speaker3_name_custom: Optional[str] = ""
    rating: str = "B"
    is_official: int = 1
    status: str = "APPROVED"

class ReorderSpeakersRequest(BaseModel):
    team_id: int
    speaker1_id: Optional[int] = None
    speaker2_id: Optional[int] = None
    speaker3_id: Optional[int] = None

def _validate_speaker_uniqueness(cursor, team_id: Optional[int], speaker_ids: List[Optional[int]], leader_id: Optional[int] = None):
    """
    CRITICAL BUSINESS & INTEGRITY LOGIC:
    1. A member cannot be assigned twice as speakers within the same team.
    2. A member cannot belong to multiple teams (neither as speaker nor as leader).
    3. A team leader cannot serve as a debater or leader in another team.
    """
    valid_ids = [sid for sid in speaker_ids if sid is not None]
    
    # Check duplicates within speakers in the same team
    if valid_ids and len(valid_ids) != len(set(valid_ids)):
        raise HTTPException(
            status_code=400,
            detail="একই সদস্যকে একই দলে একাধিক স্পিকার পদে নির্বাচন করা যাবে না। (A member cannot be selected multiple times in the same team.)"
        )

    all_check_ids = list(set(valid_ids + ([leader_id] if leader_id else [])))
    if not all_check_ids:
        return

    placeholders = ",".join("?" for _ in all_check_ids)
    query = f"""
        SELECT t.id, t.name, u.full_name,
               CASE
                 WHEN t.leader_id = u.id THEN 'দলনেতা (Leader)'
                 ELSE 'বিতার্কিক (Speaker)'
               END as role_title
        FROM teams t
        JOIN users u ON (u.id = t.leader_id OR u.id = t.speaker1_id OR u.id = t.speaker2_id OR u.id = t.speaker3_id)
        WHERE (t.leader_id IN ({placeholders}) OR t.speaker1_id IN ({placeholders}) OR t.speaker2_id IN ({placeholders}) OR t.speaker3_id IN ({placeholders}))
          AND t.status != 'REJECTED'
    """
    params = all_check_ids * 4
    if team_id:
        query += " AND t.id != ?"
        params.append(team_id)

    cursor.execute(query, params)
    conflict = cursor.fetchone()
    if conflict:
        t_name = conflict["name"]
        u_name = conflict["full_name"]
        r_title = conflict["role_title"]
        raise HTTPException(
            status_code=400,
            detail=f"সদস্য '{u_name}' ইতিমধ্যে '{t_name}' দলে {r_title} হিসেবে অন্তর্ভুক্ত আছেন। এক সদস্য একাধিক দলে অংশগ্রহণ করতে পারবে না।"
        )

@router.get("")
def list_teams(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.name, t.custom_name, t.school_organization, t.photo_url, t.leader_id, t.speaker1_id, t.speaker2_id, t.speaker3_id,
               t.speaker1_name_custom, t.speaker2_name_custom, t.speaker3_name_custom,
               t.status, t.rating, t.is_official, t.seed_number, t.created_at,
               u_lead.full_name AS leader_name, u_lead.whatsapp_number AS leader_phone,
               COALESCE(NULLIF(t.speaker1_name_custom, ''), u_s1.full_name, '') AS speaker1_name,
               COALESCE(u_s1.whatsapp_number, u_lead.whatsapp_number, '') AS speaker1_phone,
               COALESCE(NULLIF(t.speaker2_name_custom, ''), u_s2.full_name, '') AS speaker2_name,
               COALESCE(u_s2.whatsapp_number, u_lead.whatsapp_number, '') AS speaker2_phone,
               COALESCE(NULLIF(t.speaker3_name_custom, ''), u_s3.full_name, '') AS speaker3_name,
               COALESCE(u_s3.whatsapp_number, u_lead.whatsapp_number, '') AS speaker3_phone
        FROM teams t
        LEFT JOIN users u_lead ON t.leader_id = u_lead.id
        LEFT JOIN users u_s1 ON t.speaker1_id = u_s1.id
        LEFT JOIN users u_s2 ON t.speaker2_id = u_s2.id
        LEFT JOIN users u_s3 ON t.speaker3_id = u_s3.id
        ORDER BY COALESCE(t.seed_number, t.id) ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    is_admin = user.get("role") == "ADMIN"
    results = []
    for r in rows:
        item = {
            "id": r["id"],
            "name": r["name"],
            "custom_name": r["custom_name"] or "",
            "school_organization": r["school_organization"] or "HGHSDC (Habiganj Govt. High School)",
            "photo_url": r["photo_url"] or "",
            "leader_id": r["leader_id"],
            "leader_name": r["leader_name"],
            "leader_phone": r["leader_phone"],
            "speaker1_id": r["speaker1_id"],
            "speaker1_name": r["speaker1_name"],
            "speaker1_phone": r["speaker1_phone"],
            "speaker1_name_custom": r["speaker1_name_custom"],
            "speaker2_id": r["speaker2_id"],
            "speaker2_name": r["speaker2_name"],
            "speaker2_phone": r["speaker2_phone"],
            "speaker2_name_custom": r["speaker2_name_custom"],
            "speaker3_id": r["speaker3_id"],
            "speaker3_name": r["speaker3_name"],
            "speaker3_phone": r["speaker3_phone"],
            "speaker3_name_custom": r["speaker3_name_custom"],
            "status": r["status"],
            "is_official": r["is_official"],
            "seed_number": r["seed_number"],
            "created_at": r["created_at"]
        }
        if is_admin:
            item["rating"] = r["rating"]
        results.append(item)

    return {"teams": results}

@router.get("/available-for-leader")
def get_available_teams_for_leader(user: dict = Depends(require_leader_or_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.name, t.school_organization, t.leader_id, t.seed_number, t.status, t.rating,
               t.speaker1_id, t.speaker2_id, t.speaker3_id,
               u_lead.full_name AS leader_name
        FROM teams t
        LEFT JOIN users u_lead ON t.leader_id = u_lead.id
        ORDER BY COALESCE(t.seed_number, t.id) ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return {"available_teams": [dict(r) for r in rows]}

@router.post("/reorder-speakers")
def reorder_speakers(req: ReorderSpeakersRequest, user: dict = Depends(require_leader_or_admin)):
    """Allows Team Leader or Tab Director to interchange speaker positions."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, leader_id, speaker1_id, speaker2_id, speaker3_id FROM teams WHERE id = ?", (req.team_id,))
    team = cursor.fetchone()
    if not team:
        conn.close()
        raise HTTPException(status_code=404, detail="Team not found.")

    if user.get("role") != "ADMIN" and team["leader_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Only the assigned Team Leader or Tab Director can reorder speakers.")

    # Validate that the reordered IDs match the existing team's speakers
    current_ids = {team["speaker1_id"], team["speaker2_id"], team["speaker3_id"]} - {None}
    new_ids = {req.speaker1_id, req.speaker2_id, req.speaker3_id} - {None}

    if user.get("role") != "ADMIN" and current_ids != new_ids:
        conn.close()
        raise HTTPException(status_code=400, detail="Speakers can only be interchanged among existing team members.")

    cursor.execute("""
        UPDATE teams
        SET speaker1_id = ?, speaker2_id = ?, speaker3_id = ?
        WHERE id = ?
    """, (req.speaker1_id, req.speaker2_id, req.speaker3_id, req.team_id))

    log_audit(conn, user["id"], user["full_name"], "REORDER_SPEAKERS", "TEAM", req.team_id,
              f"Interchanged speakers for {team['name']}", previous_data={"speaker1_id": team["speaker1_id"], "speaker2_id": team["speaker2_id"], "speaker3_id": team["speaker3_id"]})
    conn.commit()
    conn.close()
    return {"success": True, "message": "স্পিকার পজিশন সফলভাবে পরিবর্তন করা হয়েছে। (Speaker positions updated successfully.)"}

@router.post("/apply")
def submit_team_form(req: TeamApplyRequest, leader: dict = Depends(require_leader_or_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, custom_name, status, leader_id, seed_number FROM teams WHERE id = ?", (req.team_id,))
    team = cursor.fetchone()
    if not team:
        conn.close()
        raise HTTPException(status_code=404, detail="Selected team slot not found.")

    if team["leader_id"] and team["leader_id"] != leader["id"] and leader.get("role") != "ADMIN":
        conn.close()
        raise HTTPException(status_code=403, detail="This team slot is already assigned to another team leader.")

    # Determine custom team name if provided
    raw_name = (req.custom_name or req.name or "").strip()
    slot_name = f"Team {team['seed_number']}" if team["seed_number"] else team["name"]

    # If user provided a custom name that is not just the default slot name
    if raw_name and raw_name.lower() != slot_name.lower():
        custom_name = raw_name
    else:
        custom_name = ""

    # Ensure no other team has the exact same custom name
    if custom_name:
        cursor.execute("SELECT id FROM teams WHERE LOWER(custom_name) = LOWER(?) AND id != ?", (custom_name, req.team_id))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="এই নামে ইতিমধ্যে আরেকটি দল রয়েছে। অন্য নাম বেছে নিন।")

    # Check that speakers are not in multiple teams
    speakers = [req.speaker1_id, req.speaker2_id, req.speaker3_id]
    valid_speakers = [s for s in speakers if s]
    if len(valid_speakers) < 1:
        raise HTTPException(status_code=400, detail="কমপক্ষে একজন সদস্য নির্বাচন করতে হবে।")
    _validate_speaker_uniqueness(cursor, req.team_id, valid_speakers, leader["id"])

    # Update team slot name, custom_name, leader, speakers and approve
    cursor.execute("""
        UPDATE teams
        SET name = ?, custom_name = ?, leader_id = ?, speaker1_id = ?, speaker2_id = ?, speaker3_id = ?, status = 'APPROVED', is_official = 1
        WHERE id = ?
    """, (slot_name, custom_name, leader["id"], req.speaker1_id, req.speaker2_id, req.speaker3_id, req.team_id))

    display_name = f"{slot_name} ({custom_name})" if custom_name else slot_name
    log_audit(conn, leader["id"], leader["full_name"], "TEAM_APPLY", "TEAM", req.team_id,
              f"Team roster updated: '{display_name}' (Slot {team['seed_number']})")
    conn.commit()
    conn.close()

    return {
        "success": True,
        "team_id": req.team_id,
        "team_name": slot_name,
        "custom_name": custom_name,
        "message": f"দলের নাম '{display_name}' এবং রোস্টার সফলভাবে সংরক্ষিত হয়েছে।"
    }

@router.post("/approve")
def approve_or_reject_team(req: TeamApprovalRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, status, speaker1_id, speaker2_id, speaker3_id FROM teams WHERE id = ?", (req.team_id,))
    team = cursor.fetchone()
    if not team:
        conn.close()
        raise HTTPException(status_code=404, detail="Team not found.")

    new_status = "APPROVED" if req.status.upper() == "APPROVED" else "REJECTED"
    is_official = 1 if new_status == "APPROVED" else 0

    if new_status == "APPROVED":
        # Make sure speaker uniqueness is strictly preserved
        speakers = [team["speaker1_id"], team["speaker2_id"], team["speaker3_id"]]
        _validate_speaker_uniqueness(cursor, req.team_id, speakers)

    cursor.execute("""
        UPDATE teams
        SET status = ?, is_official = ?
        WHERE id = ?
    """, (new_status, is_official, req.team_id))

    log_audit(conn, admin["id"], admin["full_name"], f"TEAM_{new_status}", "TEAM", req.team_id,
              f"Team {team['name']} set to {new_status}", previous_data={"old_status": team["status"]})
    conn.commit()
    conn.close()

    return {"success": True, "status": new_status, "team_id": req.team_id}

@router.post("/rating")
def set_team_rating(req: TeamRatingRequest, admin: dict = Depends(require_admin)):
    rating = req.rating.upper()
    if rating not in ("A", "B", "C"):
        raise HTTPException(status_code=400, detail="Rating must be A, B, or C.")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, rating FROM teams WHERE id = ?", (req.team_id,))
    team = cursor.fetchone()
    if not team:
        conn.close()
        raise HTTPException(status_code=404, detail="Team not found.")

    old_rating = team["rating"]
    cursor.execute("UPDATE teams SET rating = ? WHERE id = ?", (rating, req.team_id))
    log_audit(conn, admin["id"], admin["full_name"], "TEAM_RATING_CHANGE", "TEAM", req.team_id,
              f"Changed rating of {team['name']} from {old_rating} to {rating}", previous_data={"old_rating": old_rating})
    conn.commit()
    conn.close()

    return {"success": True, "team_id": req.team_id, "rating": rating}

@router.post("/official")
def toggle_team_official(req: TeamOfficialToggleRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, is_official FROM teams WHERE id = ?", (req.team_id,))
    team = cursor.fetchone()
    if not team:
        conn.close()
        raise HTTPException(status_code=404, detail="Team not found.")

    val = 1 if req.is_official else 0
    cursor.execute("UPDATE teams SET is_official = ? WHERE id = ?", (val, req.team_id))
    log_audit(conn, admin["id"], admin["full_name"], "TOGGLE_TEAM_OFFICIAL", "TEAM", req.team_id,
              f"Set team {team['name']} official={val}")
    conn.commit()
    conn.close()
    return {"success": True, "team_id": req.team_id, "is_official": val}

@router.get("/{team_id}")
def get_team_by_id(team_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.*,
               u_lead.full_name AS leader_name, u_lead.whatsapp_number AS leader_phone,
               COALESCE(NULLIF(t.speaker1_name_custom, ''), u_s1.full_name, '') AS speaker1_name,
               COALESCE(u_s1.whatsapp_number, u_lead.whatsapp_number, '') AS speaker1_phone,
               COALESCE(NULLIF(t.speaker2_name_custom, ''), u_s2.full_name, '') AS speaker2_name,
               COALESCE(u_s2.whatsapp_number, u_lead.whatsapp_number, '') AS speaker2_phone,
               COALESCE(NULLIF(t.speaker3_name_custom, ''), u_s3.full_name, '') AS speaker3_name,
               COALESCE(u_s3.whatsapp_number, u_lead.whatsapp_number, '') AS speaker3_phone
        FROM teams t
        LEFT JOIN users u_lead ON t.leader_id = u_lead.id
        LEFT JOIN users u_s1 ON t.speaker1_id = u_s1.id
        LEFT JOIN users u_s2 ON t.speaker2_id = u_s2.id
        LEFT JOIN users u_s3 ON t.speaker3_id = u_s3.id
        WHERE t.id = ?
    """, (team_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Team not found.")

    t_dict = dict(row)
    t_dict["speaker1"] = {"position": 1, "name": t_dict["speaker1_name"] or "Speaker 1", "phone": t_dict["speaker1_phone"] or ""}
    t_dict["speaker2"] = {"position": 2, "name": t_dict["speaker2_name"] or "Speaker 2", "phone": t_dict["speaker2_phone"] or ""}
    t_dict["speaker3"] = {"position": 3, "name": t_dict["speaker3_name"] or "Speaker 3", "phone": t_dict["speaker3_phone"] or ""}
    return {"team": t_dict}

@router.post("/admin/save-team")
def admin_save_team(req: AdminSaveTeamRequest, admin: dict = Depends(require_admin)):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Team name is required.")

    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rating = req.rating.upper() if req.rating.upper() in ("A", "B", "C") else "B"

    s1_id = req.speaker1_id
    s1_custom = req.speaker1_name_custom.strip() if req.speaker1_name_custom else ""
    if s1_custom:
        s1_id = None

    s2_id = req.speaker2_id
    s2_custom = req.speaker2_name_custom.strip() if req.speaker2_name_custom else ""
    if s2_custom:
        s2_id = None

    s3_id = req.speaker3_id
    s3_custom = req.speaker3_name_custom.strip() if req.speaker3_name_custom else ""
    if s3_custom:
        s3_id = None

    # CRITICAL LOGIC CHECK: A member cannot be in two teams!
    speakers = [s1_id, s2_id, s3_id]
    _validate_speaker_uniqueness(cursor, req.id, speakers, req.leader_id)

    org_name = (req.school_organization or "HGHSDC (Habiganj Govt. High School)").strip()

    if req.id:
        cursor.execute("SELECT * FROM teams WHERE id = ?", (req.id,))
        team_row = cursor.fetchone()
        if not team_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Team not found.")
        existing_team = dict(team_row)
        
        custom_name = (req.custom_name or "").strip()
        name_val = req.name.strip()
        # If admin specified a custom name in name field instead of Team X for a seeded slot
        if existing_team.get("seed_number") and not name_val.startswith("Team "):
            if not custom_name:
                custom_name = name_val
            name_val = f"Team {existing_team['seed_number']}"

        cursor.execute("""
            UPDATE teams
            SET name = ?, custom_name = ?, school_organization = ?, leader_id = ?,
                speaker1_id = ?, speaker2_id = ?, speaker3_id = ?,
                speaker1_name_custom = ?, speaker2_name_custom = ?, speaker3_name_custom = ?,
                rating = ?, is_official = ?, status = ?
            WHERE id = ?
        """, (name_val, custom_name, org_name,
              req.leader_id, s1_id, s2_id, s3_id,
              s1_custom, s2_custom, s3_custom,
              rating, req.is_official, req.status, req.id))
        log_audit(conn, admin["id"], admin["full_name"], "ADMIN_EDIT_TEAM", "TEAM", req.id, f"Edited team {name_val} ({custom_name})", previous_data=existing_team)
        team_id = req.id
    else:
        custom_name = (req.custom_name or "").strip()
        name_val = req.name.strip()
        cursor.execute("SELECT id FROM teams WHERE LOWER(name) = LOWER(?)", (name_val,))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="A team with this name already exists.")

        cursor.execute("""
            INSERT INTO teams (name, custom_name, school_organization, leader_id,
                               speaker1_id, speaker2_id, speaker3_id,
                               speaker1_name_custom, speaker2_name_custom, speaker3_name_custom,
                               rating, is_official, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name_val, custom_name, org_name,
              req.leader_id, s1_id, s2_id, s3_id,
              s1_custom, s2_custom, s3_custom,
              rating, req.is_official, req.status, now_str))
        team_id = cursor.lastrowid
        log_audit(conn, admin["id"], admin["full_name"], "ADMIN_CREATE_TEAM", "TEAM", team_id, f"Created team {name_val} ({custom_name})")

    conn.commit()
    conn.close()
    return {"success": True, "team_id": team_id, "message": f"Team '{req.name}' saved successfully."}

@router.delete("/admin/teams/{team_id}")
def admin_delete_team(team_id: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM teams WHERE id = ?", (team_id,))
    target = cursor.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="Team not found.")

    cursor.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
    target_full = dict(cursor.fetchone())
    cursor.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    log_audit(conn, admin["id"], admin["full_name"], "ADMIN_DELETE_TEAM", "TEAM", team_id, f"Deleted team {target['name']}", previous_data=target_full)
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Team {target['name']} deleted."}
