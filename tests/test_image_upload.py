"""图片上传的回归守卫：压缩函数必须真的 resolve，不能永挂。

历史缺陷（`c2e8bae` 引入，2026-11-01 才发现）：桌面端 `static/app.js` 的
`compressImageFile` 里漏了 `img.src = e.target.result`，却在 `reader.onload`
里又把 `reader.readAsDataURL(file)` 调了一遍。于是 `img` 永远不会触发
`onload`，Promise 永挂。

它不是「图片显示不出来」这种局部问题：这个 Promise 被 `await` 串在
`fileInput.onchange` 的 for 循环里，一旦挂住，`renderPreviews()` 不执行、
后续文件不处理、上传按钮点了也没反应 —— 用户看到的就是「上传图片无反应」。

移动端两份实现（`compressImageFile` / 闭包里的 `compressImage`）当时是对的，
所以这里用运行时验证桌面端、静态断言守移动端，避免以后谁再照着改回去。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"

_RUNNER = r"""
const fn = require("./fn.js");

function installMocks(ok) {
  global.FileReader = class {
    readAsDataURL() {
      setTimeout(() => {
        if (!ok) { this.onerror && this.onerror(); return; }
        this.onload({ target: { result: "data:image/png;base64,AAAA" } });
      }, 0);
    }
  };
  // 关键：onload 必须在 set src 之后触发，模拟真实浏览器；如果函数没写
  // img.src，这个回调永远不会被调用，Promise 就永挂。
  global.Image = class {
    constructor() { this.width = 2000; this.height = 1000; }
    set src(v) { this._src = v; setTimeout(() => (ok ? this.onload && this.onload() : this.onerror && this.onerror()), 0); }
    get src() { return this._src; }
  };
  global.document = {
    createElement: () => ({
      width: 0, height: 0,
      getContext: () => ({ drawImage() {} }),
      toDataURL: () => "data:image/jpeg;base64,OK",
    }),
  };
}

const TIMEOUT = "__TIMEOUT__";
const withTimeout = (p) => Promise.race([
  p, new Promise((r) => setTimeout(() => r(TIMEOUT), 2500)),
]);

(async () => {
  const out = {};
  installMocks(true);
  out.happy = await withTimeout(fn({ name: "a.png" }));
  installMocks(false);
  out.broken = await withTimeout(fn({ name: "b.png" }));
  console.log(JSON.stringify(out));
})();
"""


def _extract_function(text: str, name: str) -> str:
    """从源文件里抠出 `function name(...) {...}` 的完整源码（按大括号配对）。"""
    start = text.find(f"function {name}(")
    assert start >= 0, f"找不到函数 {name}"
    brace = text.find("{", start)
    assert brace >= 0, f"{name} 没有函数体"
    depth = 0
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError(f"{name} 函数体括号不闭合")


@pytest.fixture()
def compression_result(node_exe: str, tmp_path: Path) -> dict:
    """把桌面端 compressImageFile 抠出来，在 node 里用 mock DOM 跑一遍。"""
    src = _extract_function(APP_JS.read_text(encoding="utf-8"), "compressImageFile")
    (tmp_path / "fn.js").write_text(
        "module.exports = " + src + ";\n", encoding="utf-8")
    (tmp_path / "run.js").write_text(_RUNNER, encoding="utf-8")

    proc = subprocess.run([node_exe, "run.js"], cwd=str(tmp_path),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"node 执行失败：{proc.stderr[-1500:]}"
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def test_compress_image_resolves_on_success(compression_result: dict):
    """正常图片必须压出 data URL；永挂时这里会拿到 __TIMEOUT__。"""
    got = compression_result["happy"]
    assert got != "__TIMEOUT__", (
        "compressImageFile 的 Promise 没有 resolve —— 多半是漏了 "
        "`img.src = e.target.result`，img 不会 onload，UI 表现为「上传图片无反应」")
    assert got.startswith("data:image/jpeg"), f"压缩结果不是 JPEG data URL：{got[:40]}"


def test_compress_image_resolves_empty_on_decode_failure(compression_result: dict):
    """解码失败也要 resolve("")：否则一张坏图就能把整条上传链堵死。"""
    got = compression_result["broken"]
    assert got != "__TIMEOUT__", "图片解码失败时 Promise 永挂，调用方会一直转圈"
    assert got == "", f"失败时应返回空串交给调用方提示，实际是 {got!r}"


def test_compress_image_sets_img_src():
    """静态兜底：直接点名那行必需代码，报错信息比超时更好懂。"""
    body = _extract_function(APP_JS.read_text(encoding="utf-8"), "compressImageFile")
    assert "img.src" in body, "compressImageFile 没给 img 设 src"
    assert "reader.readAsDataURL(file)" in body, "compressImageFile 没真正开始读文件"


@pytest.mark.parametrize("path, name", [(APP_JS, "compressImageFile"), (M_JS, "compressImageFile")])
def test_both_ends_have_error_fallbacks(path: Path, name: str):
    """两端都要有 reader.onerror / img.onerror：坏文件不能变成永久等待。"""
    body = _extract_function(path.read_text(encoding="utf-8"), name)
    assert re.search(r"reader\.onerror", body), f"{path.name} 缺 reader.onerror"
    assert re.search(r"img\.onerror", body), f"{path.name} 缺 img.onerror"


def test_mobile_compress_image_sets_img_src():
    """移动端 AI 答疑用的是闭包里的 compressImage，同样得有 img.src。"""
    text = M_JS.read_text(encoding="utf-8")
    start = text.find("const compressImage = (file)")
    assert start >= 0, "移动端找不到 compressImage"
    chunk = text[start:start + 900]
    assert "img.src = e.target.result" in chunk, "移动端 compressImage 没给 img 设 src"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_image_failure_is_reported_to_user(path: Path):
    """压缩返回空串时必须 toast，不能静默丢图（静默正是这次被当成「无反应」的原因）。"""
    text = path.read_text(encoding="utf-8")
    assert "图片读取失败" in text, f"{path.name} 缺少图片读取失败的用户提示"
