from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
import os
import secrets
import db
import draw

CATEGORIES = ["U8", "U10", "U12", "U14"]

# Auth: set env vars for fixed passwords, otherwise auto-generate on startup
ADMIN_PASSWORD = os.getenv("TOURNAMENT_ADMIN_PW") or secrets.token_hex(4)
REFEREE_PASSWORD = os.getenv("TOURNAMENT_REFEREE_PW") or secrets.token_hex(4)
SESSION_SECRET = os.getenv("TOURNAMENT_SECRET") or secrets.token_hex(32)

AUTH_TIMEOUT = 1800  # 30 minutes


# ── Pydantic models ──

class PlayerCreate(BaseModel):
    name: str
    phone: str
    category: str
    birth_date: str | None = None


class ScoreUpdate(BaseModel):
    score1: int
    score2: int
    tb_score1: int | None = None
    tb_score2: int | None = None


class ImportCSV(BaseModel):
    csv_text: str
    category: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    print(f"\n{'='*50}")
    print(f"  管理员密码: {ADMIN_PASSWORD}")
    print(f"  裁判员密码: {REFEREE_PASSWORD}")
    print(f"{'='*50}\n")
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ═══════════════ Auth helpers ═══════════════

def check_auth(request: Request):
    """Return (role, username) or None if not authenticated/expired."""
    session = request.session
    role = session.get("role")
    ts = session.get("ts", 0)
    import time
    if role and (time.time() - ts) < AUTH_TIMEOUT:
        return role
    return None

def require_auth(request: Request):
    role = check_auth(request)
    if not role:
        raise HTTPException(401)
    return role

def require_role(request: Request, allowed: list[str]):
    role = require_auth(request)
    if role not in allowed:
        raise HTTPException(403)
    return role


# ═══════════════ Page Routes ═══════════════

@app.get("/")
def root():
    return RedirectResponse("/public")


@app.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("admin/login.html", {
        "request": request,
        "error": error,
    })


@app.post("/admin/login")
def login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        role = "admin"
    elif password == REFEREE_PASSWORD:
        role = "referee"
    else:
        return templates.TemplateResponse("admin/login.html", {
            "request": request,
            "error": "密码错误",
        }, status_code=401)

    import time
    request.session.update({"role": role, "ts": time.time()})
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    role = check_auth(request)
    if not role:
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "role": role,
    })


@app.get("/public", response_class=HTMLResponse)
def public_home(request: Request):
    try:
        counts = {c: db.get_player_count(c) for c in CATEGORIES}
        return templates.TemplateResponse("public/index.html", {
            "request": request,
            "categories": CATEGORIES,
            "counts": counts,
        })
    except Exception as e:
        import traceback
        return HTMLResponse(f"<h2>Error</h2><pre>{traceback.format_exc()}</pre>", status_code=500)


@app.get("/public/{category}", response_class=HTMLResponse)
def public_category(request: Request, category: str):
    if category not in CATEGORIES:
        raise HTTPException(404, "组别不存在")
    try:
        return templates.TemplateResponse("public/category.html", {
            "request": request,
            "category": category,
        })
    except Exception as e:
        return HTMLResponse(f"<h2>Error</h2><pre>{e}</pre>", status_code=500)


# ═══════════════ Player API ═══════════════

@app.get("/api/players")
def api_players(category: str = None):
    return db.get_players(category)


@app.get("/api/players/counts")
def api_player_counts():
    return {c: db.get_player_count(c) for c in CATEGORIES}


@app.post("/api/players")
def api_add_player(data: PlayerCreate, request: Request):
    require_role(request, ["admin"])
    if data.category not in CATEGORIES:
        raise HTTPException(400, "无效组别")
    if db.get_player_count(data.category) >= 16:
        raise HTTPException(400, f"{data.category} 组已满 16 人")
    pid = db.add_player(
        name=data.name,
        phone=data.phone,
        category=data.category,
        birth_date=data.birth_date,
    )
    return {"status": "ok", "id": pid}


@app.delete("/api/players/{player_id}")
def api_delete_player(player_id: int, request: Request):
    require_role(request, ["admin"])
    db.delete_player(player_id)
    return {"status": "ok"}


@app.post("/api/players/import")
def api_import_players(data: ImportCSV, request: Request):
    """Bulk import from CSV text. category='auto' reads from CSV column, otherwise forces target category."""
    require_role(request, ["admin"])
    import csv, io

    csv_text = data.csv_text
    force_cat = data.category  # 'auto' or specific category

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise HTTPException(400, "无法解析CSV，请确认格式正确")

    # Map Chinese headers
    col_map = {}
    for fn in reader.fieldnames:
        fn_clean = fn.strip().replace("'", "").replace("﻿", "")
        if "姓名" in fn_clean: col_map["name"] = fn
        elif "手机" in fn_clean or "电话" in fn_clean: col_map["phone"] = fn
        elif "组别" in fn_clean: col_map["category"] = fn
        elif "出生" in fn_clean or "日期" in fn_clean: col_map["birth_date"] = fn

    if "name" not in col_map or "phone" not in col_map:
        raise HTTPException(400, "CSV表头需包含「姓名」和「手机号」列")

    # Pre-load existing phones per category
    existing = {}
    for c in CATEGORIES:
        existing[c] = {p["phone"] for p in db.get_players(c)}

    quotas = {c: db.get_player_count(c) for c in CATEGORIES}

    result = {c: {"imported": 0, "skipped": 0} for c in CATEGORIES}
    errors = []

    for row_num, row in enumerate(reader, start=2):
        name = (row.get(col_map.get("name", "")) or "").strip()
        phone = (row.get(col_map.get("phone", "")) or "").strip()
        birth = (row.get(col_map.get("birth_date", "")) or "").strip()

        # Determine category
        if force_cat == "auto":
            cat_raw = (row.get(col_map.get("category", "")) or "").strip()
            # Extract category code from value (e.g. "U8（2018年...）" → "U8")
            cat = None
            for c in CATEGORIES:
                if cat_raw.startswith(c):
                    cat = c
                    break
            if not cat:
                errors.append(f"第{row_num}行: 无法识别组别'{cat_raw}'，跳过")
                continue
        else:
            cat = force_cat

        if cat not in CATEGORIES:
            errors.append(f"第{row_num}行: 无效组别'{cat}'，跳过")
            continue

        # Validate
        if not name or not phone:
            errors.append(f"第{row_num}行: 姓名或手机为空，跳过")
            continue
        if phone in existing[cat]:
            errors.append(f"第{row_num}行: {name} 已在{cat}组，跳过")
            continue
        if not phone.isdigit() or len(phone) != 11:
            errors.append(f"第{row_num}行: {name} 手机号格式不对，跳过")
            continue

        if quotas[cat] >= 16:
            result[cat]["skipped"] += 1
            continue

        db.add_player(name, phone, cat, birth if birth else None)
        existing[cat].add(phone)
        quotas[cat] += 1
        result[cat]["imported"] += 1

    # Build summary
    total_imported = sum(r["imported"] for r in result.values())
    total_skipped = sum(r["skipped"] for r in result.values())
    by_cat = {c: {"imported": result[c]["imported"], "remaining": 16 - quotas[c]}
              for c in CATEGORIES if result[c]["imported"] > 0 or result[c]["skipped"] > 0}

    return {
        "status": "ok",
        "imported": total_imported,
        "skipped": total_skipped,
        "by_category": by_cat,
        "errors": errors[:10],
    }

@app.post("/api/draw-groups/{category}")
def api_draw_groups(category: str, request: Request):
    require_role(request, ["admin"])
    if category not in CATEGORIES:
        raise HTTPException(400, "无效组别")
    if db.has_group_stage(category):
        raise HTTPException(400, "已分组，请先清除再重新抽签")

    players = db.get_players(category)
    if len(players) != 16:
        raise HTTPException(400, f"需要恰好 16 人，当前 {len(players)} 人")

    groups = draw.draw_groups([p["id"] for p in players])
    schedule = draw.round_robin_schedule()

    match_order = 0
    match_data = []
    for group_name in ["A", "B", "C", "D"]:
        pids = groups[group_name]  # 4 player ids
        for round_num, pairs in schedule:
            for pos1, pos2 in pairs:
                match_order += 1
                match_data.append({
                    "category": category,
                    "stage": "group",
                    "group_name": group_name,
                    "round": round_num,
                    "match_order": match_order,
                    "player1_id": pids[pos1 - 1],
                    "player2_id": pids[pos2 - 1],
                })

    db.create_matches_batch(match_data)

    # Return groups with player names
    player_map = {p["id"]: p["name"] for p in players}
    result = {}
    for g, pids in groups.items():
        result[g] = [{"id": pid, "name": player_map[pid]} for pid in pids]

    return {"status": "ok", "groups": result}


# ═══════════════ Match API ═══════════════

@app.get("/api/matches/{category}")
def api_matches(category: str, stage: str = None):
    if category not in CATEGORIES:
        raise HTTPException(400, "无效组别")
    return db.get_matches(category, stage)


@app.put("/api/matches/{match_id}/score")
def api_update_score(match_id: int, data: ScoreUpdate, request: Request):
    require_role(request, ["admin", "referee"])
    score1 = data.score1
    score2 = data.score2

    match = db.get_match(match_id)
    if not match:
        raise HTTPException(404, "比赛不存在")

    if score1 == score2:
        raise HTTPException(400, "比分不能相等，如2:2抢七决胜局分写3:2，抢七小分填在抢七栏")

    winner_id = match["player1_id"] if score1 > score2 else match["player2_id"]

    db.update_match_score(match_id, score1, score2, winner_id, data.tb_score1, data.tb_score2)

    # Auto-advance knockout winner to next round
    if winner_id and match["stage"] in ("quarterfinal", "semifinal"):
        _advance_winner(match["category"], match["stage"], match["match_order"], winner_id)

    return {"status": "ok", "winner_id": winner_id}


def _advance_winner(category: str, stage: str, match_order: int, winner_id: int):
    """After QF/SF completed, fill winner into next round's match."""
    matches = db.get_matches(category)
    knockout = [m for m in matches if m["stage"] != "group"]

    if stage == "quarterfinal":
        sf_order = 5 if match_order <= 2 else 6
        slot = "player1_id" if match_order in (1, 3) else "player2_id"
        target_stage = "semifinal"
    else:  # semifinal
        sf_order = 7
        slot = "player1_id" if match_order == 5 else "player2_id"
        target_stage = "final"

    target = next((m for m in knockout if m["stage"] == target_stage and m["match_order"] == sf_order), None)
    if target:
        db.update_match_player(target["id"], slot, winner_id)


# ═══════════════ Standings API ═══════════════

@app.get("/api/standings/{category}")
def api_standings(category: str):
    if category not in CATEGORIES:
        raise HTTPException(400, "无效组别")
    return db.get_group_standings(category)


# ═══════════════ Knockout API ═══════════════

@app.post("/api/draw-top8/{category}")
def api_draw_top8(category: str, request: Request):
    require_role(request, ["admin"])
    if category not in CATEGORIES:
        raise HTTPException(400, "无效组别")
    if not db.all_group_matches_done(category):
        raise HTTPException(400, "小组赛尚未全部完成，无法生成8强")
    if db.has_knockout_stage(category):
        raise HTTPException(400, "淘汰赛已生成，请先清除")

    standings = db.get_group_standings(category)
    # Extract A1, A2, B1, B2, C1, C2, D1, D2
    top2 = {}
    for g in ["A", "B", "C", "D"]:
        gs = standings.get(g, [])
        if len(gs) < 2:
            raise HTTPException(400, f"{g}组出线人数不足")
        top2[f"{g}1"] = gs[0]
        top2[f"{g}2"] = gs[1]

    # Fixed bracket: A1vsC2, B1vsD2, C1vsA2, D1vsB2
    matchups = [
        (top2["A1"]["player_id"], top2["C2"]["player_id"]),
        (top2["B1"]["player_id"], top2["D2"]["player_id"]),
        (top2["C1"]["player_id"], top2["A2"]["player_id"]),
        (top2["D1"]["player_id"], top2["B2"]["player_id"]),
    ]

    bracket = draw.generate_knockout_bracket(matchups)
    for m in bracket:
        m["category"] = category
    db.create_matches_batch(bracket)

    # Return with names
    players = {p["id"]: p["name"] for p in db.get_players(category)}
    qualifier_names = [
        {"group": "A1", "name": top2["A1"]["player_name"]},
        {"group": "A2", "name": top2["A2"]["player_name"]},
        {"group": "B1", "name": top2["B1"]["player_name"]},
        {"group": "B2", "name": top2["B2"]["player_name"]},
        {"group": "C1", "name": top2["C1"]["player_name"]},
        {"group": "C2", "name": top2["C2"]["player_name"]},
        {"group": "D1", "name": top2["D1"]["player_name"]},
        {"group": "D2", "name": top2["D2"]["player_name"]},
    ]
    return {
        "status": "ok",
        "matchups": [
            f"A1 {top2['A1']['player_name']} vs C2 {top2['C2']['player_name']}",
            f"B1 {top2['B1']['player_name']} vs D2 {top2['D2']['player_name']}",
            f"C1 {top2['C1']['player_name']} vs A2 {top2['A2']['player_name']}",
            f"D1 {top2['D1']['player_name']} vs B2 {top2['B2']['player_name']}",
        ],
    }


@app.get("/api/knockout/{category}")
def api_knockout(category: str):
    if category not in CATEGORIES:
        raise HTTPException(400, "无效组别")
    matches = db.get_matches(category)
    return [m for m in matches if m["stage"] != "group"]


# ═══════════════ Clear API ═══════════════

@app.post("/api/clear/{category}")
def api_clear(category: str, request: Request, stage: str = None):
    require_role(request, ["admin"])
    if category not in CATEGORIES:
        raise HTTPException(400, "无效组别")
    db.clear_matches(category, stage)
    return {"status": "ok"}


# ═══════════════ Run ═══════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
