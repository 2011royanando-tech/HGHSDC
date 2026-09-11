from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db, log_audit
from app.auth import get_current_user, require_admin
from app.models import TimerSettingsRequest

router = APIRouter(prefix="/api/timer", tags=["Timer"])

@router.get("/settings")
def get_timer_settings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM timer_settings ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {
            "speaking_time_seconds": 180,
            "warning_1_seconds": 120,
            "warning_2_seconds": 150,
            "final_bell_seconds": 180,
            "sound_enabled": 1
        }
    return dict(row)

@router.post("/settings")
def update_timer_settings(req: TimerSettingsRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE timer_settings
        SET speaking_time_seconds = ?, warning_1_seconds = ?, warning_2_seconds = ?,
            final_bell_seconds = ?, sound_enabled = ?
    """, (req.speaking_time_seconds, req.warning_1_seconds, req.warning_2_seconds, req.final_bell_seconds, req.sound_enabled))
    log_audit(conn, admin["id"], admin["full_name"], "UPDATE_TIMER_SETTINGS", "TIMER", "CONFIG",
              f"Timer updated: {req.speaking_time_seconds}s total, w1={req.warning_1_seconds}s, w2={req.warning_2_seconds}s")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Timer settings updated successfully."}
