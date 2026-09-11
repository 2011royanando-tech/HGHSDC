import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.database import get_db, log_audit
from app.auth import get_current_user, require_admin, require_judge_or_admin

router = APIRouter(prefix="/api/results", tags=["Results & Tabulation"])

from app.models import DirectScoreRequest, ResolveTieRequest

class ScoreOverrideRequest(BaseModel):
    team1_aggregate: float
    team2_aggregate: float
    winner_id: int
    tie_status: Optional[str] = "NONE"

@router.get("/match/{match_id}/review")
def get_match_review(match_id: int, user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.*,
               t1.name AS team1_name, t1.custom_name AS team1_custom_name, t1.seed_number AS team1_seed, t1.status AS team1_status, t1.school_organization AS team1_school,
               t2.name AS team2_name, t2.custom_name AS team2_custom_name, t2.seed_number AS team2_seed, t2.status AS team2_status, t2.school_organization AS team2_school,
               w.name AS winner_name, w.custom_name AS winner_custom_name, w.seed_number AS winner_seed, w.status AS winner_status,
               r.name AS round_name, r.round_number
        FROM matches m
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN teams w ON m.winner_id = w.id
        LEFT JOIN rounds r ON m.round_id = r.id
        WHERE m.id = ?
    """, (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    is_admin = user.get("role") == "ADMIN"
    cursor.execute("SELECT judge_id FROM judge_assignments WHERE match_id = ?", (match_id,))
    assigned_judges = [r[0] for r in cursor.fetchall()]
    if not is_admin and user["id"] not in assigned_judges:
        conn.close()
        raise HTTPException(status_code=403, detail="Unauthorized to view private match tabulation.")

    cursor.execute("""
        SELECT sc.id, sc.judge_id, sc.status, sc.team1_total, sc.team2_total,
               sc.tie_choice_team_id, sc.submitted_at,
               u.full_name AS judge_name
        FROM scorecards sc
        JOIN users u ON sc.judge_id = u.id
        WHERE sc.match_id = ?
    """, (match_id,))
    ballots = [dict(r) for r in cursor.fetchall()]

    def get_team_members(t_id):
        if not t_id: return []
        cursor.execute("""
            SELECT t.leader_id, ul.full_name AS leader_name, ul.whatsapp_number AS leader_phone,
                   t.speaker1_id, u1.full_name AS s1_name, u1.whatsapp_number AS s1_phone,
                   t.speaker2_id, u2.full_name AS s2_name, u2.whatsapp_number AS s2_phone,
                   t.speaker3_id, u3.full_name AS s3_name, u3.whatsapp_number AS s3_phone
            FROM teams t
            LEFT JOIN users ul ON t.leader_id = ul.id
            LEFT JOIN users u1 ON t.speaker1_id = u1.id
            LEFT JOIN users u2 ON t.speaker2_id = u2.id
            LEFT JOIN users u3 ON t.speaker3_id = u3.id
            WHERE t.id = ?
        """, (t_id,))
        r = cursor.fetchone()
        if not r: return []
        members = []
        if r["leader_name"]:
            members.append({"role": "Leader", "name": r["leader_name"], "phone": r["leader_phone"] or ""})
        if r["s1_name"]:
            members.append({"role": "1st Speaker", "name": r["s1_name"], "phone": r["s1_phone"] or ""})
        if r["s2_name"]:
            members.append({"role": "2nd Speaker", "name": r["s2_name"], "phone": r["s2_phone"] or ""})
        if r["s3_name"]:
            members.append({"role": "3rd Speaker", "name": r["s3_name"], "phone": r["s3_phone"] or ""})
        return members

    team1_members = get_team_members(match["team1_id"])
    team2_members = get_team_members(match["team2_id"])
    conn.close()

    return {
        "match": dict(match),
        "ballots": ballots,
        "team1_members": team1_members,
        "team2_members": team2_members
    }

@router.post("/match/{match_id}/override")
def override_scores(match_id: int, req: ScoreOverrideRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, team1_id, team2_id, round_id, match_number FROM matches WHERE id = ?", (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    if req.winner_id not in (match["team1_id"], match["team2_id"]):
        conn.close()
        raise HTTPException(status_code=400, detail="Winner must be either Team 1 or Team 2.")

    cursor.execute("""
        UPDATE matches
        SET team1_aggregate = ?, team2_aggregate = ?, winner_id = ?, tie_status = ?, status = 'SILENT'
        WHERE id = ?
    """, (req.team1_aggregate, req.team2_aggregate, req.winner_id, req.tie_status, match_id))

    log_audit(conn, admin["id"], admin["full_name"], "SCORE_OVERRIDE", "MATCH", match_id,
              f"Override scores: T1={req.team1_aggregate}, T2={req.team2_aggregate}, Winner={req.winner_id}")
    conn.commit()
    conn.close()

    return {"success": True, "message": "Scores overridden. Result is retained in SILENT state."}

@router.post("/match/{match_id}/publish")
def publish_result(match_id: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.id, m.round_id, m.match_number, m.bracket_position, m.half,
               m.team1_id, m.team2_id, m.winner_id, m.is_published,
               r.round_number
        FROM matches m
        JOIN rounds r ON m.round_id = r.id
        WHERE m.id = ?
    """, (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    if not match["winner_id"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot publish result without an assigned winner.")

    if match["is_published"]:
        conn.close()
        return {"success": True, "message": "Result already published."}

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        UPDATE matches
        SET is_published = 1, status = 'PUBLISHED' WHERE id = ?
    """, (match_id,))

    # Advance winner to next round
    m_num = match["match_number"]
    winner_id = match["winner_id"]

    adv_match_num = None
    adv_slot = None
    if m_num in range(1, 9):
        # R16 -> QF
        adv_match_num = 9 + ((m_num - 1) // 2)
        adv_slot = 1 if (m_num % 2 != 0) else 2
        cursor.execute(f"UPDATE matches SET team{adv_slot}_id = ? WHERE match_number = ?", (winner_id, adv_match_num))
    elif m_num in range(9, 13):
        # QF -> SF
        adv_match_num = 13 if m_num in (9, 10) else 14
        adv_slot = 1 if m_num in (9, 11) else 2
        cursor.execute(f"UPDATE matches SET team{adv_slot}_id = ? WHERE match_number = ?", (winner_id, adv_match_num))
    elif m_num in (13, 14):
        # SF -> Final
        adv_match_num = 15
        adv_slot = 1 if m_num == 13 else 2
        cursor.execute(f"UPDATE matches SET team{adv_slot}_id = ? WHERE match_number = 15", (winner_id,))
    elif m_num == 15:
        # Grand Final Winner -> Champion!
        cursor.execute("UPDATE tournament SET status = 'COMPLETED'")

    log_audit(conn, admin["id"], admin["full_name"], "PUBLISH_RESULT", "MATCH", match_id,
              f"Published result for match {m_num}. Winner: {winner_id}")

    conn.commit()
    conn.close()

    advancement = [adv_match_num, adv_slot] if adv_match_num else None
    return {
        "success": True,
        "winner_id": winner_id,
        "advancement": advancement,
        "message": f"Match {m_num} result published and winner advanced."
    }

@router.post("/match/{match_id}/direct-score")
def direct_score(match_id: int, req: DirectScoreRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, team1_id, team2_id, match_number FROM matches WHERE id = ?", (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    if req.winner_id not in (match["team1_id"], match["team2_id"]):
        conn.close()
        raise HTTPException(status_code=400, detail="Winner must be either Team 1 or Team 2.")

    status = "SILENT"
    cursor.execute("""
        UPDATE matches
        SET team1_aggregate = ?, team2_aggregate = ?, winner_id = ?, tie_status = 'NONE', status = ?
        WHERE id = ?
    """, (req.team1_score, req.team2_score, req.winner_id, status, match_id))

    log_audit(conn, admin["id"], admin["full_name"], "DIRECT_SCORE_APPLIED", "MATCH", match_id,
              f"Applied direct scores: T1={req.team1_score}, T2={req.team2_score}, Winner={req.winner_id}")
    conn.commit()
    conn.close()

    if req.publish_now:
        return publish_result(match_id, admin)

    return {"success": True, "message": "Scores applied directly. Result is in SILENT state."}

@router.post("/match/{match_id}/resolve-tie")
def resolve_tie(match_id: int, req: ResolveTieRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, team1_id, team2_id, match_number FROM matches WHERE id = ?", (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    if req.winner_id not in (match["team1_id"], match["team2_id"]):
        conn.close()
        raise HTTPException(status_code=400, detail="Winner must be either Team 1 or Team 2.")

    cursor.execute("""
        UPDATE matches
        SET winner_id = ?, tie_status = 'RESOLVED', status = 'SILENT'
        WHERE id = ?
    """, (req.winner_id, match_id))

    log_audit(conn, admin["id"], admin["full_name"], "DEADLOCK_TIE_RESOLVE", "MATCH", match_id,
              f"Admin resolved tie for match {match['match_number']}: winner={req.winner_id}. Reason: {req.reason}")
    conn.commit()
    conn.close()

    return {"success": True, "winner_id": req.winner_id, "message": "Tie resolved successfully."}

@router.post("/match/{match_id}/undo-end")
def undo_end_match(match_id: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.id, m.match_number, m.winner_id, m.is_published
        FROM matches m
        WHERE m.id = ?
    """, (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found.")

    m_num = match["match_number"]
    winner_id = match["winner_id"]

    # Revert match status
    cursor.execute("""
        UPDATE matches
        SET is_published = 0, status = 'SILENT'
        WHERE id = ?
    """, (match_id,))

    # Remove advanced winner from subsequent matches
    if m_num in range(1, 9):
        adv_match_num = 9 + ((m_num - 1) // 2)
        adv_slot = 1 if (m_num % 2 != 0) else 2
        cursor.execute(f"UPDATE matches SET team{adv_slot}_id = NULL WHERE match_number = ?", (adv_match_num,))
    elif m_num in range(9, 13):
        adv_match_num = 13 if m_num in (9, 10) else 14
        adv_slot = 1 if m_num in (9, 11) else 2
        cursor.execute(f"UPDATE matches SET team{adv_slot}_id = NULL WHERE match_number = ?", (adv_match_num,))
    elif m_num in (13, 14):
        adv_slot = 1 if m_num == 13 else 2
        cursor.execute(f"UPDATE matches SET team{adv_slot}_id = NULL WHERE match_number = 15", ())
    elif m_num == 15:
        cursor.execute("UPDATE tournament SET status = 'IN_PROGRESS'")

    log_audit(conn, admin["id"], admin["full_name"], "UNDO_MATCH_RESULT", "MATCH", match_id,
              f"Undid result for match {m_num}. Retracted winner from subsequent rounds.")

    conn.commit()
    conn.close()

    return {"success": True, "message": f"Match {m_num} end undone. Winner retracted from next round."}
