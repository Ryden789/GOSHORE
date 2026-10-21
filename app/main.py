"""GOSHORE 本地 Web 服务入口。"""
from __future__ import annotations

import datetime
import json
import mimetypes
import os
import shutil
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

# PWA（功能 3.1）：.webmanifest 需专用 MIME，否则浏览器拒绝安装
mimetypes.add_type("application/manifest+json", ".webmanifest")

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import ai, db, essay_rubric, formula_drill, importer, interview, knowledge, planner, share, speedcalc, variant, wordfill, argument, zy_notes, xingce_notes, cube_vision, sync_webdav
from .config import (STATIC_DIR, DATA_DIR, DB_PATH, SETTINGS_PATH, BASE_DIR, REMINDER_KEYS,
                     GOAL_KEYS, load_settings, reminder_patch, goal_patch,
                     save_settings, SYNC_KEYS, sync_patch, SYNC_REMOTE_DEFAULT)
# 可打印导出页（G5）：与手机端 goshor_server.py 共用同一份拼装逻辑。
# esc/rich_text 也从这里引入，别再在本模块另写一份（会漂移）。
from .print_export import esc, rich_text, render_html


# 存储残缺（只剩一半库）时记录原因，lifespan 捕获 StorageBroken 时写入，
# 由 /api/health 暴露出去——排查「题库突然空了」时一眼看到真正原因。
_STORAGE_ERROR: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # 全新安装：先把内置示例题库放到位，免得开箱就是「题库 0 道」。
        # 只在老库/新库都不存在时生效，已有数据的用户完全不受影响。
        if db.seed_sample():
            print("[seed] 已放置内置示例题库（可在「导入」里换成自己的题源）")
        db.init_db(db.connect())
        # 首次启动自动构建索引（库为空时）
        conn = db.connect()
        n = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        conn.close()
        if n == 0:
            # 首次启动的自动建索引是「锦上添花」：用户没配 vault、vault 很大、
            # 或某个文件解析炸了，都不能让整个服务起不来（窗口会白屏）。
            try:
                db.reindex()
            except Exception as e:  # noqa: BLE001
                print(f"[reindex] 首次建索引跳过：{e}")
        _startup_selfcheck()
    except db.StorageBroken as e:
        # 存储残缺时**仍然把服务起起来**：窗口能打开、页面能把这条原因显示给
        # 用户（各数据接口会统一返回 503 + 这个说明）。比进程直接退出、窗口
        # 一闪而过好得多——后者用户只会以为软件坏了。
        print("\033[91m" + "=" * 60)
        print(str(e))
        print("=" * 60 + "\033[0m")
        _STORAGE_ERROR.clear()
        _STORAGE_ERROR.update(msg=str(e))
    yield
    # 退出前给后台掌握度衰减（建议9）一点时间收尾，避免留下半截批次
    try:
        db.wait_decay_bg(2.0)
    except Exception:  # noqa: BLE001  存储残缺时收尾也可能失败
        pass


def _startup_selfcheck() -> None:
    """启动时自检核心数据接口，失败项用红色标注但不阻断启动。

    逐项打印（含通过项）——这样「自检输出包含哪些项」本身是可观测的，
    新增模块（面试 / 时政）有没有被覆盖，看启动日志即可确认（建议7）。
    """
    checks = [
        ("题库 facets", lambda: db.facets()),
        ("试卷列表 list_exams", lambda: db.list_exams()),
        ("设置 load_settings", lambda: load_settings()),
        # 建议7：新模块（面试 / 时政）的表可访问性，沿用 facets/list_exams 的检查模式。
        # 空表返回 [] 不算失败——这里只验证「表存在且可查询」，不是验证「有没有内容」。
        ("面试题库 list_interview_questions", lambda: db.list_interview_questions()),
        ("面试分类 interview_category_counts", lambda: db.interview_category_counts()),
        ("时政库 list_shizheng", lambda: db.list_shizheng()),
    ]
    ok, fail = 0, 0
    for name, fn in checks:
        try:
            r = fn()
            if r is None:
                raise RuntimeError("返回 None")
            ok += 1
            print(f"\033[92m  [ OK ] {name}\033[0m")
        except Exception as e:
            fail += 1
            print(f"\033[91m  [FAIL] {name}: {e}\033[0m")
    status = "\033[92m全部通过\033[0m" if fail == 0 else f"\033[91m{fail} 项失败\033[0m"
    print(f"  启动自检: {ok}/{ok + fail} 通过 · {status}")


app = FastAPI(title="GOSHORE 上岸", lifespan=lifespan)


@app.exception_handler(db.StorageBroken)
async def _storage_broken_handler(_request: Request, exc: db.StorageBroken):
    """题库库/个人库只剩一半时，给前端一条能读懂的话，而不是 500 栈。

    桌面窗口里会直接渲染这段文字：用户看到的是「content.db 缺失，怎么恢复」，
    而不是「Internal Server Error」。
    """
    return JSONResponse(
        status_code=503,
        content={"ok": False, "storage_broken": True, "detail": str(exc)},
    )

# 允许本地 file:// 演示页（Origin: null）调用 open_app 接口
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null", "http://127.0.0.1:8765", "http://localhost:8765"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
except Exception:
    pass


@app.get("/api/health")
def api_health():
    """轻量探活：演示页用它发现本地服务实际使用的端口。

    `storage` 顺带暴露存储形态（split / legacy / broken），排查「题库突然空了」
    时不用再去翻日志：broken 就是 content.db 丢了，不是数据被删。
    """
    try:
        state = db.split_state()
    except Exception:  # noqa: BLE001  探活接口不能因为存储异常而 500
        state = "unknown"
    out = {"ok": True, "app": "goshore", "storage": state}
    if _STORAGE_ERROR.get("msg"):
        out["storage_error"] = _STORAGE_ERROR["msg"]
    return out


# ---------------- 一键拉起模拟器 APP ----------------

_OPEN_APP_LOCK = threading.Lock()
_OPEN_APP = {"state": "idle", "msg": "", "started": 0.0}
_EMULATOR_BOOT_TIMEOUT = 300.0      # 冷启动模拟器最长等待（秒）
_MUMU_BOOT_TIMEOUT = 180.0          # 冷启动 MuMu 模拟器最长等待（秒）
_MUMU_ADB_PORTS = (16384, 7555)     # MuMu 12/15 与 MuMu 6 的 adb 端口
_BAT_TIMEOUT = 180.0                # 安装 APK + 拉起 Activity 的兜底超时


def _first_existing(paths):
    for p in paths:
        if not p:
            continue
        try:
            if Path(p).exists():
                return Path(p)
        except OSError:
            continue
    return None


def _sdk_roots():
    """候选 SDK 根目录：仓库内置 → 环境变量 → 用户默认安装位置。"""
    roots = [BASE_DIR / ".android-sdk"]
    for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        val = os.environ.get(key)
        if val:
            roots.append(Path(val))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Android" / "Sdk")
    return roots


def _adb_path():
    found = _first_existing(
        [Path(r"D:\platform-tools-latest-windows\platform-tools\adb.exe")]
        + [r / "platform-tools" / "adb.exe" for r in _sdk_roots()]
    )
    if found:
        return found
    which = shutil.which("adb")
    return Path(which) if which else None


def _emulator_path():
    found = _first_existing([r / "emulator" / "emulator.exe" for r in _sdk_roots()])
    if found:
        return found
    which = shutil.which("emulator")
    return Path(which) if which else None


def _mumu_cli():
    """网易 MuMu 模拟器的命令行工具；装了就能用它拉起安卓实例。"""
    cands = []
    home = os.environ.get("MUMU_HOME")
    if home:
        cands.append(Path(home) / "nx_main" / "mumu-cli.exe")
    for drive in ("C:", "D:", "E:", "F:"):
        for base in ("Program Files", "Program Files (x86)"):
            # 必须带分隔符：Path("D:") / "x" 得到的是盘符相对路径 "D:x"
            cands.append(Path(f"{drive}\\{base}\\Netease\\MuMu\\nx_main\\mumu-cli.exe"))
    return _first_existing(cands)


def _mumu_launch(cli):
    """拉起 MuMu 的 0 号实例（已在运行时不报错）。"""
    try:
        proc = _run([str(cli), "control", "--vmindex", "0", "launch"],
                    timeout=90, cwd=str(cli.parent))
    except Exception:
        return False
    out = (proc.stdout or b"").decode("utf-8", "ignore")
    return '"errcode": 0' in out or proc.returncode == 0


def _mumu_connect(adb, deadline, elapsed):
    """MuMu 启动后逐端口 adb connect，直到设备就绪并开机完成。"""
    while time.time() < deadline:
        for port in _MUMU_ADB_PORTS:
            try:
                _run([str(adb), "connect", f"127.0.0.1:{port}"], timeout=15)
            except Exception:
                pass
        found = _devices(adb)
        if found and _boot_completed(adb, found[0]):
            return found[0]
        _set_open_state("booting", f"MuMu 模拟器正在启动… 已等待 {elapsed()} 秒")
        time.sleep(4)
    return None


def _run(cmd, timeout=30, **kw):
    return subprocess.run(cmd, capture_output=True, timeout=timeout, **kw)


def _devices(adb):
    """处于 device 状态（已连接且已授权）的序列号列表。"""
    try:
        proc = _run([str(adb), "devices"], timeout=20)
    except Exception:
        return []
    out = (proc.stdout or b"").decode("utf-8", "ignore")
    serials = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _boot_completed(adb, serial):
    try:
        proc = _run([str(adb), "-s", serial, "shell", "getprop", "sys.boot_completed"],
                    timeout=15)
        return (proc.stdout or b"").decode("utf-8", "ignore").strip() == "1"
    except Exception:
        return False


def _list_avds(emu):
    try:
        proc = _run([str(emu), "-list-avds"], timeout=25, cwd=str(emu.parent))
        out = (proc.stdout or b"").decode("utf-8", "ignore")
        return [ln.strip() for ln in out.splitlines()
                if ln.strip() and not ln.strip().startswith("INFO")]
    except Exception:
        return []


def _set_open_state(state, msg):
    with _OPEN_APP_LOCK:
        _OPEN_APP["state"] = state
        _OPEN_APP["msg"] = msg


def _apk_path():
    """优先用 dist 下最新的发布 APK，其次退到构建产物。"""
    cands = []
    dist = BASE_DIR / "dist"
    if dist.is_dir():
        try:
            cands.extend(sorted(dist.glob("goshor-*.apk"),
                                key=lambda p: p.stat().st_mtime, reverse=True))
        except OSError:
            pass
    cands.append(BASE_DIR / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk")
    return _first_existing(cands)


def _launch_apk(adb, serial):
    """装 APK（未安装时）并拉起 MainActivity。"""
    installed = False
    try:
        proc = _run([str(adb), "-s", serial, "shell", "pm", "list", "packages",
                     "com.goshor.app"], timeout=30)
        installed = "com.goshor.app" in (proc.stdout or b"").decode("utf-8", "ignore")
    except Exception:
        pass
    if not installed:
        apk = _apk_path()
        if apk is None:
            return False, "找不到可安装的 APK（dist/goshor-*.apk 或 app-debug.apk）"
        try:
            _run([str(adb), "-s", serial, "install", "-r", "-d", str(apk)],
                 timeout=_BAT_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, "APK 安装超时（约 286 MB），请稍后重试"
        except Exception as exc:
            return False, f"APK 安装失败：{exc}"
    try:
        proc = _run([str(adb), "-s", serial, "shell", "am", "start", "-n",
                     "com.goshor.app/.MainActivity"], timeout=60)
    except Exception as exc:
        return False, f"启动 APP 失败：{exc}"
    out = ((proc.stdout or b"") + (proc.stderr or b"")).decode("utf-8", "ignore")
    if "Error" in out or "Exception" in out:
        return False, f"启动 APP 失败：{out.strip()[:120]}"
    return True, "APP 已启动"


def _open_app_worker():
    try:
        _open_app_pipeline()
    except Exception as exc:            # 后台线程不得静默死掉
        _set_open_state("error", f"启动流程异常：{exc}")


def _boot_avd(adb, elapsed):
    """退回 Android SDK 自带模拟器；失败时把原因写进状态并返回 None。"""
    emu = _emulator_path()
    if emu is None:
        _set_open_state("error", "未找到可用的安卓模拟器（MuMu 或 emulator.exe），请先安装其中之一")
        return None
    avds = _list_avds(emu)
    if not avds:
        _set_open_state("error", "没有可用的安卓虚拟设备（AVD），请先在 Android Studio 中创建")
        return None
    avd = avds[0]
    _set_open_state("booting", f"正在启动模拟器「{avd}」，首次启动约需 1-3 分钟…")
    try:
        subprocess.Popen(
            [str(emu), "-avd", avd, "-no-snapshot", "-no-audio",
             "-gpu", "swiftshader_indirect"],
            cwd=str(emu.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as exc:
        _set_open_state("error", f"模拟器启动失败：{exc}")
        return None
    deadline = time.time() + _EMULATOR_BOOT_TIMEOUT
    while time.time() < deadline:
        time.sleep(3)
        found = _devices(adb)
        if found and _boot_completed(adb, found[0]):
            return found[0]
        _set_open_state("booting", f"正在启动模拟器「{avd}」… 已等待 {elapsed()} 秒")
    _set_open_state("error",
                    f"模拟器 {int(_EMULATOR_BOOT_TIMEOUT)} 秒内未完成启动。"
                    "若模拟器窗口一出现即无响应，说明本机 Android Emulator 引擎异常，"
                    "请重装 emulator 包，或改用其他模拟器（如 MuMu）／网页版。")
    return None


def _open_app_pipeline():
    adb = _adb_path()
    if adb is None:
        _set_open_state("error", "未找到 adb，请安装 Android platform-tools")
        return
    try:
        _run([str(adb), "start-server"], timeout=30)
    except Exception:
        pass

    def elapsed():
        return int(time.time() - _OPEN_APP["started"])

    serials = _devices(adb)
    serial = serials[0] if serials else None

    if not serial:
        # 优先用 MuMu：它比 Android SDK 自带模拟器启动快、兼容性好
        cli = _mumu_cli()
        if cli is not None:
            _set_open_state("booting", "正在启动 MuMu 模拟器…")
            if _mumu_launch(cli):
                serial = _mumu_connect(adb, time.time() + _MUMU_BOOT_TIMEOUT, elapsed)
            if not serial:
                _set_open_state("booting", "MuMu 未能启动，尝试 Android 虚拟设备（AVD）…")
        if not serial:
            serial = _boot_avd(adb, elapsed)
        if not serial:
            return

    _set_open_state("launching", f"设备已就绪（{serial}），正在安装并打开 APP…")
    ok, msg = _launch_apk(adb, serial)
    _set_open_state("done" if ok else "error", msg)


@app.post("/api/open_app")
def api_open_app():
    """异步拉起模拟器 + APP。立即返回，进度用 /api/open_app/status 轮询。"""
    with _OPEN_APP_LOCK:
        state = str(_OPEN_APP["state"])
        if state in ("booting", "launching"):
            started = float(_OPEN_APP["started"])
            return {"ok": True, "state": state, "msg": str(_OPEN_APP["msg"]),
                    "elapsed": int(time.time() - started), "reused": True}
        _OPEN_APP["state"] = "booting"
        _OPEN_APP["msg"] = "正在检查设备…"
        _OPEN_APP["started"] = time.time()
    threading.Thread(target=_open_app_worker, daemon=True).start()
    return {"ok": True, "state": "booting", "msg": "正在检查设备…",
            "elapsed": 0, "reused": False}


@app.get("/api/open_app/status")
def api_open_app_status():
    """返回当前拉起进度：idle / booting / launching / done / error。"""
    with _OPEN_APP_LOCK:
        state = str(_OPEN_APP["state"])
        msg = str(_OPEN_APP["msg"])
        started = float(_OPEN_APP["started"])
    return {"ok": state in ("booting", "launching", "idle", "done"),
            "state": state, "msg": msg,
            "elapsed": int(time.time() - started) if started else 0}


# ---------------- 题库 ----------------

@app.get("/api/facets")
def api_facets():
    return db.facets()


class SearchIn(BaseModel):
    q: str = ""
    kind: str = ""
    module: str = ""
    daclass: str = ""
    region: str = ""
    year: str = ""
    page: int = 1
    page_size: int = 20


@app.post("/api/search")
def api_search(b: SearchIn):
    rows, total = db.search_docs(
        q=b.q, kind=b.kind, module=b.module, daclass=b.daclass,
        region=b.region, year=b.year, page=b.page, page_size=b.page_size,
    )
    return {"items": rows, "total": total, "page": b.page}


@app.get("/api/doc/{doc_id}")
def api_doc(doc_id: int):
    d = db.get_doc(doc_id)
    if not d:
        raise HTTPException(404)
    return d


class BatchDocsIn(BaseModel):
    ids: list[int]


@app.post("/api/docs/batch")
def api_docs_batch(b: BatchDocsIn):
    """批量获取题目详情（用于组卷/套卷加载，减少并发请求）"""
    return {"items": db.get_docs_batch(b.ids)}


@app.get("/api/doc-by-qid/{qid}")
def api_doc_by_qid(qid: str):
    did = db.doc_id_by_qid(qid)
    if did is None:
        raise HTTPException(404)
    return {"doc_id": did}


class AnswerIn(BaseModel):
    doc_id: int
    selected: str = ""
    correct: bool = False
    ms: int = 0
    guessed: bool = False


@app.post("/api/answer")
def api_answer(b: AnswerIn):
    db.add_answer(b.doc_id, b.selected, b.correct, b.ms, b.guessed)
    return {"ok": True}


class BatchAnswerIn(BaseModel):
    items: list[AnswerIn] = []


@app.post("/api/answer/batch")
def api_answer_batch(b: BatchAnswerIn):
    """考场模式：交卷时一次性落库本卷全部作答（延迟结算，不再一题一判）。"""
    n = 0
    annihilated: list[int] = []
    for it in b.items:
        info = db.add_answer(it.doc_id, it.selected, it.correct, it.ms, it.guessed)
        n += 1
        if info.get("annihilated"):
            annihilated.append(it.doc_id)
    return {"ok": True, "n": n, "annihilated": annihilated}


class MarkIn(BaseModel):
    doc_id: int
    mark: str = ""


@app.post("/api/mark")
def api_mark(b: MarkIn):
    db.set_mark(b.doc_id, b.mark)
    return {"ok": True}


@app.post("/api/reindex")
def api_reindex():
    return db.reindex()


@app.post("/api/difficulty/tag")
def api_difficulty_tag():
    """手动触发难度批量打标（关键词启发式）。"""
    return db.tag_difficulty_batch()


# ---------------- 图片代理（限定 vault 内） ----------------

# 只放行真正的图片类型：vault 里可能混着 md / json / zip，不能让 /img 变成文件读取器。
_IMG_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico",
})


@app.get("/img")
def api_img(path: str):
    import urllib.parse
    path = urllib.parse.unquote(path)
    # 未配置 vault 时必须直接拒绝：Path("") == Path(".")，而 Path("").exists()
    # 恒为 True，越界校验会退化成「不许出当前工作目录」，等于把整个程序目录
    # （含 data/settings.json、data/goshor.db）暴露给局域网任意设备。
    raw = (load_settings().get("vault_path") or "").strip()
    if not raw:
        raise HTTPException(404, "尚未设置题库源目录")
    vault = Path(raw).resolve()
    if not vault.is_dir():
        raise HTTPException(404, "题库源目录不存在")
    fp = (vault / path).resolve()
    try:
        fp.relative_to(vault)
    except ValueError:
        raise HTTPException(403)
    # 只代理图片：vault 里还可能躺着 md 原文与备份，不该经此接口外泄。
    if fp.suffix.lower() not in _IMG_SUFFIXES:
        raise HTTPException(403)
    if not fp.is_file():
        raise HTTPException(404)
    return FileResponse(fp)


# ---------------- 安卓安装包下载 ----------------

@app.get("/api/app-apk")
def api_app_apk():
    fp = DATA_DIR.parent / "dist" / "goshor.apk"
    if not fp.exists():
        raise HTTPException(404, "APK 尚未构建")
    return FileResponse(fp, filename="goshor.apk",
                        media_type="application/vnd.android.package-archive")


# ---------------- AI 讲题 ----------------

class ExplainIn(BaseModel):
    doc_id: int
    mode: str = "deep"            # quick / deep / stuck
    stuck: dict | None = None
    ask: str = ""
    history: list[dict] = []


@app.post("/api/ai/explain")
async def api_explain(b: ExplainIn):
    doc = db.get_doc(b.doc_id)
    if not doc:
        raise HTTPException(404)

    stuck_key = ""
    if b.mode == "stuck" and b.stuck:
        stuck_key = json.dumps({"s": b.stuck.get("selected"), "step": b.stuck.get("step")}, ensure_ascii=False, sort_keys=True)

    # 首讲命中缓存直接流式复现（追问不缓存）
    if not b.history:
        cached = db.get_explain_cache(b.doc_id, b.mode, stuck_key)
        if cached:
            async def replay():
                yield f"data: {json.dumps({'type': 'delta', 'text': cached}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'text': ''}, ensure_ascii=False)}\n\n"
            return StreamingResponse(replay(), media_type="text/event-stream")

    if not b.history:
        messages = ai.build_first_messages(doc, b.mode, b.stuck)
    else:
        messages = [{"role": "system", "content": ai.SYSTEM_PROMPT}]
        messages += b.history
        if b.ask:
            messages.append({"role": "user", "content": b.ask})

    # 收集首讲内容用于缓存
    buffer: list[str] = []

    async def gen():
        async for kind, payload in ai.stream_chat(messages):
            if kind == "delta":
                buffer.append(payload)
            yield f"data: {json.dumps({'type': kind, 'text': payload}, ensure_ascii=False)}\n\n"
        if not b.history and buffer:
            db.set_explain_cache(b.doc_id, b.mode, stuck_key, "".join(buffer))

    return StreamingResponse(gen(), media_type="text/event-stream")


class AskIn(BaseModel):
    messages: list[dict] = []


@app.post("/api/ai/ask")
async def api_ai_ask(b: AskIn):
    """自由提问 AI 答疑：与做题无关，历史存前端 localStorage，服务端不落库。"""
    msgs = []
    use_vision = False
    for m in b.messages[-12:]:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        raw = m.get("content")
        if isinstance(raw, list):
            # 多模态消息（含图片），原样传递
            msgs.append({"role": role, "content": raw})
            if any(isinstance(p, dict) and p.get("type") == "image_url" for p in raw):
                use_vision = True
        else:
            content = str(raw or "")[:4000]
            if content:
                msgs.append({"role": role, "content": content})
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(400, "最后一条必须是用户提问")
    messages = [{"role": "system", "content": ai.ASK_SYSTEM}] + msgs

    async def gen():
        async for kind, payload in ai.stream_chat(messages, use_vision=use_vision):
            yield f"data: {json.dumps({'type': kind, 'text': payload}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


class GuideIn(BaseModel):
    doc_id: int
    answer: str = ""
    history: list[dict] = []


@app.post("/api/ai/guide")
async def api_ai_guide(b: GuideIn):
    """2.5 苏格拉底式引导讲题：连续追问，最多 GUIDE_MAX_ROUNDS 轮后必给解析。"""
    doc = db.get_doc(b.doc_id)
    if not doc:
        raise HTTPException(404)
    round_no = sum(1 for m in b.history if m.get("role") == "assistant") + 1
    force = round_no >= ai.GUIDE_MAX_ROUNDS
    messages = ai.build_guide_messages(doc, b.history, b.answer, round_no, force)
    buffer: list[str] = []

    async def gen():
        async for kind, payload in ai.stream_chat(messages):
            if kind == "delta":
                buffer.append(payload)
            yield _sse({"type": kind, "text": payload})
        parsed = ai.parse_guide_output("".join(buffer), round_no, force)
        yield _sse({"type": "result", "data": parsed})

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------- 折纸盒·拍照录题 ----------------

class CubeRecognizeIn(BaseModel):
    image: str = ""


@app.post("/api/cube/recognize")
async def api_cube_recognize(b: CubeRecognizeIn):
    try:
        return await cube_vision.recognize_net(b.image, load_settings())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # 网络/服务端异常兜底
        raise HTTPException(502, f"识别服务调用失败：{e}")


# ---------------- 速算 ----------------

class SpeedIn(BaseModel):
    config: dict = {}
    n: int = 10


@app.post("/api/speed/generate")
def api_speed_generate(b: SpeedIn):
    return {"items": speedcalc.generate(b.config, b.n)}


class SpeedResultIn(BaseModel):
    config: dict = {}
    total: int
    correct: int
    avg_ms: int
    details: list[dict] = []     # [{type, correct, ms}]


@app.post("/api/speed/result")
def api_speed_result(b: SpeedResultIn):
    db.add_speed_round(b.config, b.total, b.correct, b.avg_ms, b.details)
    return {"ok": True}


@app.get("/api/speed/type-stats")
def api_speed_type_stats():
    return {"items": db.speed_type_stats()}


@app.get("/api/speed/history")
def api_speed_history():
    return {"items": db.speed_history()}


# ---------------- 资料分析列式专项 ----------------

class FormulaIn(BaseModel):
    config: dict = {}
    n: int = 10


@app.post("/api/formula/generate")
def api_formula_generate(b: FormulaIn):
    types = b.config.get("types") or []
    n = max(5, min(30, b.n))
    return {"items": formula_drill.generate(types, n)}


class FormulaResultIn(BaseModel):
    config: dict = {}
    total: int
    correct: int
    avg_ms: int
    details: list[dict] = []


@app.post("/api/formula/result")
def api_formula_result(b: FormulaResultIn):
    db.add_formula_round(b.config, b.total, b.correct, b.avg_ms, b.details)
    return {"ok": True}


@app.get("/api/formula/type-stats")
def api_formula_type_stats():
    return {"items": db.formula_type_stats()}


@app.get("/api/formula/history")
def api_formula_history():
    return {"items": db.formula_history()}


# ---------------- 学习数据 ----------------

@app.get("/api/stats")
def api_stats():
    st = load_settings()
    # G2 每日目标：目标值从设置读入，stats 顺带返回今日进度环所需的一切
    out = db.stats_overview(
        int(st.get("daily_goal_questions") or 0),
        int(st.get("daily_goal_minutes") or 0))
    # N3 考试倒计时：顺带带上考试日期与剩余天数，首页一次请求即可渲染横幅
    exam_date = st.get("exam_date", "") or ""
    out["exam_date"] = exam_date
    out["days_left"] = db.exam_days_left(exam_date)
    return out


@app.get("/api/history")
def api_history(limit: int = 100, offset: int = 0):
    """做题历史记录（含题目信息）"""
    return db.answer_history(min(500, limit), offset)


@app.get("/api/time-analysis")
def api_time_analysis():
    """G1 单题用时分析：各模块均时/中位/超时，最慢 Top10，会做但超时清单。"""
    return db.time_analysis()


@app.get("/api/report/weekly")
def api_weekly_report():
    """每周学习诊断报告：本周 vs 上周，模块对比/薄弱考点/规则化建议。"""
    return db.weekly_report()


@app.get("/api/wrong-book")
def api_wrong_book():
    return {"items": db.list_wrong_book()}


class DocIdIn(BaseModel):
    doc_id: int


@app.post("/api/wrong-book/dismiss")
def api_wrong_book_dismiss(b: DocIdIn):
    """把一道题移出错题本。"""
    db.dismiss_wrong_book(b.doc_id)
    return {"ok": True}


@app.post("/api/wrong-book/restore")
def api_wrong_book_restore(b: DocIdIn):
    """把一道题重新放回错题本。"""
    db.restore_wrong_book(b.doc_id)
    return {"ok": True}


@app.get("/api/review/dashboard")
def api_review_dashboard():
    return db.review_dashboard()


@app.get("/api/marks")
def api_marks():
    return {"items": db.list_marks()}


@app.get("/api/my-documents")
def api_my_documents():
    """我的题库：当前账号导入的私有题目。"""
    return {"items": db.list_my_documents()}


@app.delete("/api/my-documents/{doc_id}")
def api_my_document_delete(doc_id: int):
    """从我的题库删除一条私有题目。"""
    if not db.delete_my_document(doc_id):
        raise HTTPException(404, "题目不存在")
    return {"ok": True}


@app.get("/api/kaodian-list")
def api_kaodian_list():
    return {"items": db.kaodian_list()}


@app.get("/api/kaodian-tree")
def api_kaodian_tree(module: str = "判断推理"):
    """判断专项：某模块真题考点两级树（大类/细分，带题数）。"""
    return {"items": db.kaodian_tree(module)}


@app.get("/api/zy/notes")
def api_zy_notes():
    """综应考点知识库：C类综应知识体系静态数据。"""
    return {"ok": True, "data": zy_notes.NOTES}


@app.get("/api/xc/notes")
def api_xc_notes():
    """O2 行测速查手册：公式 / 规律 / 速算技巧静态数据（与移动端同源）。"""
    return {"ok": True, "data": xingce_notes.NOTES}


class PaperIn(BaseModel):
    module: str = ""
    kaodian: str = ""
    n: int = 10
    trap: bool = False     # 疑点陷阱题集：只抽「确认问题」的题


@app.post("/api/paper")
def api_paper(b: PaperIn):
    ids = db.random_paper(b.module, b.kaodian, max(1, min(30, b.n)), trap=b.trap)
    return {"ids": ids}


@app.post("/api/paper/adaptive")
def api_paper_adaptive(b: PaperIn):
    """自适应组卷：按掌握度加权抽题，弱项优先（功能 1.1）。"""
    return {"ids": db.adaptive_paper(b.module, max(1, min(30, b.n)), b.kaodian)}


@app.post("/api/paper/sequential")
def api_paper_sequential(b: PaperIn):
    """顺序组卷（功能 1.1 顺序模式）：按题目 id 升序。"""
    return {"ids": db.sequential_paper(b.module, b.kaodian, max(1, min(50, b.n)))}


# ---------------- 练习草稿（N1 断点续做） ----------------
#
# 4 条路由双端同步：桌面在这里，移动端在 goshor_server.py 的 do_GET/do_POST。
# scope 白名单（'normal'/'exam'）由 db.normalize_draft_scope 统一收口，
# 前端传脏值不会写出新 scope 行。

class PaperDraftIn(BaseModel):
    scope: str = "normal"
    title: str = ""
    # 刻意用宽松的 list 而不是 list[int]：移动端 http.server 那侧没有模型校验，
    # 若这里严格，脏 id 会变成桌面 422 / 手机静默过滤，双端行为不一致。
    # 过滤统一收口在 db._as_int_list()。
    ids: list = []
    state: dict = {}


class DraftScopeIn(BaseModel):
    scope: str = "normal"


@app.get("/api/paper-drafts")
def api_paper_drafts():
    """草稿清单（首页「继续上次」卡片用，只含精简信息）。"""
    return {"items": db.list_unfinished_drafts()}


@app.get("/api/paper-draft/{scope}")
def api_paper_draft_get(scope: str):
    """完整草稿（点「继续」时拉取）。不存在返回 draft=null，前端当无草稿处理。"""
    return {"draft": db.load_paper_draft(scope)}


@app.post("/api/paper-draft/save")
def api_paper_draft_save(b: PaperDraftIn):
    db.save_paper_draft(b.scope, b.title, b.ids, b.state)
    return {"ok": True}


@app.post("/api/paper-draft/clear")
def api_paper_draft_clear(b: DraftScopeIn):
    db.clear_paper_draft(b.scope)
    return {"ok": True}


class NoteIn(BaseModel):
    content: str = ""


@app.get("/api/doc/{doc_id}/note")
def api_doc_note_get(doc_id: int):
    """读取某题笔记（无笔记返回空串）。"""
    return db.get_note(doc_id)


@app.post("/api/doc/{doc_id}/note")
def api_doc_note_set(doc_id: int, b: NoteIn):
    """写入/覆盖某题笔记；content 归一后为空即删除该题笔记。"""
    return db.set_note(doc_id, b.content)


@app.post("/api/note/clear")
def api_note_clear(b: NoteIn):
    """清空全部笔记（G7 数据清空与「我的」页一键清理用）。

    这里复用 NoteIn 只为拿到合适的 body 模型；content 被忽略。
    """
    db.clear_note(0)
    return {"ok": True}


@app.get("/api/notes")
def api_notes(limit: int = 500):
    """全部笔记（集中浏览 + 列表页「有笔记」标记）。"""
    return {"items": db.list_notes(limit), "counts": db.note_counts()}


# ---------------- G7 数据清空与重置 ----------------

class ResetIn(BaseModel):
    scope: str = ""
    # 两步确认的服务端护栏：前端必须显式带上 confirm=true，
    # 否则就算前端漏了二次确认也清不掉数据。
    confirm: bool = False


@app.get("/api/data/reset")
def api_data_reset_scopes():
    """清理范围清单（前端渲染危险区按钮用，含各范围覆盖的表名）。"""
    return {
        "scopes": [
            {"key": k, "tables": list(db.RESET_SCOPES[k])}
            for k in db.RESET_ALLOWED_SCOPES
        ],
        "forbidden": sorted(db.RESET_FORBIDDEN),
    }


@app.post("/api/data/reset")
def api_data_reset(b: ResetIn):
    """按白名单范围清空个人数据；题库 / 导入题 / 卡库内容永不清理。"""
    if not b.confirm:
        raise HTTPException(400, "缺少确认标记，已取消清理")
    r = db.reset_data(b.scope)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error") or "清理失败")
    return r


@app.get("/api/mastery")
def api_mastery(module: str = "", only_practiced: bool = False,
                limit: int = 0, offset: int = 0):
    """考点级掌握度图谱（功能 1.4）。

    limit 语义：不传/0 → 安全默认 MASTERY_PAGE_DEFAULT 条（防新客户端忘传参数
    把 1.45MB 全量拉回来）；>0 → 指定条数；-1 → 显式全量。
    前端默认分页拉取，避免上万行一次性渲染。
    """
    return db.kaodian_mastery_page(module, only_practiced=only_practiced,
                                   limit=limit, offset=offset)


# ---------------- 能力雷达 & 学习计划（功能 2.1） ----------------

class PlanIn(BaseModel):
    exam_date: str = ""      # 'YYYY-MM-DD'，空则按通用 14 天计划
    days: int = 14
    daily_n: int = 30


def _weak_kaodian_pool() -> dict[str, list[str]]:
    """薄弱考点池：各模块红/黄考点（题量大的优先），供计划轮换。"""
    pool: dict[str, list[str]] = {}
    for m in planner.MODULE_WEIGHT:
        rows = db.kaodian_mastery(m)
        weak = [r["kaodian"] for r in rows
                if r.get("level") in ("red", "amber") and r.get("total", 0) >= 3]
        pool[m] = weak[:8]
    return pool


@app.get("/api/ability/radar")
def api_ability_radar():
    return {"items": db.ability_radar()}


@app.get("/api/study-plan")
def api_study_plan():
    today = datetime.date.today().isoformat()
    return {
        "items": db.list_study_plan(),
        "summary": db.study_plan_summary(today),
        "today": today,
        # N3：计划页需要预填已保存的考试日期
        "exam_date": load_settings().get("exam_date", "") or "",
    }


@app.post("/api/study-plan/generate")
def api_study_plan_generate(b: PlanIn):
    """按能力雷达 + 考试日期生成 14 天计划并落库（覆盖同日期旧计划）。"""
    # N3：优先用本次传入的日期；没传则回落到设置里已保存的考试日期。
    # 非法日期一律当作「没设」——不落库、也不传给 planner，避免脏值污染设置文件。
    exam_date = (b.exam_date or "").strip() or (
        load_settings().get("exam_date", "") or "")
    if db.exam_days_left(exam_date) is None:
        exam_date = ""
    else:
        save_settings({"exam_date": exam_date})   # 生成计划即记住考试日期
    radar = db.ability_radar()
    items = planner.build_plan(
        radar, exam_date=exam_date,
        days=max(1, min(60, b.days)), daily_n=max(10, min(200, b.daily_n)),
        kaodian_pool=_weak_kaodian_pool())
    n = db.save_study_plan(items)
    today = datetime.date.today().isoformat()
    return {"ok": True, "n": n, "items": db.list_study_plan(),
            "summary": db.study_plan_summary(today), "today": today,
            "exam_date": exam_date}


class PlanToggleIn(BaseModel):
    day: str
    module: str
    done: bool = True


@app.post("/api/study-plan/toggle")
def api_study_plan_toggle(b: PlanToggleIn):
    ok = db.toggle_study_plan(b.day, b.module, b.done)
    today = datetime.date.today().isoformat()
    return {"ok": ok, "summary": db.study_plan_summary(today)}


# ---------------- 词语填空 ----------------

class WordfillGenIn(BaseModel):
    category: str = ""      # 成语 / 实词 / 混搭
    difficulty: str = "mid"
    n: int = 1


@app.post("/api/wordfill/generate")
async def api_wordfill_generate(b: WordfillGenIn):
    """AI 生成 n 道词填空，存入题库并返回。"""
    out = []
    for _ in range(max(1, min(5, b.n))):
        q = await wordfill.generate_one(b.category, b.difficulty)
        if q:
            q["difficulty"] = b.difficulty
            q["id"] = db.save_wordfill(q)
            out.append(q)
    return {"items": out, "total": db.wordfill_count()}


class WordfillPracticeIn(BaseModel):
    category: str = ""
    difficulty: str = ""
    n: int = 10


@app.post("/api/wordfill/practice")
async def api_wordfill_practice(b: WordfillPracticeIn):
    """练习题：优先从题库抽，不足则生成。"""
    existing = db.random_wordfill(b.n, b.category, b.difficulty)
    if len(existing) >= b.n:
        return {"items": existing, "generated": 0}
    # 补生成
    need = b.n - len(existing)
    for _ in range(min(need, 5)):
        q = await wordfill.generate_one(b.category, b.difficulty or "mid")
        if q:
            q["difficulty"] = b.difficulty or "mid"
            q["id"] = db.save_wordfill(q)
            existing.append(q)
    return {"items": existing, "generated": need}


class WordfillAnswerIn(BaseModel):
    qid: int
    selected: str
    correct: bool
    ms: int


@app.post("/api/wordfill/answer")
def api_wordfill_answer(b: WordfillAnswerIn):
    db.add_wordfill_answer(b.qid, b.selected, b.correct, b.ms)
    return {"ok": True}


@app.get("/api/wordfill/stats")
def api_wordfill_stats():
    return db.wordfill_stats()


# ---------------- 题库导入 ----------------

class ImportJsonIn(BaseModel):
    text: str
    defaults: dict = {}


@app.post("/api/import/json/preview")
def api_import_json_preview(b: ImportJsonIn):
    """解析自有题库 JSON，返回预览（不入库）。"""
    items, errors = importer.parse_json_bank(b.text)
    return {"items": items, "errors": errors, "count": len(items)}


class ImportUrlIn(BaseModel):
    url: str = ""
    text: str = ""


@app.post("/api/import/web/preview")
async def api_import_web_preview(b: ImportUrlIn):
    """抓网页或接受粘贴文本，AI 抽取真题，返回预览（不入库）。"""
    try:
        if b.url:
            text = await importer.fetch_url_text(b.url)
            if len(text) < 50:
                return {"items": [], "error": "网页正文过短，可能被反爬；请改用粘贴文本模式"}
        else:
            text = b.text.strip()
    except Exception as e:
        return {"items": [], "error": f"抓取失败：{e}"}
    if not text:
        return {"items": [], "error": "内容为空"}
    items, err = await importer.ai_extract_questions(text)
    return {"items": items, "error": err, "count": len(items)}


class ImportFileIn(BaseModel):
    name: str
    data_b64: str


@app.post("/api/import/file/preview")
async def api_import_file_preview(b: ImportFileIn):
    """解析上传文件（PDF/Word/Excel/CSV/MD），AI 抽取真题，返回预览（不入库）。"""
    import base64
    if not b.name or not b.data_b64:
        return {"items": [], "error": "文件为空"}
    try:
        data = base64.b64decode(b.data_b64)
    except Exception:
        return {"items": [], "error": "文件数据解码失败"}
    if len(data) > 20 * 1024 * 1024:
        return {"items": [], "error": "文件过大（上限 20MB）"}
    ext = b.name.rsplit(".", 1)[-1].lower() if "." in b.name else ""
    if ext not in ("pdf", "docx", "xlsx", "xls", "csv", "md", "txt", "json"):
        return {"items": [], "error": f"不支持的格式 .{ext}，支持 pdf/docx/xlsx/csv/md/txt/json"}
    try:
        text = importer.extract_text_from_file(b.name, data)
    except Exception as e:
        return {"items": [], "error": f"文件解析失败：{e}"}
    if len(text.strip()) < 20:
        return {"items": [], "error": "文件内容为空或过短"}
    # JSON 文件直接解析，不走 AI
    if ext == "json":
        items, errors = importer.parse_json_bank(text)
        return {"items": items, "errors": errors, "count": len(items)}
    fig_items, attach = [], {}
    if ext == "pdf":
        from .pdf_visual import build_figure_items
        try:
            fig_items, attach = await build_figure_items(data, load_settings())
        except Exception:
            fig_items, attach = [], {}  # 图形提取失败不影响文字题流程
    items, err = await importer.ai_extract_questions(text, extra_items=fig_items)
    for it in items:  # 文字题补图（如资料分析图表题，AI 已抽到但缺图）
        tags = attach.get(it.get("no"))
        if tags and "<img" not in it["stem"]:
            it["stem"] += "\n" + "\n".join(tags)
    return {"items": items, "error": err, "count": len(items)}


class ImportCommitIn(BaseModel):
    items: list[dict]
    defaults: dict = {}


@app.post("/api/import/commit")
def api_import_commit(b: ImportCommitIn):
    """确认导入：写 md 到 vault 99-自导入/ 并入库。"""
    if not b.items:
        return {"ok": False, "error": "没有可导入的题目"}
    if len(b.items) > 200:
        return {"ok": False, "error": "单次最多导入 200 题"}
    items, errors = [], []
    for i, raw in enumerate(b.items, 1):
        item, err = importer.normalize_item(raw, i)
        if item:
            items.append(item)
        else:
            errors.append(err)
    if not items:
        return {"ok": False, "error": "全部题目校验失败：" + "；".join(errors[:3])}
    result = importer.commit_items(items, b.defaults)
    result["skipped"] = errors
    return result


# ---------------- 疑点复核工作台 ----------------

@app.post("/api/doubts/sync")
def api_doubts_sync():
    return db.sync_doubts()


@app.get("/api/doubts")
def api_doubts(status: str = "", page: int = 1):
    items, total, counts = db.list_doubts(status, page)
    # 附带 doc_id 便于跳题：一次批量查回，避免逐条建连接（30 条 = 30 个连接）
    idmap = db.doc_ids_by_qids([it["qid"] for it in items])
    for it in items:
        it["doc_id"] = idmap.get(str(it["qid"]))
    return {"items": items, "total": total, "counts": counts}


class DoubtStatusIn(BaseModel):
    qid: str
    status: str            # pending / confirmed / dismissed


@app.post("/api/doubt/status")
def api_doubt_status(b: DoubtStatusIn):
    if b.status not in ("pending", "confirmed", "dismissed"):
        raise HTTPException(400, "非法状态")
    db.set_doubt_status(b.qid, b.status)
    return {"ok": True}


@app.post("/api/doubt/recheck/{qid}")
async def api_doubt_recheck(qid: str):
    """AI 独立重算单条疑点，返回结论文本并保存。"""
    items, _, _ = db.list_doubts()
    target = next((x for x in items if x["qid"] == qid), None)
    # list_doubts 分页默认 30，改用直接查询
    if not target:
        conn = db.connect()
        db._ensure_doubt(conn)
        row = conn.execute("SELECT * FROM doubts WHERE qid=?", (qid,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(404)
        target = dict(row)
    doc_id = db.doc_id_by_qid(qid)
    doc = db.get_doc(doc_id) if doc_id else None

    parts = [
        "你是事业单位C类命题质检员。下面是一道真题及其「疑点描述」，请你独立重算/重读，判断疑点是否成立，给出结论与理由，200 字以内。若题目含图片，你无法读图，只能基于文字与给定解析复核，不得臆断图中内容。",
        f"【疑点描述】{target['descr']}",
    ]
    if doc:
        d = doc["data"]
        if d.get("stem"):
            parts.append(f"【题干】{d['stem'][:800]}")
        if d.get("options"):
            parts.append("【选项】" + "；".join(f"{o['label']}.{o['text']}" for o in d["options"]))
        ans = next((o["label"] for o in d.get("options", []) if o.get("correct")), "")
        if ans:
            parts.append(f"【给定答案】{ans}")
        if d.get("official"):
            import re as _re2
            off = _re2.sub(r"<[^>]+>", "", d["official"])[:600]
            parts.append(f"【官方解析】{off}")
    else:
        parts.append("（题库中未找到原题，仅根据疑点描述判断）")

    messages = [
        {"role": "system", "content": "你是事业单位C类命题质检员，独立复核题目疑点，只给结论与依据。"},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    buf = []
    async for kind, payload in ai.stream_chat(messages):
        if kind == "delta":
            buf.append(payload)
        elif kind == "error":
            return {"ok": False, "error": payload}
    note = "".join(buf).strip()
    if note:
        db.set_doubt_ai(qid, note)
    return {"ok": True, "note": note}


# ---------------- 变式题 ----------------

@app.post("/api/variant/generate/{doc_id}")
async def api_variant_generate(doc_id: int):
    doc = db.get_doc(doc_id)
    if not doc:
        raise HTTPException(404)
    q = await variant.generate_variant(doc)
    if not q:
        return {"ok": False, "error": "生成未通过校验（结构或盲选交叉验证失败），请重试"}
    q["id"] = variant.save_variant(q)
    return {"ok": True, "item": q}


@app.get("/api/variant/list/{doc_id}")
def api_variant_list(doc_id: int):
    return {"items": variant.list_variants(doc_id)}


# ---------------- 变式歼灭闭环 ----------------

class AnnihilateIn(BaseModel):
    doc_id: int


@app.post("/api/annihilate/start")
async def api_annihilate_start(b: AnnihilateIn):
    """归因 + 并发生成 3 道同考点变式题（约 20–60 秒）。"""
    return await variant.start_annihilation(b.doc_id)


@app.post("/api/annihilate/finish")
def api_annihilate_finish(b: AnnihilateIn):
    """连对全部变式后落库歼灭记录。"""
    if not db.get_doc(b.doc_id):
        raise HTTPException(404)
    variant.finish_annihilation(b.doc_id)
    return {"ok": True}


# ---------------- 综应C·论证评价训练器 ----------------

class ArgumentSubmitIn(BaseModel):
    mid: str
    marks: list[dict]
    with_ai: bool = False


class ArgumentQuizCheckIn(BaseModel):
    answers: list[dict]


@app.get("/api/argument/overview")
def api_argument_overview():
    ov = argument.list_materials()
    ov["taxonomy"] = argument._TAXONOMY
    ov["quiz_stats"] = argument.quiz_stats()
    ov["quiz_type_stats"] = argument.quiz_type_stats()
    return ov


@app.get("/api/argument/material/{mid}")
def api_argument_material(mid: str):
    m = argument.get_material(mid)
    if not m:
        raise HTTPException(404)
    return m


@app.post("/api/argument/submit")
async def api_argument_submit(b: ArgumentSubmitIn):
    r = argument.submit(b.mid, b.marks)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "判分失败"))
    if b.with_ai:
        r["ai_comments"] = await argument.ai_comment(b.mid, r["detail"])
    return r


@app.post("/api/argument/quiz/draw")
def api_argument_quiz_draw(b: dict):
    # types 兼容字符串（单类型专练）与列表，归一化在 quiz_draw 内
    return argument.quiz_draw(max(1, min(20, int(b.get("n", 5)))),
                              types=b.get("types") or None)


@app.post("/api/argument/quiz/check")
def api_argument_quiz_check(b: ArgumentQuizCheckIn):
    return argument.quiz_check(b.answers)


# ---------------- 设置 ----------------

@app.get("/api/settings")
def api_settings_get():
    s = load_settings()
    s["deepseek_api_key"] = "***" + s["deepseek_api_key"][-4:] if s["deepseek_api_key"] else ""
    # O1：WebDAV 密码 / 同步口令绝不回给前端，只暴露「是否已配置」
    s["sync_has_password"] = bool(s.pop("sync_password", ""))
    s["sync_has_passphrase"] = bool(s.pop("sync_passphrase", ""))
    return s


class SettingsIn(BaseModel):
    vault_path: str | None = None
    deepseek_base_url: str | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None
    exam_date: str | None = None    # N3 考试日期 'YYYY-MM-DD'，空串=清除
    # N2 学习提醒
    reminder_on: bool | None = None
    reminder_time: str | None = None
    reminder_plan_only: bool | None = None
    # G2 每日目标（0=该项不设目标）
    daily_goal_questions: int | None = None
    daily_goal_minutes: int | None = None


@app.post("/api/settings")
def api_settings_set(b: SettingsIn):
    raw = b.model_dump()
    patch = {k: v for k, v in raw.items() if v is not None}
    if patch.get("deepseek_api_key", "").startswith("***"):
        patch.pop("deepseek_api_key")
    # N3：考试日期只接受空串（清除）或合法 YYYY-MM-DD，脏值不落盘（与移动端同口径）
    if "exam_date" in patch:
        patch["exam_date"] = patch["exam_date"].strip()
        if patch["exam_date"] and db.exam_days_left(patch["exam_date"]) is None:
            patch.pop("exam_date")
    # N2：提醒字段统一归一化（非法时间/开关一律丢弃，与移动端同口径）
    for k in REMINDER_KEYS:
        patch.pop(k, None)
    patch.update(reminder_patch(raw))
    # G2：每日目标同样归一化（0 合法=不设目标，脏值丢弃）
    for k in GOAL_KEYS:
        patch.pop(k, None)
    patch.update(goal_patch(raw))
    save_settings(patch)
    return {"ok": True}


# ---------------- F6 错因标签 / F7 间隔复习 ----------------

class WrongReasonIn(BaseModel):
    doc_id: int
    reason: str = ""


@app.post("/api/wrong-reason")
def api_wrong_reason(b: WrongReasonIn):
    db.set_wrong_reason(b.doc_id, b.reason)
    return {"ok": True}


@app.get("/api/wrong-reasons")
def api_wrong_reasons():
    return db.wrong_reason_map()


class WrongReasonAiIn(BaseModel):
    doc_id: int


@app.post("/api/wrong-reason/ai-suggest")
async def api_wrong_reason_ai(b: WrongReasonAiIn):
    """AI 结构化归因（错因 2.0）：返回五类错因 + 具体错点 + 考点 + 建议，落库不覆盖手填。"""
    doc = db.get_doc(b.doc_id)
    if not doc:
        raise HTTPException(404)
    d = doc["data"]
    hist = db.get_user_history(b.doc_id)
    correct = next((o["label"] for o in d.get("options") or [] if o.get("correct")), "")
    opts = "\n".join(f"{o['label']}. {o['text']}" for o in d.get("options") or [])
    prompt = ai.build_wrong_reason_prompt(
        str(d.get("stem", "")), opts, correct,
        str(hist.get("last_selected") or ""), hist.get("tries", 0), hist.get("wrongs", 0))
    try:
        raw = await ai.chat_once([{"role": "user", "content": prompt}], temperature=0)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    data = ai.parse_wrong_reason_json(raw)
    if not data:
        # 兜底：AI 未按 JSON 返回时，退化为关键词匹配
        reason = next((r for r in ai.WRONG_CATEGORIES if r in raw), "")
        if reason:
            db.set_wrong_ai(b.doc_id, reason)
        return {"ok": bool(reason), "reason": reason, "category": reason,
                "specific": "", "kaodian": "", "advice": ""}
    db.set_wrong_ai(b.doc_id, data["category"], data["specific"],
                    data["kaodian"], data["advice"])
    return {"ok": True, "reason": data["category"], **data}


@app.get("/api/wrong-reason/ai-map")
def api_wrong_reason_ai_map():
    """AI 结构化归因映射（错因 2.0）。"""
    return {"items": db.wrong_reason_ai_map()}


@app.get("/api/wrong-reason/distribution")
def api_wrong_reason_distribution():
    """错因分布（错因 2.0）。"""
    return {"items": db.wrong_reason_distribution()}


@app.get("/api/reviews")
def api_reviews():
    return {"items": db.due_reviews()}


# ---------------- F9 辨析卡 ----------------

@app.post("/api/cards/import")
def api_cards_import():
    return db.import_cards()


@app.get("/api/cards")
def api_cards(card_type: str = "", category: str = "", module: str = ""):
    return {"items": db.list_cards(card_type, category, module)}


@app.get("/api/cards/facets")
def api_cards_facets():
    return db.card_facets()


class CardReviewIn(BaseModel):
    card_id: str
    level: int = 2      # 0不会 1模糊 2认识


@app.post("/api/card-review")
def api_card_review(b: CardReviewIn):
    db.card_review(b.card_id, b.level)
    return {"ok": True}


@app.get("/api/due-cards")
def api_due_cards():
    return {"items": db.due_cards()}


@app.get("/api/cards/weak")
def api_cards_weak():
    return {"items": db.weak_cards()}


# ---------------- F5 真实配比模考 ----------------

class ExamTemplateIn(BaseModel):
    key: str = "guokao"     # guokao / shiye_c


@app.post("/api/exam-template")
def api_exam_template(b: ExamTemplateIn):
    return db.template_paper(b.key)


# ---------------- 就地跳下一题 / 学习时长 ----------------

@app.get("/api/next-doc/{doc_id}")
def api_next_doc(doc_id: int):
    return {"doc_id": db.next_doc_id(doc_id)}


@app.get("/api/study-time")
def api_study_time():
    return db.study_time_stats()


# ---------------- 半月时政 ----------------

def _shizheng_period(now=None) -> tuple[str, str]:
    import datetime
    dt = now or datetime.datetime.now()
    half = "上半月" if dt.day <= 15 else "下半月"
    return f"{dt.year}年{dt.month}月{half}", f"{dt.year}年{dt.month}月"


def _shizheng_recent_periods(n=12) -> list[str]:
    """返回最近 n 个半月期次（含当期），倒序排列。"""
    import datetime
    dt = datetime.datetime.now()
    periods = []
    # 当期
    half = "上半月" if dt.day <= 15 else "下半月"
    periods.append(f"{dt.year}年{dt.month}月{half}")
    # 往期
    year, month = dt.year, dt.month
    for _ in range(n - 1):
        if half == "下半月":
            half = "上半月"
        else:
            half = "下半月"
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        periods.append(f"{year}年{month}月{half}")
    return periods


@app.get("/api/shizheng")
def api_shizheng_list():
    period, month = _shizheng_period()
    recent = _shizheng_recent_periods(12)  # 近半年=12期
    existing = {item["period"] for item in db.list_shizheng()}
    return {
        "items": db.list_shizheng(),
        "current": period,
        "current_exists": db.get_shizheng(period) is not None,
        "recent_periods": recent,
        "missing_periods": [p for p in recent if p not in existing],
    }


class ShizhengGenIn(BaseModel):
    period: str = ""


@app.post("/api/shizheng/generate")
async def api_shizheng_generate(b: ShizhengGenIn):
    period = b.period or _shizheng_period()[0]
    existed = db.get_shizheng(period)
    if existed:
        return {"ok": True, "item": existed, "cached": True}
    m = __import__("re").search(r"(\d{4})年(\d{1,2})月(上|下)半月", period)
    if not m:
        return {"ok": False, "error": "期次格式错误"}
    year, month, half = m.group(1), m.group(2), ("1-15日" if m.group(3) == "上" else "16-月末")
    prompt = (
        f"你是公务员考试时政辅导老师。请整理 {year}年{month}月{half} 的时政常识积累，"
        "面向事业单位/公务员考试考生。若该时段在你的知识截止日期之后，请基于最近一次可确认的时事动态"
        "与长期高频考点（重要会议精神、科技成就、民生政策、纪念日、国际组织等）整理，并在开头注明"
        "「内容基于模型知识整理，考前请以权威时政资料核对」。"
        "输出 Markdown，结构如下：\n"
        "# {期次}时政常识\n"
        "## 一、国内要闻（10-14条，每条一行：**事件**——一句考点式说明）\n"
        "## 二、科技与民生（5-8条）\n"
        "## 三、国际要闻（4-6条）\n"
        "## 四、自测小测（5道单选题，题目后用「答案：X」标注）"
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        content = await ai.chat_once(messages, temperature=0.3)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    if not content.strip():
        return {"ok": False, "error": "生成内容为空，请重试"}
    db.save_shizheng(period, f"{period}时政常识", content)
    return {"ok": True, "item": db.get_shizheng(period)}


@app.post("/api/shizheng/quiz")
async def api_shizheng_quiz(b: ShizhengGenIn):
    """为某期时政生成 10 道自测单选（JSON），存库；已存在直接返回。"""
    import json as _json
    import re as _re
    period = b.period or _shizheng_period()[0]
    cached = db.get_shizheng_quiz(period)
    if cached:
        try:
            return {"ok": True, "cached": True, "items": _json.loads(cached)}
        except Exception:
            pass
    item = db.get_shizheng(period)
    if not item:
        return {"ok": False, "error": "该期时政尚未生成"}
    prompt = ai.build_shizheng_quiz_prompt(item["content"])
    try:
        out = await ai.chat_once([{"role": "user", "content": prompt}], temperature=0.4)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    items = ai.parse_shizheng_quiz_json(out)
    if not items:
        return {"ok": False, "error": "生成格式异常或解析失败，请重试"}
    db.save_shizheng_quiz(period, _json.dumps(items, ensure_ascii=False))
    return {"ok": True, "cached": False, "items": items}


# ---------------- 备份 / 恢复 ----------------

def _user_db_path() -> Path:
    """当前「个人数据库」的路径：split 模式是 user.db，legacy 是 goshor.db。

    刻意读 `db` 模块里的变量（而不是本模块 import 进来的常量）：测试会把
    `db.DB_PATH` / `db.USER_DB_PATH` monkeypatch 到 tmp_path，本模块的常量不会跟着变。
    """
    return db.USER_DB_PATH if db.split_enabled() else db.DB_PATH


def _replace_db_file(src) -> None:
    """把 src 的内容写进当前个人数据库（走 SQLite 在线备份 API，不换文件）。

    为什么不是 `shutil.copy2` + 删 `-wal`：
    - 只覆盖 `goshor.db`、留着旧 `-wal` → 下次打开时 SQLite 会把旧事务**重放**
      回新库，表现为「恢复了但还是旧数据」；
    - 改成「先删 `-wal` 再覆盖」在 Windows 上会撞 `WinError 32`（库连接还开着，
      文件被占用删不掉），而且中途失败就没有退路。

    用 `Connection.backup()` 把源库页面整份写进目标库，则以上问题都不存在：
    写入走 WAL、对已在运行的服务即时可见，也不需要动文件。

    split 模式下目标换成 user.db：**绝不**碰 content.db（题库是可分发、
    可整体替换的只读文件，恢复个人备份不该改动它）。
    """
    import sqlite3
    src_conn = sqlite3.connect(str(src), timeout=15)
    try:
        dst = sqlite3.connect(_user_db_path(), timeout=15)
        try:
            src_conn.backup(dst)
            dst.commit()
        finally:
            dst.close()
    finally:
        src_conn.close()


def _prune_content_tables_from_user_db() -> None:
    """split 模式下把「旧整库备份」带进 user.db 的题库表清掉。

    升级用户可能导入旧版备份：那份 `goshor.db` 里有 documents / docs_fts /
    shizheng 真实表，恢复后它们会落在 user.db 里。split 模式下这几张表永远被
    TEMP VIEW 遮蔽（读不到），留着只会让 user.db 平白胖几百 MB，之后每次备份/
    同步都把题库重新背一遍。题库的唯一来源是 content.db，所以这里删除并
    VACUUM 收回空间；个人表一律不动。
    """
    import sqlite3
    conn = sqlite3.connect(_user_db_path(), timeout=15)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        dropped = False
        for t in ("documents", "docs_fts", "shizheng"):
            if t in names:
                conn.execute(f'DROP TABLE "{t}"')
                dropped = True
        if dropped:
            conn.commit()
            # 纯空间回收，失败不该让「已经恢复成功」的导入报错
            try:
                conn.execute("VACUUM")
            except sqlite3.Error:
                pass
    except sqlite3.Error:
        # 清理是尽力而为：即便 DROP 没成功（例如库被别的连接锁住），
        # 个人数据也已经恢复完毕，下次导入/下次启动还能再清。
        pass
    finally:
        conn.close()


@app.get("/api/backup/export")
def api_backup_export():
    """打包当前个人库 + settings.json + essay_questions.json 为 zip 下载。

    整库已 400MB+，这里做两处必要处理，否则接口会「假死」：
    1. **一致性快照**：用 SQLite 在线备份 API 导出，而不是直接复制主库。
       WAL 模式下未 checkpoint 的已提交事务还留在 -wal 文件里，直接复制
       `goshor.db` 会丢掉最近数据、写入中还可能复制到撕裂的页。
    2. **落盘 + 快压缩**：zip 写入临时文件后用 FileResponse 返回。旧实现把整个
       压缩包堆在 BytesIO 里（实测 430MB→132MB，耗时 60.4s，客户端 120s 超时），
       改 compresslevel=1 后耗时 17.1s（3.5×）、体积 141MB，内存峰值从 130MB+
       降到可忽略。

    两种模式的差异只有「快照源」`db.snapshot_to` 内部处理：legacy 是 goshor.db，
    split 是 user.db（个人数据）。**split 模式的备份里永远不含 content.db**：
    题库几百 MB、可重新分发，把它塞进每次备份/同步既慢，也让「恢复个人数据」变成
    「回滚题库」。zip 内的文件名仍叫 `goshor.db`，这样旧版导入端/手机端不用改。
    """
    import shutil
    import tempfile
    import zipfile

    tmpdir = Path(tempfile.mkdtemp(prefix="goshore_bak_"))
    try:
        snap = tmpdir / "goshor.db"
        try:
            db.snapshot_to(snap)
        except Exception:
            # 极端情况下退回直接复制（至少保证能导出，只是可能缺 WAL 尾部数据）
            shutil.copyfile(_user_db_path(), snap)

        zpath = tmpdir / "backup.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=1) as z:
            if snap.exists():
                z.write(snap, "goshor.db")
            if SETTINGS_PATH.exists():
                z.write(SETTINGS_PATH, "settings.json")
            eq = DATA_DIR / "essay_questions.json"
            if eq.exists():
                z.write(eq, "essay_questions.json")
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise

    name = f"goshore_backup_{datetime.datetime.now():%Y%m%d_%H%M}.zip"
    return FileResponse(
        zpath, media_type="application/zip", filename=name,
        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True))


@app.post("/api/backup/import")
async def api_backup_import(file: UploadFile):
    """从备份 zip 恢复（覆盖个人库 / settings / essay 题库），需重启服务生效。

    split 模式下 zip 里那份 `goshor.db` 实际是 user.db 的内容：只覆盖个人库，
    **content.db 不动**（题库不随个人备份走，也不该被旧备份回滚）。
    """
    import zipfile
    import shutil
    import tempfile
    ok_files = []
    try:
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "backup.zip"
            fp.write_bytes(await file.read())
            with zipfile.ZipFile(fp) as z:
                names = z.namelist()
                if "goshor.db" not in names:
                    return {"ok": False, "error": "备份包中缺少 goshor.db"}
                tmp_db = Path(td) / "goshor.db"
                z.extract("goshor.db", td)
                # 校验是合法 SQLite 再覆盖
                import sqlite3
                try:
                    chk = sqlite3.connect(tmp_db)
                    chk.execute("SELECT 1")
                    chk.close()
                except Exception:
                    return {"ok": False, "error": "goshor.db 校验失败"}
                _replace_db_file(tmp_db)
                ok_files.append("goshor.db")
                if db.split_enabled():
                    # 旧版「整库」备份会把题库表一起写进 user.db，恢复后立刻摘掉
                    # （见 _prune_content_tables_from_user_db 的说明）
                    _prune_content_tables_from_user_db()
                if "settings.json" in names:
                    shutil.copy2(Path(td) / "settings.json", SETTINGS_PATH)
                    ok_files.append("settings.json")
                if "essay_questions.json" in names:
                    shutil.copy2(Path(td) / "essay_questions.json",
                                 DATA_DIR / "essay_questions.json")
                    ok_files.append("essay_questions.json")
        return {"ok": True, "restored": ok_files, "note": "请重启服务使恢复生效"}
    except zipfile.BadZipFile:
        return {"ok": False, "error": "不是合法的 zip 备份包"}


# ---------------- O1 多设备加密同步（WebDAV） ----------------
# 明文永不出本机：上传的是「本地备份 zip → 口令派生密钥加密」后的信封，
# 口令只参与本地派生，不随请求发送。冲突策略见 `api_sync_down`。

class SyncConfigIn(BaseModel):
    sync_enabled: bool | None = None
    sync_url: str | None = None
    sync_user: str | None = None
    sync_remote_path: str | None = None
    sync_wifi_only: bool | None = None
    # 写入口令：不填（None）表示保持原值；传空串表示清除
    sync_password: str | None = None
    sync_passphrase: str | None = None


class SyncTestIn(BaseModel):
    """连接测试可临时传地址/账号（未保存也能先测）。"""
    sync_url: str | None = None
    sync_user: str | None = None
    sync_password: str | None = None


class SyncDownIn(BaseModel):
    force: bool = False


def _sync_public(s: dict) -> dict:
    """同步配置的对外视图（与移动端共用 `sync_webdav.public_config`）。"""
    return sync_webdav.public_config(s)


def _sync_remote_path(s: dict) -> str:
    return s.get("sync_remote_path") or SYNC_REMOTE_DEFAULT


def _sync_client(s: dict, **override) -> sync_webdav.WebDAVClient:
    return sync_webdav.WebDAVClient(
        override.get("sync_url") or s.get("sync_url", ""),
        override.get("sync_user", s.get("sync_user", "")),
        override.get("sync_password", s.get("sync_password", "")),
    )


def _sync_ready(s: dict) -> str:
    """返回错误文案；配置齐了返回空串。"""
    if not s.get("sync_url"):
        return "请先填写 WebDAV 地址"
    if not s.get("sync_passphrase"):
        return "请先设置同步口令（上传前用它加密，务必牢记）"
    return ""


def _local_stamp() -> str:
    """本地数据版本戳（个人库 + WAL 一起算，见 `sync_webdav.file_stamp`）。

    split 模式下只算 user.db：content.db 是题库，同步的是个人数据；把题库算进
    版本戳会让「换个题库文件」被误判成「本地数据变了」而触发假冲突。
    """
    return sync_webdav.file_stamp([str(_user_db_path())])


def _device_name() -> str:
    return sync_webdav.device_name()


def _sync_pack(tmpdir) -> tuple:
    """打包桌面备份（个人库一致性快照 + settings.json + essay 题库）。

    返回 (zip 路径, 明文字节数)；清单与 `/api/backup/export` 保持一致，
    便于「云端恢复」后与手动导出包互换使用。split 模式下快照源是 user.db，
    不含题库（见 `api_backup_export` 的说明）。
    """
    import shutil
    from pathlib import Path as _P
    td = _P(tmpdir)
    snap = td / "goshor.db"
    try:
        db.snapshot_to(snap)
    except Exception:
        shutil.copyfile(_user_db_path(), snap)
    pairs = [(snap, "goshor.db")]
    if SETTINGS_PATH.exists():
        pairs.append((SETTINGS_PATH, "settings.json"))
    eq = DATA_DIR / "essay_questions.json"
    if eq.exists():
        pairs.append((eq, "essay_questions.json"))
    zp = sync_webdav.build_zip(pairs, td / "backup.zip")
    return zp, zp.stat().st_size


def _http_time_gt(modified: str, last_iso: str) -> bool:
    return sync_webdav.remote_newer(modified, last_iso)


@app.get("/api/sync/config")
def api_sync_config_get():
    return {"ok": True, "config": _sync_public(load_settings())}


@app.post("/api/sync/config")
def api_sync_config_set(b: SyncConfigIn):
    raw = {k: v for k, v in b.model_dump().items() if v is not None}
    save_settings(sync_patch(raw))
    return {"ok": True, "config": _sync_public(load_settings())}


@app.post("/api/sync/test")
def api_sync_test(b: SyncTestIn | None = None):
    s = load_settings()
    ov = {k: v for k, v in (b.model_dump() if b else {}).items() if v}
    try:
        if not (ov.get("sync_url") or s.get("sync_url")):
            return {"ok": False, "error": "请先填写 WebDAV 地址"}
        res = _sync_client(s, **ov).test()
    except sync_webdav.SyncError as e:
        return {"ok": False, "error": str(e)}
    if not res.get("ok"):
        return {"ok": False, "error": res.get("message", "连接测试失败")}
    return {"ok": True, "message": res.get("message", "连接成功"),
            "server": res.get("server", "")}


@app.post("/api/sync/up")
def api_sync_up():
    import shutil
    import tempfile
    s = load_settings()
    err = _sync_ready(s)
    if err:
        return {"ok": False, "error": err}
    remote = _sync_remote_path(s)
    tmpdir = tempfile.mkdtemp(prefix="goshore_sync_")
    try:
        zp, plain_size = _sync_pack(tmpdir)
        blob = sync_webdav.encrypt_bytes(zp.read_bytes(), s["sync_passphrase"])
        cli = _sync_client(s)
        cli.ensure_dirs(remote)
        size = cli.put(remote, blob)
    except sync_webdav.SyncError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"打包备份失败：{e}"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    now = datetime.datetime.now().isoformat(timespec="seconds")
    save_settings({
        "sync_last_at": now, "sync_last_up_at": now,
        "sync_last_size": size, "sync_device": _device_name(),
        # 上传后本机就是云端的内容，重置基准 stamp，避免下次下载误报冲突
        "sync_local_stamp": _local_stamp(),
    })
    return {"ok": True, "size": size, "plain_size": plain_size,
            "remote": remote, "at": now, "note": "已加密上传（云端只见密文）"}


@app.get("/api/sync/remote")
def api_sync_remote():
    s = load_settings()
    if not s.get("sync_url"):
        return {"ok": False, "error": "请先填写 WebDAV 地址"}
    remote = _sync_remote_path(s)
    try:
        st = _sync_client(s).stat(remote)
    except sync_webdav.SyncError as e:
        return {"ok": False, "error": str(e)}
    if st is None:
        return {"ok": True, "exists": False, "remote": remote,
                "message": "云端还没有备份，请先在本机上传"}
    return {"ok": True, "exists": True, "remote": remote, "size": st["size"],
            "modified": st["modified"], "etag": st["etag"],
            "last_at": s.get("sync_last_at", ""),
            "local_changed": bool(s.get("sync_local_stamp")
                                  and _local_stamp() != s.get("sync_local_stamp"))}


@app.post("/api/sync/down")
def api_sync_down(b: SyncDownIn):
    import json as _json
    import shutil
    import sqlite3
    import tempfile
    s = load_settings()
    err = _sync_ready(s)
    if err:
        return {"ok": False, "error": err}
    remote = _sync_remote_path(s)
    try:
        cli = _sync_client(s)
        st = cli.stat(remote)
        if st is None:
            return {"ok": False, "error": "云端还没有备份，请先在本机上传"}
        # 冲突：本机自上次同步后又写了新数据，且云端也在此后更新过 → 需二次确认
        local_changed = bool(s.get("sync_local_stamp")
                             and _local_stamp() != s.get("sync_local_stamp"))
        if local_changed and _http_time_gt(st.get("modified", ""),
                                           s.get("sync_last_at", "")) and not b.force:
            return {"ok": False, "conflict": True, "size": st["size"],
                    "modified": st["modified"],
                    "error": "检测到冲突：本机自上次同步后又有新数据，云端同期也更新了。"
                             "继续将用云端覆盖本机，请确认后再试。"}
        blob = cli.get(remote)
    except sync_webdav.SyncError as e:
        return {"ok": False, "error": str(e)}
    if blob is None:
        return {"ok": False, "error": "云端还没有备份，请先在本机上传"}
    try:
        raw = sync_webdav.decrypt_bytes(blob, s["sync_passphrase"])
    except sync_webdav.SyncError as e:
        # 解不开就绝不落盘，避免「解出一堆乱码再覆盖本地」
        return {"ok": False, "error": str(e)}

    tmpdir = tempfile.mkdtemp(prefix="goshore_restore_")
    restored = []
    try:
        zp = Path(tmpdir) / "backup.zip"
        zp.write_bytes(raw)
        import zipfile
        try:
            with zipfile.ZipFile(zp) as z:
                names = z.namelist()
                if "goshor.db" not in names:
                    return {"ok": False, "error": "云端备份包中缺少 goshor.db"}
                z.extract("goshor.db", tmpdir)
                chk = sqlite3.connect(Path(tmpdir) / "goshor.db")
                chk.execute("SELECT 1")
                chk.close()
                restored.append("goshor.db")
                if "settings.json" in names:
                    z.extract("settings.json", tmpdir)
                    restored.append("settings.json")
                if "essay_questions.json" in names:
                    z.extract("essay_questions.json", tmpdir)
                    restored.append("essay_questions.json")
        except zipfile.BadZipFile:
            return {"ok": False, "error": "云端数据不是合法的备份包（口令是否用错？）"}

        # 本机的同步凭据不能被云端那份覆盖：DPAPI 密文跨机器解不开，
        # 覆盖后用户会「既连不上云、又丢了本地密钥」。先留好，落盘后回填。
        keep = {"sync_local_stamp": s.get("sync_local_stamp", "")}
        try:
            keep_disk = _json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            keep_disk = {}
        for k in SYNC_KEYS + ("sync_local_stamp", "sync_last_at",
                              "sync_last_up_at", "sync_last_down_at",
                              "sync_last_size", "sync_device"):
            if k in s:
                keep[k] = s[k]
        for enc in ("sync_password_enc", "sync_passphrase_enc"):
            if keep_disk.get(enc):
                keep[enc] = keep_disk[enc]

        _replace_db_file(Path(tmpdir) / "goshor.db")
        if "settings.json" in restored:
            merged = _json.loads(
                (Path(tmpdir) / "settings.json").read_text(encoding="utf-8"))
            merged.update(keep)
            SETTINGS_PATH.write_text(
                _json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8")
        else:
            save_settings(keep)
        if "essay_questions.json" in restored:
            shutil.copy2(Path(tmpdir) / "essay_questions.json",
                         DATA_DIR / "essay_questions.json")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    now = datetime.datetime.now().isoformat(timespec="seconds")
    save_settings({"sync_last_at": now, "sync_last_down_at": now,
                   "sync_last_size": len(blob),
                   "sync_local_stamp": _local_stamp()})
    return {"ok": True, "restored": restored, "size": len(blob), "at": now,
            "note": "已从云端恢复，请重启服务使数据生效"}


# ---------------- 申论 / 综应知识 ----------------

@app.get("/api/knowledge/essay")
def api_knowledge_essay():
    return knowledge.ESSAY_KNOWLEDGE


# ---------------- 申论 / 综应 AI 批改 ----------------

@app.get("/api/essay/rubrics")
def api_essay_rubrics():
    return {"items": [
        {"key": k, "name": v["name"], "hint": v["hint"], "default_score": v["default_score"]}
        for k, v in essay_rubric.RUBRICS.items()
    ]}


class EssayGradeIn(BaseModel):
    category: str
    question: str
    material: str = ""
    answer: str
    reference: str = ""       # 参考答案（真题库带出），空则 AI 自拟要点
    total_score: int = 0      # 0 = 用题型默认满分


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.post("/api/essay/grade")
async def api_essay_grade(b: EssayGradeIn):
    """批改 2.0：结构化 JSON（要点命中表 + 四维评分 + 改写示范），解析失败降级为纯文本。"""
    r = essay_rubric.RUBRICS.get(b.category)
    if not r:
        raise HTTPException(400, "未知题型")
    if not b.question.strip() or not b.answer.strip():
        raise HTTPException(400, "题目与作答均不能为空")
    total = b.total_score if 10 <= b.total_score <= 100 else r["default_score"]

    messages = essay_rubric.build_grade_messages(
        b.category, total, b.question, b.material, b.answer, b.reference)

    buffer: list[str] = []

    async def gen():
        yield _sse({"type": "phase", "text": "正在拆解得分点并逐条评分…"})
        async for kind, payload in ai.stream_chat_with_temp(messages, 0.2):
            if kind == "delta":
                buffer.append(payload)
            elif kind == "error":
                yield _sse({"type": "error", "text": payload})
                return
        raw = "".join(buffer).strip()
        parsed = essay_rubric.parse_grade_json(raw)
        if parsed:
            parsed["score"] = max(0.0, min(float(total), float(parsed.get("score") or 0)))
            essay_rubric.enrich_dims(parsed, b.category, total)
            md_text = essay_rubric.render_grade_markdown(parsed, total)
            gid = db.save_essay_grade(
                b.category, b.question, b.answer, total, md_text,
                score=parsed["score"], level=parsed.get("level", ""),
                points_json=json.dumps(parsed["points"], ensure_ascii=False),
                dims_json=json.dumps(parsed["dims"], ensure_ascii=False),
                rewrite_json=json.dumps(parsed["rewrite"], ensure_ascii=False))
            yield _sse({"type": "result", "data": parsed, "total": total})
            yield _sse({"type": "saved", "text": str(gid)})
        elif raw:
            gid = db.save_essay_grade(b.category, b.question, b.answer, total, raw)
            yield _sse({"type": "fallback", "text": raw})
            yield _sse({"type": "saved", "text": str(gid)})
        else:
            yield _sse({"type": "error", "text": "批改未返回内容，请重试"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/essay/trend")
def api_essay_trend(category: str = "", limit: int = 30):
    """历史提分曲线：按题型（可选）返回历次批改得分率。"""
    return {"items": db.essay_score_trend(category, limit)}


# ---------------- 面试模块（功能 2.3） ----------------

class InterviewGradeIn(BaseModel):
    qid: int = 0
    category: str = ""
    question: str
    answer: str
    think_ms: int = 0
    answer_ms: int = 0


@app.get("/api/interview/questions")
def api_interview_questions(category: str = ""):
    return {
        "items": db.list_interview_questions(category),
        "counts": db.interview_category_counts(),
        "categories": interview.CATEGORIES,
        "hints": interview.CATEGORY_HINT,
        "think_seconds": interview.THINK_SECONDS,
        "answer_seconds": interview.ANSWER_SECONDS,
    }


@app.get("/api/interview/question/{qid}")
def api_interview_question(qid: int):
    q = db.get_interview_question(qid)
    if not q:
        raise HTTPException(404)
    return q


@app.get("/api/interview/stats")
def api_interview_stats():
    return db.interview_stats()


@app.get("/api/interview/logs")
def api_interview_logs():
    return {"items": db.list_interview_logs()}


@app.get("/api/interview/log/{lid}")
def api_interview_log(lid: int):
    it = db.get_interview_log(lid)
    if not it:
        raise HTTPException(404)
    return it


@app.post("/api/interview/grade")
async def api_interview_grade(b: InterviewGradeIn):
    """AI 模拟考官：内容/逻辑/表达三维点评（结构化 JSON，失败降级纯文本）。"""
    if not b.question.strip() or not b.answer.strip():
        raise HTTPException(400, "题目与作答均不能为空")
    category = b.category or "综合分析"
    q = db.get_interview_question(b.qid) if b.qid else None
    messages = interview.build_grade_messages(
        category, b.question, b.answer, (q or {}).get("reference", ""))

    buffer: list[str] = []

    async def gen():
        yield _sse({"type": "phase", "text": "模拟考官正在点评…"})
        async for kind, payload in ai.stream_chat_with_temp(messages, 0.3):
            if kind == "delta":
                buffer.append(payload)
            elif kind == "error":
                yield _sse({"type": "error", "text": payload})
                return
        raw = "".join(buffer).strip()
        parsed = interview.parse_grade_json(raw)
        if parsed:
            md_text = interview.render_grade_markdown(parsed)
            gid = db.save_interview_log(
                b.qid, category, b.answer, parsed["content"], parsed["logic"],
                parsed["express"], md_text, b.think_ms, b.answer_ms)
            yield _sse({"type": "result", "data": parsed})
            yield _sse({"type": "saved", "text": str(gid)})
        elif raw:
            gid = db.save_interview_log(
                b.qid, category, b.answer, 0, 0, 0, raw, b.think_ms, b.answer_ms)
            yield _sse({"type": "fallback", "text": raw})
            yield _sse({"type": "saved", "text": str(gid)})
        else:
            yield _sse({"type": "error", "text": "点评未返回内容，请重试"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/essay/history")
def api_essay_history():
    items = db.list_essay_grades()
    # 列表只带总分摘要（结果第一行），不返回全文
    for it in items:
        first = (it["result"] or "").split("\n", 1)[0][:60]
        it["summary"] = first
        it.pop("result", None)
        it.pop("answer", None)
    return {"items": items}


@app.get("/api/essay/history/{gid}")
def api_essay_history_detail(gid: int):
    it = db.get_essay_grade(gid)
    if not it:
        raise HTTPException(404)
    return it


# ---------------- 申论 / 综应 真题库 ----------------

_ESSAY_Q_PATH = DATA_DIR / "essay_questions.json"


def _load_essay_questions() -> list[dict]:
    if not _ESSAY_Q_PATH.exists():
        return []
    try:
        return json.loads(_ESSAY_Q_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


@app.get("/api/essay/questions")
def api_essay_questions():
    """真题列表（不含材料/答案正文，减小传输）。"""
    return {"items": [
        {"id": q["id"], "exam": q.get("exam", ""), "category": q.get("category", ""),
         "title": q.get("title", ""), "total_score": q.get("total_score", 0),
         "has_reference": bool(q.get("reference"))}
        for q in _load_essay_questions()
    ]}


@app.get("/api/essay/question/{qid}")
def api_essay_question_detail(qid: str):
    for q in _load_essay_questions():
        if q["id"] == qid:
            return q
    raise HTTPException(404)


# ---------------- 真题套卷 ----------------

@app.get("/api/exams")
def api_exams():
    return {"items": db.list_exams()}


class ExamPaperIn(BaseModel):
    exam: str


@app.post("/api/exam-paper")
def api_exam_paper(b: ExamPaperIn):
    ids = db.exam_paper_ids(b.exam)
    n = len(ids)
    minutes = max(10, round(n * 0.89)) if n else 0
    return {"ids": ids, "minutes": minutes, "name": b.exam}


# ---------------- C类职测智能组卷 ----------------

# 事业单位联考C类《职测》规格：100题/90分钟/满分150
# 模块顺序与分值：常识20×1、言语25×1.6、数量分析15×2（数量5+资料10）、判断30×1.5、综合分析10×1.5
_CE_SPEC = [
    ("常识判断", 20, 1.0, None, None),
    ("言语理解", 25, 1.6, None, None),
    ("数量关系", 5, 2.0, None, None),
    ("资料分析", 10, 2.0, None, "material"),   # 按整篇材料抽
    ("判断推理", 30, 1.5, None, [
        ("图形推理", 5), ("定义判断", 10), ("类比推理", 5), ("逻辑判断", 10),
    ]),
    ("综合分析", 10, 1.5, ["策略制定", "实验设计"], None),
]


@app.post("/api/ce-paper")
def api_ce_paper():
    """按C类职测规格智能组卷。模块内按真实卷面顺序排列。"""
    import random
    conn = db.connect()
    try:
        cur = conn.cursor()
        ids: list[int] = []
        weights: dict[int, float] = {}
        short: list[str] = []

        def _take_from(where_sql: str, args: tuple, n: int) -> list[int]:
            rows = cur.execute(
                f"SELECT id FROM documents WHERE {where_sql}", args).fetchall()
            pool = [r[0] for r in rows]
            random.shuffle(pool)
            return pool[:n]

        for module, n, score, kd_filter, sub_spec in _CE_SPEC:
            taken: list[int] = []
            if sub_spec == "material":
                # 资料分析：按整篇材料抽（同材料小题连续），凑满 n 题
                fp_rows = cur.execute(
                    "SELECT material_fp FROM documents "
                    "WHERE module='资料分析' AND material_fp!='' "
                    "GROUP BY material_fp HAVING COUNT(*)>=5 "
                    "ORDER BY RANDOM()").fetchall()
                for (fp,) in fp_rows:
                    if len(taken) >= n:
                        break
                    sub = cur.execute(
                        "SELECT id FROM documents WHERE material_fp=? ORDER BY id LIMIT 5",
                        (fp,)).fetchall()
                    taken.extend(r[0] for r in sub)
                taken = taken[:n]
            elif sub_spec:
                # 判断推理：按真实卷面顺序（图推→定义→类比→逻辑）分大类抽
                for top_kd, sub_n in sub_spec:
                    sub = _take_from(
                        "module=? AND kaodian LIKE ?", (module, top_kd + "%"), sub_n)
                    taken.extend(sub)
                    if len(sub) < sub_n:
                        short.append(f"{top_kd}（{len(sub)}/{sub_n}）")
            elif kd_filter:
                # 综合分析：策略制定/实验设计按材料组抽取（同材料小题连续）
                # 真实卷面：91-95策略制定（1组材料5题），96-100实验设计（1组材料5题）
                # 题库材料组3-4题/组，策略2组+实验2组凑满10题
                for kd in kd_filter:
                    fp_rows = cur.execute(
                        "SELECT material_fp FROM documents "
                        "WHERE module=? AND kaodian=? AND material_fp!='' "
                        "GROUP BY material_fp ORDER BY RANDOM() LIMIT 2",
                        (module, kd)).fetchall()
                    for (fp,) in fp_rows:
                        if len(taken) >= n:
                            break
                        sub = cur.execute(
                            "SELECT id FROM documents WHERE material_fp=? ORDER BY id",
                            (fp,)).fetchall()
                        taken.extend(r[0] for r in sub)
                # 单题补满（实验设计有4道单题）
                if len(taken) < n:
                    placeholders = ",".join("?" * len(kd_filter))
                    single_rows = cur.execute(
                        f"SELECT id FROM documents WHERE module=? AND kaodian IN ({placeholders}) "
                        "AND (material_fp='' OR material_fp IS NULL) ORDER BY RANDOM()",
                        (module, *kd_filter)).fetchall()
                    taken.extend(r[0] for r in single_rows)
                taken = taken[:n]
            else:
                taken = _take_from("module=?", (module,), n)

            if len(taken) < n:
                short.append(f"{module}（{len(taken)}/{n}）")
            ids.extend(taken)
            for i in taken:
                weights[i] = score

        return {
            "ids": ids,
            "weights": weights,
            "minutes": 90,
            "full_score": 150,
            "name": "事业单位C类·职测智能组卷",
            "short": short,
        }
    finally:
        conn.close()


# ---------------- 辨析卡进度 ----------------

@app.get("/api/cards/progress")
def api_cards_progress():
    return db.cards_progress()


# ---------------- 题库导出（打印为 PDF） ----------------

@app.get("/api/export/print")
def api_export_print(
    q: str = "", kind: str = "真题", module: str = "", daclass: str = "",
    region: str = "", year: str = "", limit: int = 100, with_answer: int = 1,
    doc_ids: str = "",  # 逗号分隔的 doc_id 列表（用于单题/多题/错题本导出）
    heading: str = "",  # G5：自定义大标题（如「错题本导出」），留空用「题库导出」
):
    limit = max(1, min(500, limit))

    # 统一「先批量取题、再拼装」：原先逐题调 db.get_doc（每题新建连接 + 查 marks/
    # answers），100 题要 16.3s；改成一次 IN 查询后 0.31s（53×）。
    if doc_ids:
        try:
            ids = [int(x) for x in doc_ids.split(",") if x.strip().isdigit()][:50]
        except ValueError:
            ids = []
        brief = db.get_docs_brief(ids)
        picked = [brief[i] for i in ids if i in brief]   # 保持传入顺序
    else:
        rows, total = db.search_docs(
            q=q, kind=kind, module=module, daclass=daclass,
            region=region, year=year, page=1, page_size=limit,
        )
        brief = db.get_docs_brief([r["id"] for r in rows])
        picked = [brief[r["id"]] for r in rows if r["id"] in brief]

    items = []
    for d in picked:
        data = d["data"]
        answer = next((o["label"] for o in (data.get("options") or []) if o.get("correct")), "")
        items.append({
            "title": d["title"], "module": d["module"], "exam": d["exam"],
            "stem": data.get("stem", ""), "options": data.get("options") or [],
            "answer": answer, "analysis": data.get("official") or data.get("reasoning") or "",
        })
    if doc_ids:
        total = len(items)

    title_suffix = f"指定 {len(items)} 题" if doc_ids else f"{total} 题（本次 {len(items)} 题）"
    # 拼装逻辑与手机端共用（app/print_export.py），题干里的图片标签靠 rich_text 保留
    html = render_html(items, with_answer=bool(with_answer),
                       heading=heading or "题库导出", title_suffix=title_suffix)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


# ---------------- 题单分享与好友 PK（功能 3.3） ----------------

class ShareCreateIn(BaseModel):
    ids: list[int] = []
    title: str = ""
    author: str = ""
    note: str = ""
    result: dict | None = None


@app.post("/api/share/create")
def api_share_create(b: ShareCreateIn, request: Request):
    """把一组题编码成自包含分享码（只含题号，不含题目内容与个人数据）。"""
    code = share.encode_set(b.ids, b.title, b.author, b.result)
    if not code:
        raise HTTPException(400, "题目列表为空，无法生成分享码")
    title = (b.title or "").strip()[:40]
    author = (b.author or "").strip()[:16]
    db.save_shared_set(code, title, b.ids[:200], author, (b.note or "").strip()[:80])
    base = str(request.base_url).rstrip("/")
    return {
        "ok": True, "code": code, "title": title,
        "count": len(b.ids), "author": author,
        "url": share.share_url(base, code),
        "url_mobile": share.share_url(base, code, mobile=True),
    }


class ShareOpenIn(BaseModel):
    code: str = ""


@app.post("/api/share/open")
def api_share_open(b: ShareOpenIn):
    """解析分享码；只保留本地题库中真实存在的题，并回报缺失数量。"""
    code = (b.code or "").strip()
    data = share.decode_set(code)
    if not data:
        raise HTTPException(400, "分享码无效或已损坏")
    items = db.get_docs_batch(data["ids"])
    found = [d["id"] for d in items]
    try:
        db.bump_shared_set_play(code)
    except Exception:
        pass
    return {
        "ok": True,
        "title": data["title"],
        "author": data.get("author", ""),
        "result": data.get("result"),
        "ids": found,
        "missing": len(data["ids"]) - len(found),
        "total": len(data["ids"]),
    }


@app.get("/api/share/list")
def api_share_list():
    """本机创建过的分享题单（便于二次分发）。"""
    return {"items": db.list_shared_sets()}


class PkSubmitIn(BaseModel):
    code: str = ""
    who: str = ""
    total: int = 0
    ok: int = 0
    ms: int = 0


@app.post("/api/pk/submit")
def api_pk_submit(b: PkSubmitIn):
    """提交本次成绩并返回该题单 PK 榜（正确率优先、用时次之）。"""
    code = (b.code or "").strip()
    if not code:
        raise HTTPException(400, "缺少题单分享码")
    rid = db.save_pk_record(code, (b.who or "").strip()[:16], b.total, b.ok, b.ms)
    return {
        "ok": True, "id": rid,
        "best": db.pk_best(code),
        "records": db.list_pk_records(code, limit=20),
    }


@app.get("/api/pk/{code}")
def api_pk_list(code: str):
    return {"records": db.list_pk_records(code, limit=50), "best": db.pk_best(code)}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
