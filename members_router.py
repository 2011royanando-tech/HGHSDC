import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.database import get_db, log_audit
from app.auth import get_current_user, require_admin, hash_pin
from app.models import RoleApprovalRequest

router = APIRouter(prefix="/api/members", tags=["Members & Applications"])

class AdminCreateUserRequest(BaseModel):
    full_name: str
    whatsapp_number: str
    pin: str = "1234"
    role: str = "MEMBER"  # ADMIN, JUDGE, LEADER, MEMBER
    school_organization: Optional[str] = ""
    photo_url: Optional[str] = ""

class AdminUpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    whatsapp_number: Optional[str] = None
    pin: Optional[str] = None
    role: Optional[str] = None
    role_status: Optional[str] = None
    school_organization: Optional[str] = None
    photo_url: Optional[str] = None

@router.get("")
def list_members(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, whatsapp_number, role, applied_role, role_status, school_organization, photo_url, created_at
        FROM users ORDER BY full_name ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    is_admin = user.get("role") == "ADMIN"
    result = []
    for r in rows:
        item = {
            "id": r["id"],
            "full_name": r["full_name"],
            "role": r["role"],
            "applied_role": r["applied_role"],
            "role_status": r["role_status"],
            "school_organization": r["school_organization"] or "",
            "photo_url": r["photo_url"] or "",
            "created_at": r["created_at"]
        }
        if is_admin:
            item["whatsapp_number"] = r["whatsapp_number"]
        result.append(item)
    return {"members": result}

@router.get("/eligible-speakers")
def get_eligible_speakers(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.full_name, u.whatsapp_number, u.school_organization, u.role, u.photo_url,
               t.id AS current_team_id, t.name AS current_team_name
        FROM users u
        LEFT JOIN teams t ON (t.speaker1_id = u.id OR t.speaker2_id = u.id OR t.speaker3_id = u.id) AND t.status != 'REJECTED'
        WHERE u.role NOT IN ('ADMIN', 'JUDGE') AND u.applied_role != 'JUDGE'
        ORDER BY u.full_name ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    eligible = []
    for r in rows:
        eligible.append({
            "id": r["id"],
            "full_name": r["full_name"],
            "whatsapp_number": r["whatsapp_number"],
            "school_organization": r["school_organization"] or "HGHSDC (Habiganj Govt. High School)",
            "photo_url": r["photo_url"] or "",
            "role": r["role"],
            "current_team_id": r["current_team_id"],
            "current_team_name": r["current_team_name"]
        })
    return {"eligible_speakers": eligible}

@router.get("/applications/pending")
def list_pending_applications(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, whatsapp_number, applied_role, role_status, school_organization, photo_url, created_at
        FROM users
        WHERE applied_role IN ('LEADER', 'JUDGE') AND role_status = 'PENDING_APPROVAL'
        ORDER BY created_at ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    return {"pending_applications": [dict(r) for r in rows]}

@router.post("/applications/approve")
def approve_application(req: RoleApprovalRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name, applied_role FROM users WHERE id = ?", (req.user_id,))
    target_user = cursor.fetchone()
    if not target_user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")

    new_role = target_user["applied_role"] if target_user["applied_role"] in ("LEADER", "JUDGE") else "MEMBER"
    cursor.execute("""
        UPDATE users
        SET role = ?, role_status = 'APPROVED'
        WHERE id = ?
    """, (new_role, req.user_id))

    log_audit(conn, admin["id"], admin["full_name"], "ROLE_APPROVE", "USER", req.user_id, f"Approved role {new_role}")
    conn.commit()
    conn.close()
    return {"success": True, "message": f"User approved as {new_role}."}

@router.post("/applications/reject")
def reject_application(req: RoleApprovalRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name, applied_role FROM users WHERE id = ?", (req.user_id,))
    target_user = cursor.fetchone()
    if not target_user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")

    cursor.execute("""
        UPDATE users
        SET role = 'MEMBER', role_status = 'REJECTED'
        WHERE id = ?
    """, (req.user_id,))

    log_audit(conn, admin["id"], admin["full_name"], "ROLE_REJECT", "USER", req.user_id, f"Rejected {target_user['applied_role']} application")
    conn.commit()
    conn.close()
    return {"success": True, "message": f"User application rejected. Retained as Member."}

# ==========================================
# ADMIN SUPER-DIRECT USER OPERATIONS
# ==========================================

@router.get("/admin/all-users")
def admin_get_all_users(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, username, whatsapp_number, role, applied_role, role_status, school_organization, photo_url, created_at
        FROM users
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return {"users": [dict(r) for r in rows]}

@router.post("/admin/create-user")
def admin_create_user(req: AdminCreateUserRequest, admin: dict = Depends(require_admin)):
    if not req.full_name.strip() or not req.whatsapp_number.strip():
        raise HTTPException(status_code=400, detail="Name and WhatsApp / Username are required.")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE LOWER(whatsapp_number) = LOWER(?)", (req.whatsapp_number.strip(),))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="A user with this username/phone already exists.")

    pin_hash, salt = hash_pin(req.pin.strip() if req.pin else "1234")
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    role = req.role.upper() if req.role else "MEMBER"

    cursor.execute("""
        INSERT INTO users (full_name, whatsapp_number, pin_hash, salt, role, applied_role, role_status, school_organization, photo_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'APPROVED', ?, ?, ?)
    """, (req.full_name.strip(), req.whatsapp_number.strip(), pin_hash, salt, role, role,
          (req.school_organization or "").strip(), (req.photo_url or "").strip(), now_str))

    user_id = cursor.lastrowid
    log_audit(conn, admin["id"], admin["full_name"], "ADMIN_CREATE_USER", "USER", user_id, f"Created {role} {req.full_name.strip()}")
    conn.commit()
    conn.close()
    return {"success": True, "user_id": user_id, "message": f"User created as {role}."}

@router.get("/admin/users/{user_id}")
def admin_get_single_user(user_id: int, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, whatsapp_number, username, role, applied_role, role_status, school_organization, photo_url, created_at
        FROM users WHERE id = ?
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"user": dict(row)}

@router.put("/admin/users/{user_id}")
def admin_update_user(user_id: int, req: AdminUpdateUserRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name FROM users WHERE id = ?", (user_id,))
    target = cursor.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")

    updates = []
    params = []

    if req.full_name is not None:
        updates.append("full_name = ?")
        params.append(req.full_name.strip())
    if req.whatsapp_number is not None:
        clean_phone = req.whatsapp_number.strip()
        if not clean_phone:
            conn.close()
            raise HTTPException(status_code=400, detail="WhatsApp number / Username cannot be empty.")
        cursor.execute("SELECT id FROM users WHERE (LOWER(whatsapp_number) = LOWER(?) OR LOWER(username) = LOWER(?)) AND id != ?", (clean_phone, clean_phone, user_id))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="This WhatsApp number / Username is already in use by another user.")
        updates.append("whatsapp_number = ?")
        params.append(clean_phone)
        updates.append("username = ?")
        params.append(clean_phone)
    if req.role is not None:
        updates.append("role = ?")
        params.append(req.role.upper())
    if req.role_status is not None:
        updates.append("role_status = ?")
        params.append(req.role_status.upper())
    if req.school_organization is not None:
        updates.append("school_organization = ?")
        params.append(req.school_organization.strip())
    if req.photo_url is not None:
        updates.append("photo_url = ?")
        params.append(req.photo_url)
    if req.pin is not None and len(req.pin.strip()) >= 4:
        pin_hash, salt = hash_pin(req.pin.strip())
        updates.append("pin_hash = ?")
        updates.append("salt = ?")
        params.extend([pin_hash, salt])

    if updates:
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        prev_user_full = dict(cursor.fetchone())
        params.append(user_id)
        cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        log_audit(conn, admin["id"], admin["full_name"], "ADMIN_EDIT_USER", "USER", user_id, f"Updated user {target['full_name']}", previous_data=prev_user_full)
        conn.commit()

    conn.close()
    return {"success": True, "message": "User updated successfully."}

@router.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own active administrator account.")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name FROM users WHERE id = ?", (user_id,))
    target = cursor.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")

    target_name = target["full_name"]

    # 1. Cleanly nullify references in teams
    cursor.execute("UPDATE teams SET leader_id = NULL WHERE leader_id = ?", (user_id,))
    cursor.execute("UPDATE teams SET speaker1_id = NULL WHERE speaker1_id = ?", (user_id,))
    cursor.execute("UPDATE teams SET speaker2_id = NULL WHERE speaker2_id = ?", (user_id,))
    cursor.execute("UPDATE teams SET speaker3_id = NULL WHERE speaker3_id = ?", (user_id,))

    # 2. Delete judge assignments & notifications
    cursor.execute("DELETE FROM judge_notifications WHERE judge_id = ?", (user_id,))
    cursor.execute("DELETE FROM judge_assignments WHERE judge_id = ?", (user_id,))
    cursor.execute("UPDATE scorecards SET judge_id = NULL WHERE judge_id = ?", (user_id,))

    # 3. Delete active user sessions
    cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    # 4. Nullify actor in audit logs
    cursor.execute("UPDATE audit_logs SET actor_id = NULL WHERE actor_id = ?", (user_id,))

    # 5. Safely delete user
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    log_audit(conn, admin["id"], admin["full_name"], "ADMIN_DELETE_USER", "USER", user_id, f"Deleted member {target_name}")
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Member {target_name} deleted successfully."}
