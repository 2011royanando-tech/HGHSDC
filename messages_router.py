import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.database import get_db, log_audit
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/messages", tags=["Judge & Admin Communication"])

class SendMessageRequest(BaseModel):
    message: str
    match_id: Optional[int] = None
    room_info: Optional[str] = None
    is_urgent: Optional[bool] = False

class ReplyMessageRequest(BaseModel):
    reply: str

@router.get("/my-messages")
def get_my_messages(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, sender_id, sender_name, sender_role, message, reply, replied_at, is_resolved, created_at
        FROM judge_admin_messages
        WHERE sender_id = ?
        ORDER BY id DESC
    """, (user["id"],))
    rows = cursor.fetchall()
    conn.close()
    messages = []
    for r in rows:
        d = dict(r)
        d["timestamp"] = d.get("created_at") or ""
        d["admin_reply"] = d.get("reply") or ""
        messages.append(d)
    return {"success": True, "messages": messages}

@router.post("/send")
def send_message(req: SendMessageRequest, user: dict = Depends(get_current_user)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    msg_body = req.message.strip()
    if req.room_info:
        msg_body = f"[{req.room_info}] {msg_body}"
    cursor.execute("""
        INSERT INTO judge_admin_messages (sender_id, sender_name, sender_role, message, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user["id"], user["full_name"], user["role"], msg_body, now_str))
    msg_id = cursor.lastrowid
    log_audit(conn, user["id"], user["full_name"], "SEND_MESSAGE", "MESSAGE", msg_id, "Sent message to Tab Director")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Message sent to Tab Director.", "id": msg_id, "message_id": msg_id}

@router.get("/admin/all")
def get_all_messages(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.sender_id, m.sender_name, m.sender_role, m.message, m.reply, m.replied_at, m.is_resolved, m.created_at, u.whatsapp_number AS judge_phone
        FROM judge_admin_messages m
        LEFT JOIN users u ON m.sender_id = u.id
        ORDER BY m.is_resolved ASC, m.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    messages = []
    for r in rows:
        d = dict(r)
        d["judge_name"] = d.get("sender_name")
        d["timestamp"] = d.get("created_at") or ""
        d["admin_reply"] = d.get("reply") or ""
        messages.append(d)
    return {"success": True, "messages": messages}

@router.post("/admin/{message_id}/reply")
def reply_message(message_id: int, req: ReplyMessageRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        UPDATE judge_admin_messages
        SET reply = ?, replied_at = ?, is_resolved = 1
        WHERE id = ?
    """, (req.reply.strip(), now_str, message_id))
    log_audit(conn, admin["id"], admin["full_name"], "REPLY_MESSAGE", "MESSAGE", message_id, "Admin replied to adjudicator message")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Reply sent successfully."}
