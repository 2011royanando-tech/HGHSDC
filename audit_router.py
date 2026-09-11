import datetime
import json
import re
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db, log_audit
from app.auth import require_admin

router = APIRouter(prefix="/api/audit", tags=["Audit Log"])

@router.get("")
def get_audit_logs(limit: int = 150, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, actor_id, actor_name, action, object_type, object_id, details, previous_data, is_undone, timestamp
        FROM audit_logs
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return {"audit_logs": [dict(r) for r in rows]}

@router.post("/{log_id}/undo")
def undo_audit_log(log_id: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, actor_id, actor_name, action, object_type, object_id, details, previous_data, is_undone, timestamp
        FROM audit_logs
        WHERE id = ?
    """, (log_id,))
    log = cursor.fetchone()
    if not log:
        conn.close()
        raise HTTPException(status_code=404, detail="Audit log entry not found.")

    if log["is_undone"]:
        conn.close()
        raise HTTPException(status_code=400, detail="এই পরিবর্তনটি ইতিমধ্যে বাতিল (Undo) করা হয়েছে। (This action has already been undone.)")

    action = log["action"]
    obj_type = log["object_type"]
    obj_id = log["object_id"]
    prev_raw = log["previous_data"] or ""
    details = log["details"] or ""

    prev_data = {}
    if prev_raw:
        try:
            prev_data = json.loads(prev_raw)
        except:
            prev_data = {}

    success_msg = f"Action '{action}' undone successfully."

    # -------------------------------------------------------------
    # 1. USER ROLE APPROVALS & REJECTIONS
    # -------------------------------------------------------------
    if action == "ROLE_APPROVE":
        uid = int(obj_id)
        cursor.execute("UPDATE users SET role = 'MEMBER', role_status = 'PENDING_APPROVAL' WHERE id = ?", (uid,))
        success_msg = "ভূমিকা অনুমোদন বাতিল করা হয়েছে। ব্যবহারকারীর স্ট্যাটাস 'অপেক্ষমাণ' হিসেবে রাখা হলো।"

    elif action == "ROLE_REJECT":
        uid = int(obj_id)
        cursor.execute("UPDATE users SET role_status = 'PENDING_APPROVAL' WHERE id = ?", (uid,))
        success_msg = "ভূমিকা প্রত্যাখ্যান বাতিল করা হয়েছে। ব্যবহারকারীর স্ট্যাটাস 'অপেক্ষমাণ' হিসেবে রাখা হলো।"

    # -------------------------------------------------------------
    # 2. TEAM APPROVAL & REJECTION
    # -------------------------------------------------------------
    elif action == "TEAM_APPROVED":
        tid = int(obj_id)
        cursor.execute("UPDATE teams SET status = 'PENDING_ADMIN_APPROVAL', is_official = 0 WHERE id = ?", (tid,))
        success_msg = "দল অনুমোদন বাতিল করা হয়েছে। দলের স্ট্যাটাস 'অপেক্ষমাণ' রাখা হলো।"

    elif action == "TEAM_REJECTED":
        tid = int(obj_id)
        cursor.execute("UPDATE teams SET status = 'PENDING_ADMIN_APPROVAL' WHERE id = ?", (tid,))
        success_msg = "দল প্রত্যাখ্যান বাতিল করা হয়েছে। দলের স্ট্যাটাস 'অপেক্ষমাণ' রাখা হলো।"

    # -------------------------------------------------------------
    # 3. TEAM RATING CHANGE
    # -------------------------------------------------------------
    elif action == "TEAM_RATING_CHANGE":
        tid = int(obj_id)
        old_rating = prev_data.get("old_rating")
        if not old_rating and "from " in details and " to " in details:
            m = re.search(r'from\s+([A-C])\s+to\s+([A-C])', details)
            if m:
                old_rating = m.group(1)
        if old_rating:
            cursor.execute("UPDATE teams SET rating = ? WHERE id = ?", (old_rating, tid))
            success_msg = f"দলের রেটিং পূর্বের মান ({old_rating}) এ ফিরিয়ে নেওয়া হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="Cannot determine previous rating to revert to.")

    # -------------------------------------------------------------
    # 4. TEAM CREATION / EDIT / DELETION
    # -------------------------------------------------------------
    elif action == "ADMIN_CREATE_TEAM" or action == "TEAM_APPLY":
        tid = int(obj_id)
        cursor.execute("DELETE FROM teams WHERE id = ?", (tid,))
        success_msg = "দল তৈরির পদক্ষেপটি বাতিল করা হয়েছে। দলটি মুছে দেওয়া হলো।"

    elif action == "ADMIN_EDIT_TEAM":
        tid = int(obj_id)
        if prev_data:
            cursor.execute("""
                UPDATE teams
                SET name = ?, school_organization = ?, leader_id = ?,
                    speaker1_id = ?, speaker2_id = ?, speaker3_id = ?,
                    speaker1_name_custom = ?, speaker2_name_custom = ?, speaker3_name_custom = ?,
                    rating = ?, is_official = ?, status = ?
                WHERE id = ?
            """, (
                prev_data.get("name"), prev_data.get("school_organization"), prev_data.get("leader_id"),
                prev_data.get("speaker1_id"), prev_data.get("speaker2_id"), prev_data.get("speaker3_id"),
                prev_data.get("speaker1_name_custom", ""), prev_data.get("speaker2_name_custom", ""), prev_data.get("speaker3_name_custom", ""),
                prev_data.get("rating", "B"), prev_data.get("is_official", 1), prev_data.get("status", "APPROVED"),
                tid
            ))
            success_msg = f"দল '{prev_data.get('name')}' এর আগের তথ্য ফিরিয়ে আনা হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="No previous team state recorded to restore.")

    elif action == "ADMIN_DELETE_TEAM":
        if prev_data:
            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cursor.execute("""
                INSERT INTO teams (id, name, school_organization, leader_id, speaker1_id, speaker2_id, speaker3_id,
                                   speaker1_name_custom, speaker2_name_custom, speaker3_name_custom,
                                   rating, is_official, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prev_data.get("id"), prev_data.get("name"), prev_data.get("school_organization"), prev_data.get("leader_id"),
                prev_data.get("speaker1_id"), prev_data.get("speaker2_id"), prev_data.get("speaker3_id"),
                prev_data.get("speaker1_name_custom", ""), prev_data.get("speaker2_name_custom", ""), prev_data.get("speaker3_name_custom", ""),
                prev_data.get("rating", "B"), prev_data.get("is_official", 1), prev_data.get("status", "APPROVED"),
                prev_data.get("created_at", now_str)
            ))
            success_msg = f"মুছে ফেলা দল '{prev_data.get('name')}' পুনরায় ফিরিয়ে আনা হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="No previous team state recorded to restore.")

    # -------------------------------------------------------------
    # 5. USER CREATION / EDIT / DELETION
    # -------------------------------------------------------------
    elif action in ("ADMIN_CREATE_USER", "REGISTER"):
        uid = int(obj_id)
        if uid == admin["id"]:
            raise HTTPException(status_code=400, detail="Cannot delete active administrator account.")
        cursor.execute("DELETE FROM users WHERE id = ?", (uid,))
        success_msg = "ব্যবহারকারী তৈরির পদক্ষেপ বাতিল করা হয়েছে।"

    elif action == "ADMIN_EDIT_USER":
        uid = int(obj_id)
        if prev_data:
            cursor.execute("""
                UPDATE users
                SET full_name = ?, whatsapp_number = ?, role = ?, role_status = ?,
                    school_organization = ?, photo_url = ?
                WHERE id = ?
            """, (
                prev_data.get("full_name"), prev_data.get("whatsapp_number"), prev_data.get("role"),
                prev_data.get("role_status"), prev_data.get("school_organization"), prev_data.get("photo_url", ""),
                uid
            ))
            success_msg = f"ব্যবহারকারী '{prev_data.get('full_name')}' এর আগের তথ্য ফিরিয়ে আনা হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="No previous user state recorded.")

    elif action == "ADMIN_DELETE_USER":
        if prev_data:
            cursor.execute("""
                INSERT INTO users (id, full_name, whatsapp_number, pin_hash, salt, role, applied_role, role_status, school_organization, photo_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prev_data.get("id"), prev_data.get("full_name"), prev_data.get("whatsapp_number"),
                prev_data.get("pin_hash", ""), prev_data.get("salt", ""), prev_data.get("role", "MEMBER"),
                prev_data.get("applied_role", "MEMBER"), prev_data.get("role_status", "APPROVED"),
                prev_data.get("school_organization", ""), prev_data.get("photo_url", ""),
                prev_data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat())
            ))
            success_msg = f"মুছে ফেলা ব্যবহারকারী '{prev_data.get('full_name')}' সফলভাবে ফিরিয়ে আনা হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="No previous user state recorded.")

    # -------------------------------------------------------------
    # 6. BRACKET LOCK & UNLOCK
    # -------------------------------------------------------------
    elif action == "LOCK_BRACKET":
        cursor.execute("UPDATE tournament SET status = 'BRACKET_GENERATED'")
        cursor.execute("UPDATE rounds SET status = 'DRAFT' WHERE round_number = 1")
        cursor.execute("UPDATE matches SET status = 'SCHEDULED' WHERE match_number BETWEEN 1 AND 8 AND status = 'READY'")
        success_msg = "ব্র্যাকেট লক বাতিল করা হয়েছে। ব্র্যাকেট এখন আনলক অবস্থায় আছে।"

    elif action == "UNLOCK_BRACKET":
        cursor.execute("UPDATE tournament SET status = 'BRACKET_LOCKED'")
        cursor.execute("UPDATE rounds SET status = 'READY' WHERE round_number = 1")
        cursor.execute("UPDATE matches SET status = 'READY' WHERE match_number BETWEEN 1 AND 8")
        success_msg = "ব্র্যাকেট আনলক বাতিল করা হয়েছে। ব্র্যাকেট পুনরায় লক করা হলো।"

    elif action == "GENERATE_BRACKET":
        cursor.execute("DELETE FROM matches")
        cursor.execute("UPDATE tournament SET status = 'SETUP', bracket_balance_score = 0.0, bracket_details = ''")
        success_msg = "ব্র্যাকেট জেনারেশন বাতিল করা হয়েছে। ব্র্যাকেট রিসেট করা হলো।"

    # -------------------------------------------------------------
    # 7. BRACKET MANUAL SWAP
    # -------------------------------------------------------------
    elif action == "BRACKET_MANUAL_SWAP":
        if prev_data:
            cursor.execute(f"UPDATE matches SET team{prev_data['slot_1']}_id = ? WHERE match_number = ?", (prev_data['team1_id'], prev_data['match_id_1']))
            cursor.execute(f"UPDATE matches SET team{prev_data['slot_2']}_id = ? WHERE match_number = ?", (prev_data['team2_id'], prev_data['match_id_2']))
            success_msg = "ব্র্যাকেটের টিম অদলবদল বাতিল করে আগের স্থানে ফিরিয়ে দেওয়া হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="Previous swap state unavailable.")

    # -------------------------------------------------------------
    # 8. REORDER SPEAKERS
    # -------------------------------------------------------------
    elif action == "REORDER_SPEAKERS":
        tid = int(obj_id)
        if prev_data:
            cursor.execute("""
                UPDATE teams SET speaker1_id = ?, speaker2_id = ?, speaker3_id = ? WHERE id = ?
            """, (prev_data.get("speaker1_id"), prev_data.get("speaker2_id"), prev_data.get("speaker3_id"), tid))
            success_msg = "স্পিকারদের আগের অর্ডারে ফিরিয়ে আনা হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="Previous speaker order unavailable.")

    # -------------------------------------------------------------
    # 9. RESULTS / DIRECT SCORE / PUBLISH
    # -------------------------------------------------------------
    elif action == "PUBLISH_RESULT":
        mid = int(obj_id)
        cursor.execute("UPDATE matches SET is_published = 0, status = 'SILENT' WHERE id = ?", (mid,))
        success_msg = "ফলাফল প্রকাশ বাতিল করা হয়েছে। ফলাফল পুনরায় অপ্রকাশিত (Silent) রাখা হলো।"

    elif action == "ADMIN_DIRECT_SCORE":
        mid = int(obj_id)
        if prev_data:
            cursor.execute("""
                UPDATE matches
                SET team1_aggregate = ?, team2_aggregate = ?, winner_id = ?, tie_status = ?, status = ?, is_published = ?
                WHERE id = ?
            """, (
                prev_data.get("team1_aggregate"), prev_data.get("team2_aggregate"),
                prev_data.get("winner_id"), prev_data.get("tie_status", "NONE"),
                prev_data.get("status", "SCHEDULED"), prev_data.get("is_published", 0),
                mid
            ))
            success_msg = "সরাসরি নম্বর ইনপুট বাতিল করে আগের ম্যাচে ফিরিয়ে দেওয়া হয়েছে।"
        else:
            cursor.execute("UPDATE matches SET team1_aggregate = NULL, team2_aggregate = NULL, winner_id = NULL, tie_status = 'NONE', status = 'SCHEDULED' WHERE id = ?", (mid,))
            success_msg = "ম্যাচের নম্বর ও বিজয়ী বাতিল করা হয়েছে।"

    elif action == "RESOLVE_DEADLOCK_TIE":
        mid = int(obj_id)
        cursor.execute("UPDATE matches SET winner_id = NULL, tie_status = 'DEADLOCK_ADMIN_REQUIRED' WHERE id = ?", (mid,))
        success_msg = "টাইব্রেকার সমাধান বাতিল করা হয়েছে।"

    # -------------------------------------------------------------
    # 10. JUDGE ASSIGNMENTS
    # -------------------------------------------------------------
    elif action == "ASSIGN_JUDGES":
        mid = int(obj_id)
        cursor.execute("DELETE FROM judge_assignments WHERE match_id = ?", (mid,))
        cursor.execute("DELETE FROM scorecards WHERE match_id = ?", (mid,))
        if prev_data and "judge_ids" in prev_data:
            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for jid in prev_data["judge_ids"]:
                cursor.execute("INSERT INTO judge_assignments (match_id, judge_id, created_at) VALUES (?, ?, ?)", (mid, jid, now_str))
                cursor.execute("INSERT INTO scorecards (match_id, judge_id, status) VALUES (?, ?, 'DRAFT')", (mid, jid))
            success_msg = f"ম্যাচ #{mid} এর বিচারক অ্যাসাইনমেন্ট পূর্বাবস্থায় ফিরিয়ে নেওয়া হয়েছে।"
        else:
            success_msg = f"ম্যাচ #{mid} এর বিচারক অ্যাসাইনমেন্ট বাতিল করা হয়েছে।"

    # -------------------------------------------------------------
    # 11. ROUND START & MOTIONS
    # -------------------------------------------------------------
    elif action == "START_ROUND":
        rnum = int(obj_id)
        cursor.execute("UPDATE rounds SET status = 'READY' WHERE round_number = ?", (rnum,))
        cursor.execute("""
            UPDATE matches SET status = 'READY'
            WHERE round_id = (SELECT id FROM rounds WHERE round_number = ?)
        """, (rnum,))
        success_msg = f"রাউন্ড {rnum} এর শুরু বাতিল করে 'প্রস্তুত' অবস্থায় ফিরিয়ে নেওয়া হয়েছে।"

    elif action == "UPDATE_ROUND_MOTION":
        rnum = int(obj_id)
        if prev_data:
            cursor.execute("UPDATE rounds SET motion_en = ?, motion_bn = ? WHERE round_number = ?", (prev_data.get("motion_en", ""), prev_data.get("motion_bn", ""), rnum))
            success_msg = f"রাউন্ড {rnum} এর মোশন পূর্বের লেখায় ফিরিয়ে নেওয়া হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="Previous motion data unavailable.")

    # -------------------------------------------------------------
    # 12. TIMER SETTINGS
    # -------------------------------------------------------------
    elif action == "UPDATE_TIMER_SETTINGS":
        if prev_data:
            cursor.execute("""
                UPDATE timer_settings
                SET speaking_time_seconds = ?, warning_1_seconds = ?, warning_2_seconds = ?,
                    final_bell_seconds = ?, sound_enabled = ?
                WHERE id = 1
            """, (
                prev_data.get("speaking_time_seconds", 180), prev_data.get("warning_1_seconds", 120),
                prev_data.get("warning_2_seconds", 150), prev_data.get("final_bell_seconds", 180),
                prev_data.get("sound_enabled", 1)
            ))
            success_msg = "টাইমার সেটিংস পূর্বের মানে ফিরিয়ে নেওয়া হয়েছে।"
        else:
            raise HTTPException(status_code=400, detail="Previous timer settings not found.")

    else:
        raise HTTPException(status_code=400, detail=f"অ্যাকশন '{action}' এর জন্য Undo সমর্থিত নয়।")

    # Mark this log as undone
    cursor.execute("UPDATE audit_logs SET is_undone = 1 WHERE id = ?", (log_id,))

    # Log undo audit event
    log_audit(
        conn, admin["id"], admin["full_name"], "UNDO_ACTION", "AUDIT_LOG", log_id,
        f"বাতিল করা হয়েছে: '{action}' ({obj_type} #{obj_id})"
    )

    conn.commit()
    conn.close()

    return {"success": True, "message": success_msg}
