"""E-5 缓存版本守卫（docs/03-开发/2026-10-31-行测申论速查优化方向.md B4-E5）。

背景：静态资源靠 `?v=` 破缓存，Service Worker 另有自己的 `VERSION`。
两处不一致时会出现「联网看到新版、离线还是旧版」，而且**内容改了忘升版本**
在本地几乎看不出来（浏览器缓存命中），所以用测试兜住：

  1. 三处（桌面 index.html / 手机 index.html / sw.js）版本号必须完全一致；
  2. 格式 `YYYYMMDD-slN`，且不早于本次改动基线（只增不减）；
  3. index.html 里每个本地 css/js 引用都要带 `?v=`，新增文件不会漏；
  4. sw.js 的 VERSION 必须由同一个版本号拼出来，避免手写两遍。

运行：python -m pytest tests/test_notes_version.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DESKTOP_HTML = ROOT / "static" / "index.html"
MOBILE_HTML = ROOT / "static" / "m" / "index.html"
SW_JS = ROOT / "static" / "sw.js"

# 本次交互改造（P4）升到的版本；只允许往上走，不允许回落
BASELINE = "20261115-sl2"
VER_RE = re.compile(r"^\d{8}-sl\d+$")
Q_V = re.compile(r"[?&]v=([0-9]{8}-sl[0-9]+)")


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _versions(path: Path) -> set[str]:
    return set(Q_V.findall(_text(path)))


def _sw_version() -> str:
    m = re.search(r'const VERSION = "goshore-([^"]+)"', _text(SW_JS))
    assert m, "sw.js 里找不到 VERSION 常量"
    return m.group(1)


def _key(ver: str) -> tuple[int, int]:
    day, n = ver.split("-sl")
    return int(day), int(n)


# ---------------------------------------------------------------- 一致性

def test_all_asset_refs_use_one_version():
    """同一份页面里不能出现两个版本号，否则部分资源命中旧缓存。"""
    for path in (DESKTOP_HTML, MOBILE_HTML):
        vers = _versions(path)
        assert len(vers) == 1, f"{path.name} 出现多个版本号：{sorted(vers)}"


def test_triple_version_match():
    """桌面 / 手机 / Service Worker 三处版本必须一致。"""
    desk = _versions(DESKTOP_HTML)
    mob = _versions(MOBILE_HTML)
    sw = _sw_version()
    assert desk == mob, f"桌面 {sorted(desk)} ≠ 手机 {sorted(mob)}"
    assert desk == {sw}, f"sw.js 的 {sw} 与页面 {sorted(desk)} 不一致"


def test_version_format():
    for path in (DESKTOP_HTML, MOBILE_HTML):
        for v in _versions(path):
            assert VER_RE.match(v), f"{path.name} 的版本号格式不对：{v}"


def test_version_never_goes_backwards():
    """版本只增不减：回落会让老用户拿着新内容跑旧逻辑。"""
    for v in _versions(DESKTOP_HTML) | {_sw_version()}:
        assert _key(v) >= _key(BASELINE), f"版本 {v} 低于基线 {BASELINE}"


# ---------------------------------------------------------------- 防漏

@pytest.mark.parametrize("html", [DESKTOP_HTML, MOBILE_HTML])
def test_every_local_asset_is_versioned(html):
    """新增 css/js 忘了带 ?v= 时，这里会红。"""
    text = _text(html)
    refs = re.findall(r'(?:src|href)="(/[^"]+\.(?:js|css))(?:\?[^"]*)?"', text)
    missing = [r for r in refs if f'{r}?v=' not in text]
    assert not missing, f"{html.name} 有资源没带版本号：{missing}"


def test_sw_version_built_from_same_token():
    """sw.js 的 VERSION 应直接引用版本号，不要另写一份日期。"""
    text = _text(SW_JS)
    assert f'"goshore-{_sw_version()}"' in text
    # 版本号只在一个常量里出现一次，其它地方引用 CACHE/VERSION 变量
    assert text.count(_sw_version()) <= 2, "sw.js 里版本号出现多次，容易改一半"
