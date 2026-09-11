import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.database import get_db, log_audit
from app.auth import get_current_user, require_judge_or_admin, require_admin
from app.models import ScorecardSaveRequest, ScorecardSubmitRequest

class RejudgeRequest(BaseModel):
    reason: Optional[str] = "Re-evaluation requested by Tab Director."

router = APIRouter(prefix="/api/scoring", tags=["Scoring & Scorecards"])

@router.get("/scorecard/{scorecard_id}")
def get_scorecard(scorecard_id: int, user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sc.id, sc.match_id, sc.judge_id, sc.status, sc.team1_total, sc.team2_total,
               sc.tie_choice_team_id, sc.submitted_at,
               m.round_id, m.match_number, m.team1_id, m.team2_id,
               t1.name AS team1_name, t1.custom_name AS team1_custom_name, t1.seed_number AS team1_seed, t1.status AS team1_status,
               t2.name AS team2_name, t2.custom_name AS team2_custom_name, t2.seed_number AS team2_seed, t2.status AS team2_status,
               r.name AS round_name, r.round_number
        FROM scorecards sc
        JOIN matches m ON sc.match_id = m.id
        JOIN rounds r ON m.round_id = r.id
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        WHERE sc.id = ?
    """, (scorecard_id,))
    sc = cursor.fetchone()
    if not sc:
        conn.close()
        raise HTTPException(status_code=404, detail="Scorecard not found.")

    # Authorization: only the assigned judge or an Admin can access this ballot
    is_admin = user.get("role") == "ADMIN"
    if not is_admin and sc["judge_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Access denied: You can only access your own independent judge ballot.")

    # Get criteria
    cursor.execute("""
        SELECT id, name, name_bn, max_marks, sort_order
        FROM score_criteria
        WHERE scorecard_id = ?
        ORDER BY sort_order ASC, id ASC
    """, (scorecard_id,))
    criteria = [dict(c) for c in cursor.fetchall()]

    # Get scores
    cursor.execute("""
        SELECT criterion_id, team_id, speaker_position, score
        FROM speaker_scores
        WHERE scorecard_id = ?
    """, (scorecard_id,))
    scores = [dict(s) for s in cursor.fetchall()]

    conn.close()

    return {
        "scorecard": dict(sc),
        "criteria": criteria,
        "scores": scores
    }

def _validate_and_calculate_scores(conn, scorecard_id: int, criteria_data, scores_data, match_team1_id: int, match_team2_id: int):
    """
    Validates criteria, saves/updates them, validates speaker scores against max_marks,
    prevents negative scores, and calculates Speaker Totals and Team Totals accurately.
    """
    cursor = conn.cursor()

    if not criteria_data or len(criteria_data) < 1:
        raise HTTPException(status_code=400, detail="At least one scoring criterion must be defined.")

    # Replace / sync criteria
    # Keep track of criterion map
    crit_max_map = {}
    saved_crit_ids = []

    # Clear existing criteria and scores for clean sync
    cursor.execute("DELETE FROM speaker_scores WHERE scorecard_id = ?", (scorecard_id,))
    cursor.execute("DELETE FROM score_criteria WHERE scorecard_id = ?", (scorecard_id,))

    for idx, c in enumerate(criteria_data):
        if c.max_marks <= 0:
            raise HTTPException(status_code=400, detail=f"Criterion '{c.name}' must have a positive maximum mark.")
        cursor.execute("""
            INSERT INTO score_criteria (scorecard_id, name, name_bn, max_marks, sort_order)
            VALUES (?, ?, ?, ?, ?)
        """, (scorecard_id, c.name.strip(), (c.name_bn or "").strip(), c.max_marks, idx))
        new_crit_id = cursor.lastrowid
        # Map original input ID or index
        crit_max_map[idx] = (new_crit_id, c.max_marks, c.name.strip())
        saved_crit_ids.append(new_crit_id)

    team1_total = 0.0
    team2_total = 0.0

    # Process and validate each score
    for s in scores_data:
        # Resolve criterion id
        # Criterion id can either match the new id, or the index in criteria_data
        crit_info = None
        for idx, (cid, max_m, cname) in crit_max_map.items():
            if s.criterion_id == cid or s.criterion_id == idx or (criteria_data[idx].id and s.criterion_id == criteria_data[idx].id):
                crit_info = (cid, max_m, cname)
                break
        
        if not crit_info:
            continue

        cid, max_m, cname = crit_info

        if s.score < 0:
            raise HTTPException(status_code=400, detail=f"Validation Error: Score for '{cname}' cannot be negative ({s.score}).")
        if s.score > max_m:
            raise HTTPException(status_code=400, detail=f"Validation Error: Score for '{cname}' ({s.score}) exceeds maximum marks ({max_m}).")
        if s.speaker_position not in (1, 2, 3):
            raise HTTPException(status_code=400, detail="Speaker position must be 1, 2, or 3.")

        cursor.execute("""
            INSERT INTO speaker_scores (scorecard_id, criterion_id, team_id, speaker_position, score)
            VALUES (?, ?, ?, ?, ?)
        """, (scorecard_id, cid, s.team_id, s.speaker_position, s.score))

        if s.team_id == match_team1_id:
            team1_total += s.score
        elif s.team_id == match_team2_id:
            team2_total += s.score

    return round(team1_total, 2), round(team2_total, 2)

@router.post("/scorecard/{scorecard_id}/save")
def save_scorecard(scorecard_id: int, req: ScorecardSaveRequest, user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT sc.id, sc.match_id, sc.judge_id, sc.status, m.team1_id, m.team2_id FROM scorecards sc JOIN matches m ON sc.match_id = m.id WHERE sc.id = ?", (scorecard_id,))
    sc = cursor.fetchone()
    if not sc:
        conn.close()
        raise HTTPException(status_code=404, detail="Scorecard not found.")

    if user.get("role") != "ADMIN" and sc["judge_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Cannot edit another judge's ballot.")

    if sc["status"] == "SUBMITTED" and user.get("role") != "ADMIN":
        conn.close()
        raise HTTPException(status_code=400, detail="Scorecard is already submitted. Only Admin can permit modifications.")

    team1_tot, team2_tot = _validate_and_calculate_scores(conn, scorecard_id, req.criteria, req.scores, sc["team1_id"], sc["team2_id"])

    cursor.execute("""
        UPDATE scorecards
        SET team1_total = ?, team2_total = ?
        WHERE id = ?
    """, (team1_tot, team2_tot, scorecard_id))

    cursor.execute("UPDATE matches SET status = 'SCORING' WHERE id = ? AND status = 'LIVE'", (sc["match_id"],))

    log_audit(conn, user["id"], user["full_name"], "SAVE_SCORECARD_DRAFT", "SCORECARD", scorecard_id,
              f"Saved draft: Team1={team1_tot}, Team2={team2_tot}")
    conn.commit()
    conn.close()

    return {
        "success": True,
        "team1_total": team1_tot,
        "team2_total": team2_tot,
        "message": "Scorecard draft saved successfully."
    }

@router.post("/scorecard/{scorecard_id}/submit")
def submit_scorecard(scorecard_id: int, req: ScorecardSubmitRequest, user: dict = Depends(require_judge_or_admin)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sc.id, sc.match_id, sc.judge_id, sc.status, m.team1_id, m.team2_id, m.round_id
        FROM scorecards sc
        JOIN matches m ON sc.match_id = m.id
        WHERE sc.id = ?
    """, (scorecard_id,))
    sc = cursor.fetchone()
    if not sc:
        conn.close()
        raise HTTPException(status_code=404, detail="Scorecard not found.")

    if user.get("role") != "ADMIN" and sc["judge_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Cannot submit another judge's ballot.")

    team1_tot, team2_tot = _validate_and_calculate_scores(conn, scorecard_id, req.criteria, req.scores, sc["team1_id"], sc["team2_id"])

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        UPDATE scorecards
        SET team1_total = ?, team2_total = ?, tie_choice_team_id = ?, status = 'SUBMITTED', submitted_at = ?
        WHERE id = ?
    """, (team1_tot, team2_tot, req.tie_choice_team_id, now_str, scorecard_id))

    log_audit(conn, user["id"], user["full_name"], "SUBMIT_BALLOT", "SCORECARD", scorecard_id,
              f"Submitted ballot: Team1={team1_tot}, Team2={team2_tot}")

    # Check if all assigned judges for this match have submitted
    cursor.execute("SELECT COUNT(*) FROM judge_assignments WHERE match_id = ?", (sc["match_id"],))
    assigned_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM scorecards WHERE match_id = ? AND status = 'SUBMITTED'", (sc["match_id"],))
    submitted_count = cursor.fetchone()[0]

    match_new_status = "AWAITING_BALLOTS"
    if submitted_count >= assigned_count and assigned_count > 0:
        match_new_status = "REVIEW"
        # Auto-calculate multi-judge aggregation internally!
        cursor.execute("SELECT team1_total, team2_total, tie_choice_team_id FROM scorecards WHERE match_id = ? AND status = 'SUBMITTED'", (sc["match_id"],))
        submitted_ballots = cursor.fetchall()
        t1_avg = sum(b["team1_total"] for b in submitted_ballots) / len(submitted_ballots)
        t2_avg = sum(b["team2_total"] for b in submitted_ballots) / len(submitted_ballots)

        tie_status = "NONE"
        provisional_winner = None
        if t1_avg > t2_avg:
            provisional_winner = sc["team1_id"]
        elif t2_avg > t1_avg:
            provisional_winner = sc["team2_id"]
        else:
            # Exact tie detected!
            tie_status = "JUDGE_DECISION_REQUIRED"
            # Count judge tiebreak votes
            votes_t1 = sum(1 for b in submitted_ballots if b["tie_choice_team_id"] == sc["team1_id"])
            votes_t2 = sum(1 for b in submitted_ballots if b["tie_choice_team_id"] == sc["team2_id"])
            if votes_t1 > votes_t2:
                provisional_winner = sc["team1_id"]
                tie_status = "RESOLVED"
            elif votes_t2 > votes_t1:
                provisional_winner = sc["team2_id"]
                tie_status = "RESOLVED"
            else:
                # Deadlock (e.g. 1-1 for 2 judges)
                tie_status = "DEADLOCK_ADMIN_REQUIRED"

        # Result remains SILENT (is_published = 0)
        cursor.execute("""
            UPDATE matches
            SET team1_aggregate = ?, team2_aggregate = ?, winner_id = ?, tie_status = ?, status = 'SILENT'
            WHERE id = ?
        """, (t1_avg, t2_avg, provisional_winner, tie_status, sc["match_id"]))
    else:
        cursor.execute("UPDATE matches SET status = 'AWAITING_BALLOTS' WHERE id = ?", (sc["match_id"],))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "team1_total": team1_tot,
        "team2_total": team2_tot,
        "submitted_count": submitted_count,
        "assigned_count": assigned_count,
        "message": "Final ballot submitted successfully. Result is kept SILENT until published."
    }

def _recalculate_match_state_after_ballot_change(cursor, match_id: int):
    cursor.execute("SELECT COUNT(*) FROM judge_assignments WHERE match_id = ?", (match_id,))
    assigned_count = cursor.fetchone()[0]

    cursor.execute("SELECT team1_total, team2_total, tie_choice_team_id FROM scorecards WHERE match_id = ? AND status = 'SUBMITTED'", (match_id,))
    submitted_ballots = cursor.fetchall()
    submitted_count = len(submitted_ballots)

    cursor.execute("SELECT team1_id, team2_id, is_published FROM matches WHERE id = ?", (match_id,))
    m = cursor.fetchone()
    if not m:
        return

    if submitted_count >= assigned_count and assigned_count > 0:
        t1_avg = sum(b["team1_total"] for b in submitted_ballots) / len(submitted_ballots)
        t2_avg = sum(b["team2_total"] for b in submitted_ballots) / len(submitted_ballots)

        tie_status = "NONE"
        provisional_winner = None
        if t1_avg > t2_avg:
            provisional_winner = m["team1_id"]
        elif t2_avg > t1_avg:
            provisional_winner = m["team2_id"]
        else:
            tie_status = "JUDGE_DECISION_REQUIRED"
            votes_t1 = sum(1 for b in submitted_ballots if b["tie_choice_team_id"] == m["team1_id"])
            votes_t2 = sum(1 for b in submitted_ballots if b["tie_choice_team_id"] == m["team2_id"])
            if votes_t1 > votes_t2:
                provisional_winner = m["team1_id"]
                tie_status = "RESOLVED"
            elif votes_t2 > votes_t1:
                provisional_winner = m["team2_id"]
                tie_status = "RESOLVED"
            else:
                tie_status = "DEADLOCK_ADMIN_REQUIRED"

        cursor.execute("""
            UPDATE matches
            SET team1_aggregate = ?, team2_aggregate = ?, winner_id = ?, tie_status = ?, status = 'SILENT'
            WHERE id = ?
        """, (t1_avg, t2_avg, provisional_winner, tie_status, match_id))
    elif submitted_count > 0:
        cursor.execute("""
            UPDATE matches
            SET team1_aggregate = NULL, team2_aggregate = NULL, winner_id = NULL, tie_status = 'NONE', is_published = 0, status = 'AWAITING_BALLOTS'
            WHERE id = ?
        """, (match_id,))
    else:
        cursor.execute("""
            UPDATE matches
            SET team1_aggregate = NULL, team2_aggregate = NULL, winner_id = NULL, tie_status = 'NONE', is_published = 0, status = 'SCORING'
            WHERE id = ?
        """, (match_id,))

@router.delete("/ballot/{scorecard_id}")
def delete_ballot(scorecard_id: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sc.id, sc.match_id, sc.judge_id, u.full_name AS judge_name, m.match_number
        FROM scorecards sc
        JOIN matches m ON sc.match_id = m.id
        LEFT JOIN users u ON sc.judge_id = u.id
        WHERE sc.id = ?
    """, (scorecard_id,))
    sc = cursor.fetchone()
    if not sc:
        conn.close()
        raise HTTPException(status_code=404, detail="Scorecard not found.")

    # Delete speaker scores and reset scorecard to fresh draft
    cursor.execute("DELETE FROM speaker_scores WHERE scorecard_id = ?", (scorecard_id,))
    cursor.execute("""
        UPDATE scorecards
        SET status = 'DRAFT', team1_total = 0.0, team2_total = 0.0, tie_choice_team_id = NULL, submitted_at = NULL
        WHERE id = ?
    """, (scorecard_id,))

    # Re-calculate match status
    _recalculate_match_state_after_ballot_change(cursor, sc["match_id"])

    log_audit(conn, admin["id"], admin["full_name"], "DELETE_BALLOT", "SCORECARD", scorecard_id,
              f"Deleted ballot for Judge {sc['judge_name'] or sc['judge_id']} on Match #{sc['match_number']}")
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Ballot for {sc['judge_name'] or 'Judge'} has been deleted and reset to draft."}

@router.post("/ballot/{scorecard_id}/request-rejudge")
def request_rejudge_ballot(scorecard_id: int, req: Optional[RejudgeRequest] = None, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sc.id, sc.match_id, sc.judge_id, u.full_name AS judge_name, m.match_number
        FROM scorecards sc
        JOIN matches m ON sc.match_id = m.id
        LEFT JOIN users u ON sc.judge_id = u.id
        WHERE sc.id = ?
    """, (scorecard_id,))
    sc = cursor.fetchone()
    if not sc:
        conn.close()
        raise HTTPException(status_code=404, detail="Scorecard not found.")

    reason = (req.reason if req and req.reason else "পুনর্মূল্যায়নের জন্য ট্যাব ডিরেক্টর দ্বারা ব্যালট আনলক করা হয়েছে (Re-evaluation requested by Tab Director).").strip()

    # Revert scorecard status to DRAFT so judge can edit again
    cursor.execute("""
        UPDATE scorecards
        SET status = 'DRAFT'
        WHERE id = ?
    """, (scorecard_id,))

    # Re-calculate match status
    _recalculate_match_state_after_ballot_change(cursor, sc["match_id"])

    # Send notification to judge
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    msg = f"Match #{sc['match_number']} Ballot Re-evaluation: {reason}"
    cursor.execute("""
        INSERT INTO judge_notifications (judge_id, match_id, message, is_read, created_at)
        VALUES (?, ?, ?, 0, ?)
    """, (sc["judge_id"], sc["match_id"], msg, now_str))

    log_audit(conn, admin["id"], admin["full_name"], "REQUEST_REJUDGE", "SCORECARD", scorecard_id,
              f"Requested rejudge for Match #{sc['match_number']}: {reason}")
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Re-evaluation requested for {sc['judge_name'] or 'Judge'}. Ballot unlocked to Draft."}

