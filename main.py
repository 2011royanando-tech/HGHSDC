import os
import csv
import io
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db, get_db
from app.auth import ensure_default_admin, get_current_user_optional, require_admin
from app.routers import (
    auth_router,
    members_router,
    teams_router,
    tournament_router,
    judging_router,
    scoring_router,
    results_router,
    timer_router,
    audit_router,
    senior_router,
    messages_router,
    notes_router
)

app = FastAPI(
    title="TRADITIONAL DEBATE TAB",
    description="Professional 16-Team Traditional Debate Tournament Operating System",
    version="2.0.0"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Register routers
app.include_router(auth_router.router)
app.include_router(members_router.router)
app.include_router(teams_router.router)
app.include_router(tournament_router.router)
app.include_router(judging_router.router)
app.include_router(scoring_router.router)
app.include_router(results_router.router)
app.include_router(timer_router.router)
app.include_router(audit_router.router)
app.include_router(senior_router.router)
app.include_router(messages_router.router)
app.include_router(notes_router.router)

@app.on_event("startup")
def on_startup():
    init_db()
    ensure_default_admin()

@app.get("/")
def index():
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    return FileResponse(index_path)

@app.get("/api/export/tournament-csv")
def export_tournament_csv(user: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.match_number, r.name AS round_name,
               t1.name AS team1_name, t1.custom_name AS team1_custom_name,
               t2.name AS team2_name, t2.custom_name AS team2_custom_name,
               m.team1_aggregate, m.team2_aggregate,
               w.name AS winner_name, w.custom_name AS winner_custom_name,
               m.tie_status, m.is_published
        FROM matches m
        JOIN rounds r ON m.round_id = r.id
        LEFT JOIN teams t1 ON m.team1_id = t1.id
        LEFT JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN teams w ON m.winner_id = w.id
        ORDER BY m.match_number ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Match Number", "Round", "Team 1", "Team 2", "Team 1 Aggregate", "Team 2 Aggregate", "Winner", "Tie Status", "Published"])
    for row in rows:
        r = dict(row)
        t1_str = f"{r['team1_name']} ({r['team1_custom_name']})" if r.get('team1_custom_name') else (r['team1_name'] or 'TBD')
        t2_str = f"{r['team2_name']} ({r['team2_custom_name']})" if r.get('team2_custom_name') else (r['team2_name'] or 'TBD')
        w_str = f"{r['winner_name']} ({r['winner_custom_name']})" if r.get('winner_custom_name') else (r['winner_name'] or '')
        writer.writerow([
            r["match_number"],
            r["round_name"],
            t1_str,
            t2_str,
            f"{r['team1_aggregate']:.2f}" if r["team1_aggregate"] is not None else "",
            f"{r['team2_aggregate']:.2f}" if r["team2_aggregate"] is not None else "",
            w_str,
            r["tie_status"] or "NONE",
            "YES" if r["is_published"] else "NO"
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tournament_results.csv"}
    )
