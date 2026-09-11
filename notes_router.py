import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/api/notes", tags=["Private Handnotes"])

class SaveNoteRequest(BaseModel):
    text_content: Optional[str] = None
    canvas_data: Optional[str] = None
    table_data: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    title: Optional[str] = None

@router.get("/my-notes")
def get_my_notes(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT text_content, canvas_data, table_data, updated_at
        FROM user_notes
        WHERE user_id = ?
    """, (user["id"],))
    row = cursor.fetchone()
    conn.close()
    
    d = dict(row) if row else {"text_content": "", "canvas_data": "", "table_data": "", "updated_at": ""}
    notes_list = [
        {"category": "general", "content": d.get("text_content") or ""},
        {"category": "canvas", "content": d.get("canvas_data") or ""},
        {"category": "matrix", "content": d.get("table_data") or ""}
    ]
    return {
        "success": True,
        "notes": notes_list,
        "data": d,
        "text_content": d.get("text_content") or "",
        "canvas_data": d.get("canvas_data") or "",
        "table_data": d.get("table_data") or ""
    }

@router.post("/save")
def save_my_notes(req: SaveNoteRequest, user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT text_content, canvas_data, table_data FROM user_notes WHERE user_id = ?", (user["id"],))
    existing = cursor.fetchone()
    current_text = existing["text_content"] if existing else ""
    current_canvas = existing["canvas_data"] if existing else ""
    current_table = existing["table_data"] if existing else ""

    if req.category == "general" or req.category == "text":
        current_text = req.content if req.content is not None else ""
    elif req.category == "canvas":
        current_canvas = req.content if req.content is not None else ""
    elif req.category == "matrix":
        current_table = req.content if req.content is not None else ""
    else:
        if req.text_content is not None:
            current_text = req.text_content
        if req.canvas_data is not None:
            current_canvas = req.canvas_data
        if req.table_data is not None:
            current_table = req.table_data

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO user_notes (user_id, text_content, canvas_data, table_data, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            text_content = excluded.text_content,
            canvas_data = excluded.canvas_data,
            table_data = excluded.table_data,
            updated_at = excluded.updated_at
    """, (user["id"], current_text, current_canvas, current_table, now_str))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Handnote securely synchronized."}
