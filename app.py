from fastapi import FastAPI, Request, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
import os
import secrets
import json
import time
import csv
import io
import zipfile
import openpyxl
import db
import draw

CATEGORIES = ["U8", "U10", "U12", "U14"]

CATEGORY_CONFIG = {
    "U8":  {"max_players": 16, "group_names": ["A", "B", "C", "D"]},
    "U10": {"max_players": 16, "group_names": ["A", "B", "C", "D"]},
    "U12": {"max_players": 16, "group_names": ["A", "B", "C", "D"]},
    "U14": {"max_players": 8,  "group_names": ["A", "B"]},
}


def get_cat_cfg(category: str) -> dict:
    return CATEGORY_CONFIG[category]

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


class PlayerUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    birth_date: str | None = None


class ScoreUpdate(BaseModel):
    score1: int
    score2: int
    tb_score1: int | None = None
    tb_score2: int | None = None
    game_details: dict | None = None


class ImportCSV(BaseModel):
    csv_text: str
    category: str


class RefereeCreate(BaseModel):
    name: str


class RefereeUpdate(BaseModel):
    name: str | None = None
    active: int | None = None


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
templates.env.cache = None  # disable cache to avoid Jinja2 3.2 hash bug


# ═══════════════ Auth helpers ═══════════════

def check_auth(request: Request):
    """Return (role, username) or None if not authenticated/expired."""
    session = request.session
    role = session.get("role")
    ts = session.get("ts", 0)
    if role and (time.time() - ts) < AUTH_TIMEOUT:
        session["ts"] = time.time()  # rolling refresh
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
    return templates.TemplateResponse(request=request, name="admin/login.html", context={

        "error": error,
    })


@app.post("/admin/login")
def login(request: Request, password: str = Form(...), referee_name: str = Form("")):
    if password == ADMIN_PASSWORD:
        role = "admin"
        ref_name = "管理员"
    elif password == REFEREE_PASSWORD:
        role = "referee"
        ref_name = referee_name.strip()
        if not ref_name:
            return templates.TemplateResponse(request=request, name="admin/login.html", context={
                "error": "请选择裁判员姓名",
            }, status_code=401)
        # Verify name belongs to an active referee
        active_refs = {r["name"] for r in db.get_referees(active_only=True)}
        if ref_name not in active_refs:
            return templates.TemplateResponse(request=request, name="admin/login.html", context={
                "error": f"裁判员「{ref_name}」不存在或已停用",
            }, status_code=401)
    else:
        return templates.TemplateResponse(request=request, name="admin/login.html", context={
            "error": "密码错误",
        }, status_code=401)

    request.session.update({"role": role, "ts": time.time(), "referee_name": ref_name})
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
    return templates.TemplateResponse(request=request, name="admin/dashboard.html", context={
        "role": role,
        "referee_name": request.session.get("referee_name", ""),
    })


@app.get("/public", response_class=HTMLResponse)
def public_home(request: Request):
    try:
        counts = {c: db.get_player_count(c) for c in CATEGORIES}
        max_players = {c: get_cat_cfg(c)["max_players"] for c in CATEGORIES}
        return templates.TemplateResponse(request=request, name="public/index.html", context={
            "categories": CATEGORIES,
            "counts": counts,
            "max_players": max_players,
        })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        return HTMLResponse(f"<h2>Error</h2><pre>{tb}</pre>", status_code=500)


@app.get("/health")
def health():
    """Simple health check - no DB, no template"""
    return {"status": "ok"}


@app.get("/public/{category}", response_class=HTMLResponse)
def public_category(request: Request, category: str):
    if category not in CATEGORIES:
        raise HTTPException(404, "组别不存在")
    try:
        return templates.TemplateResponse(request=request, name="public/category.html", context={
            "category": category,
            "group_names": get_cat_cfg(category)["group_names"],
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
    cfg = get_cat_cfg(data.category)
    if db.get_player_count(data.category) >= cfg["max_players"]:
        raise HTTPException(400, f"{data.category} 组已满 {cfg['max_players']} 人")
    pid = db.add_player(
        name=data.name,
        phone=data.phone,
        category=data.category,
        birth_date=data.birth_date,
    )
    return {"status": "ok", "id": pid}


@app.put("/api/players/{player_id}")
def api_update_player(player_id: int, data: PlayerUpdate, request: Request):
    require_role(request, ["admin"])
    if data.name is not None and not data.name.strip():
        raise HTTPException(400, "姓名不能为空")
    if data.phone is not None and not data.phone.strip():
        raise HTTPException(400, "手机号不能为空")
    if not db.update_player(player_id, name=data.name, phone=data.phone, birth_date=data.birth_date):
        raise HTTPException(404, "球员不存在")
    return {"status": "ok"}


@app.delete("/api/players/{player_id}")
def api_delete_player(player_id: int, request: Request):
    require_role(request, ["admin"])
    db.delete_player(player_id)
    return {"status": "ok"}


@app.post("/api/players/import")
def api_import_players(data: ImportCSV, request: Request):
    """Bulk import from CSV text. category='auto' reads from CSV column, otherwise forces target category."""
    require_role(request, ["admin"])

    csv_text = data.csv_text
    force_cat = data.category  # 'auto' or specific category

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise HTTPException(400, "无法解析CSV，请确认格式正确")

    headers = list(reader.fieldnames)
    rows = list(reader)
    return _do_import_rows(rows, headers, force_cat)


def _do_import_rows(rows: list[dict], headers: list[str], force_cat: str):
    """Shared import logic for CSV and Excel rows. Returns result dict."""
    col_map = {}
    for fn in headers:
        fn_clean = fn.strip().replace("'", "").replace("﻿", "")
        if "姓名" in fn_clean: col_map["name"] = fn
        elif "手机" in fn_clean or "电话" in fn_clean: col_map["phone"] = fn
        elif "组别" in fn_clean: col_map["category"] = fn
        elif "出生" in fn_clean or "日期" in fn_clean: col_map["birth_date"] = fn

    if "name" not in col_map or "phone" not in col_map:
        raise HTTPException(400, "表头需包含「姓名」和「手机号」列")

    existing = {}
    for c in CATEGORIES:
        existing[c] = {p["phone"] for p in db.get_players(c)}

    quotas = {c: db.get_player_count(c) for c in CATEGORIES}
    result = {c: {"imported": 0, "skipped": 0} for c in CATEGORIES}
    errors = []

    for row_num, row in enumerate(rows, start=2):
        name = (row.get(col_map.get("name", "")) or "").strip()
        phone = (row.get(col_map.get("phone", "")) or "").strip()
        birth = (row.get(col_map.get("birth_date", "")) or "").strip()

        # Determine category
        if force_cat == "auto":
            cat_raw = (row.get(col_map.get("category", "")) or "").strip()
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

        if not name or not phone:
            errors.append(f"第{row_num}行: 姓名或手机为空，跳过")
            continue
        if phone in existing[cat]:
            errors.append(f"第{row_num}行: {name} 已在{cat}组，跳过")
            continue
        if not phone.isdigit() or len(phone) != 11:
            errors.append(f"第{row_num}行: {name} 手机号格式不对，跳过")
            continue

        cfg = get_cat_cfg(cat)
        if quotas[cat] >= cfg["max_players"]:
            result[cat]["skipped"] += 1
            continue

        db.add_player(name, phone, cat, birth if birth else None)
        existing[cat].add(phone)
        quotas[cat] += 1
        result[cat]["imported"] += 1

    total_imported = sum(r["imported"] for r in result.values())
    total_skipped = sum(r["skipped"] for r in result.values())
    by_cat = {c: {"imported": result[c]["imported"], "remaining": get_cat_cfg(c)["max_players"] - quotas[c]}
              for c in CATEGORIES if result[c]["imported"] > 0 or result[c]["skipped"] > 0}

    return {
        "status": "ok",
        "imported": total_imported,
        "skipped": total_skipped,
        "by_category": by_cat,
        "errors": errors[:10],
    }


@app.post("/api/players/import-file")
async def api_import_file(request: Request, file: UploadFile = File(...), category: str = Form("auto")):
    """Bulk import from uploaded CSV or Excel (.xlsx) file."""
    require_role(request, ["admin"])

    filename = (file.filename or "").lower()
    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件大小不能超过 10MB")

    if filename.endswith(".xlsx"):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except (zipfile.BadZipFile, Exception) as e:
            raise HTTPException(400, f"无法解析Excel文件，请确认是有效的 .xlsx 文件")
        try:
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header_row = next(rows_iter)
            except StopIteration:
                raise HTTPException(400, "Excel文件为空（无表头行）")
            headers = [str(h or "").strip() for h in header_row]
            rows = []
            for r in rows_iter:
                rows.append({headers[i]: (str(r[i]) if i < len(r) and r[i] is not None else "") for i in range(len(headers))})
        finally:
            wb.close()
    elif filename.endswith(".csv"):
        # Try UTF-8-BOM first, then GBK (common for Chinese Excel exports)
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("gbk")
            except UnicodeDecodeError as e:
                raise HTTPException(400, f"无法识别CSV文件编码，请保存为 UTF-8 格式: {e}")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(400, "无法解析CSV，请确认格式正确")
        headers = list(reader.fieldnames)
        rows = list(reader)
    else:
        raise HTTPException(400, "仅支持 .csv 或 .xlsx 文件")

    if not rows:
        raise HTTPException(400, "文件内容为空")

    return _do_import_rows(rows, headers, category)

@app.post("/api/draw-groups/{category}")
def api_draw_groups(category: str, request: Request):
    require_role(request, ["admin"])
    if category not in CATEGORIES:
        raise HTTPException(400, "无效组别")
    if db.has_group_stage(category):
        raise HTTPException(400, "已分组，请先清除再重新抽签")

    cfg = get_cat_cfg(category)
    players = db.get_players(category)
    if len(players) != cfg["max_players"]:
        raise HTTPException(400, f"需要恰好 {cfg['max_players']} 人，当前 {len(players)} 人")

    groups = draw.draw_groups([p["id"] for p in players], cfg["group_names"])
    schedule = draw.round_robin_schedule()

    match_order = 0
    match_data = []
    for group_name in cfg["group_names"]:
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

    if score1 == score2 and (data.tb_score1 is None or data.tb_score2 is None):
        raise HTTPException(400, "比分不能相等，如2:2抢七决胜局分写2:2，抢七小分填在抢七栏")

    if data.tb_score1 is not None and data.tb_score2 is not None:
        winner_id = match["player1_id"] if data.tb_score1 > data.tb_score2 else match["player2_id"]
    else:
        winner_id = match["player1_id"] if score1 > score2 else match["player2_id"]

    # Scorer identity always comes from the session (set at login)
    scored_by = request.session.get("referee_name", "")

    db.update_match_score(match_id, score1, score2, winner_id, data.tb_score1, data.tb_score2,
                          json.dumps(data.game_details) if data.game_details else None,
                          scored_by=scored_by)

    # Auto-advance knockout winner to next round
    if winner_id and match["stage"] in ("quarterfinal", "semifinal"):
        _advance_winner(match["category"], match["stage"], match["match_order"], winner_id)

    return {"status": "ok", "winner_id": winner_id, "scored_by": scored_by}


@app.delete("/api/matches/{match_id}/score")
def api_reset_score(match_id: int, request: Request):
    require_role(request, ["admin"])
    match = db.get_match(match_id)
    if not match:
        raise HTTPException(404, "比赛不存在")
    # Cascade: if this is a QF/SF, clear the winner from downstream matches
    if match["stage"] in ("quarterfinal", "semifinal") and match["status"] == "completed":
        _clear_downstream(match["category"], match["stage"], match["match_order"])
    db.reset_match_score(match_id)
    return {"status": "ok"}


def _clear_downstream(category: str, stage: str, match_order: int):
    """When resetting a QF/SF, clear the winner slot in the downstream match
    and reset any completed downstream matches to prevent stale scores.
    Cascades all the way to the final if needed."""
    matches = db.get_matches(category)
    knockout = [m for m in matches if m["stage"] != "group"]
    n_groups = len(get_cat_cfg(category)["group_names"])

    # Determine immediate downstream target
    target_stage = None
    target_order = None
    slot = None

    if stage == "quarterfinal":
        target_stage = "semifinal"
        target_order = 5 if match_order <= 2 else 6
        slot = "player1_id" if match_order in (1, 3) else "player2_id"
    elif stage == "semifinal":
        target_stage = "final"
        if n_groups == 2:
            # SF 1(A1vsB2) → Final-3 player1, SF 2(B1vsA2) → Final-3 player2
            target_order = 3
            slot = "player1_id" if match_order == 1 else "player2_id"
        else:
            target_order = 7
            slot = "player1_id" if match_order == 5 else "player2_id"

    if not target_stage:
        return

    target = next((m for m in knockout if m["stage"] == target_stage and m["match_order"] == target_order), None)
    if not target:
        return

    was_completed = target["status"] == "completed"
    if was_completed:
        db.reset_match_score(target["id"])
    db.update_match_player(target["id"], slot, None)

    # Cascade: QF → SF → Final
    if stage == "quarterfinal":
        sf_match = target
        final = next((m for m in knockout if m["stage"] == "final"), None)
        if final:
            final_slot = "player1_id" if sf_match["match_order"] == 5 else "player2_id"
            if final[final_slot] is not None:
                db.update_match_player(final["id"], final_slot, None)
            if final["status"] == "completed":
                db.reset_match_score(final["id"])
    elif stage == "semifinal":
        # For both 2-group and 4-group: SF cleared, also reset Final if completed
        final = next((m for m in knockout if m["stage"] == "final"), None)
        if final and final["status"] == "completed":
            db.reset_match_score(final["id"])


def _advance_winner(category: str, stage: str, match_order: int, winner_id: int):
    """After QF/SF completed, fill winner into next round's match."""
    matches = db.get_matches(category)
    knockout = [m for m in matches if m["stage"] != "group"]
    n_groups = len(get_cat_cfg(category)["group_names"])

    target_stage = None
    target_order = None
    slot = None

    if stage == "quarterfinal":
        target_stage = "semifinal"
        target_order = 5 if match_order <= 2 else 6
        slot = "player1_id" if match_order in (1, 3) else "player2_id"
    elif stage == "semifinal":
        target_stage = "final"
        if n_groups == 2:
            target_order = 3
            slot = "player1_id" if match_order == 1 else "player2_id"
        else:
            target_order = 7
            slot = "player1_id" if match_order == 5 else "player2_id"

    if target_stage:
        target = next((m for m in knockout if m["stage"] == target_stage and m["match_order"] == target_order), None)
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
        raise HTTPException(400, "小组赛尚未全部完成，无法生成淘汰赛")
    if db.has_knockout_stage(category):
        raise HTTPException(400, "淘汰赛已生成，请先清除")

    cfg = get_cat_cfg(category)
    gn = cfg["group_names"]

    standings = db.get_group_standings(category)
    top2 = {}
    for g in gn:
        gs = standings.get(g, [])
        if len(gs) < 2:
            raise HTTPException(400, f"{g}组出线人数不足")
        top2[f"{g}1"] = gs[0]
        top2[f"{g}2"] = gs[1]

    bracket = draw.generate_knockout_bracket(top2, gn)
    for m in bracket:
        m["category"] = category
    db.create_matches_batch(bracket)

    # Return with names
    qualifier_names = []
    for g in gn:
        for rank in ["1", "2"]:
            qualifier_names.append({"group": f"{g}{rank}", "name": top2[f"{g}{rank}"]["player_name"]})

    matchup_labels = []
    if len(gn) == 4:
        matchup_labels = [
            f"A1 {top2['A1']['player_name']} vs C2 {top2['C2']['player_name']}",
            f"B1 {top2['B1']['player_name']} vs D2 {top2['D2']['player_name']}",
            f"C1 {top2['C1']['player_name']} vs A2 {top2['A2']['player_name']}",
            f"D1 {top2['D1']['player_name']} vs B2 {top2['B2']['player_name']}",
        ]
    else:
        matchup_labels = [
            f"A1 {top2['A1']['player_name']} vs B2 {top2['B2']['player_name']}",
            f"B1 {top2['B1']['player_name']} vs A2 {top2['A2']['player_name']}",
        ]

    return {
        "status": "ok",
        "matchups": matchup_labels,
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


# ═══════════════ Referee API ═══════════════

@app.get("/api/referees")
def api_referees(request: Request, active_only: bool = False):
    # active_only=true is used by the login page dropdown — allow unauthenticated
    # full list requires admin (contains inactive referees, timestamps, score counts)
    if not active_only:
        require_role(request, ["admin"])
    refs = db.get_referees(active_only=active_only)
    # When unauthenticated, only expose names (login page dropdown)
    if not check_auth(request):
        refs = [{"name": r["name"]} for r in refs]
    return refs


@app.post("/api/referees")
def api_add_referee(data: RefereeCreate, request: Request):
    require_role(request, ["admin"])
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")
    try:
        rid = db.add_referee(name)
        return {"status": "ok", "id": rid}
    except Exception as e:
        raise HTTPException(400, f"添加失败：{e}")


@app.put("/api/referees/{referee_id}")
def api_update_referee(referee_id: int, data: RefereeUpdate, request: Request):
    require_role(request, ["admin"])
    name = data.name.strip() if data.name else None
    active = data.active
    if active is not None and active not in (0, 1):
        raise HTTPException(400, "active 必须为 0 或 1")
    if not db.update_referee(referee_id, name=name, active=active):
        raise HTTPException(404, "裁判员不存在")
    return {"status": "ok"}


@app.delete("/api/referees/{referee_id}")
def api_delete_referee(referee_id: int, request: Request):
    require_role(request, ["admin"])
    if not db.delete_referee(referee_id):
        raise HTTPException(400, "无法删除：裁判员不存在或已有记分记录")
    return {"status": "ok"}


# ═══════════════ Run ═══════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
