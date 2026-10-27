"""前端全局错误兜底（P3）：`window.onerror` + `unhandledrejection`。

为什么值得单独立一个测试文件：这两个钩子只在「出 bug 时」才跑，正常路径
永远覆盖不到，回归时也没人会发现它被删掉了 —— 而它正是用户侧唯一的
「出错时不是白屏/哑火」保障。

分层：
  - 静态：钩子存在、双端共用（在 shared/core.js 而不是各端各写一份）、
    加载顺序正确（core.js 必须先于 app.js / m.js）、不清空整页；
  - 行为：在 node 沙箱里真跑 ErrorGuard，验证去重、上限、toast 签名。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "static" / "shared" / "core.js"
INDEX = ROOT / "static" / "index.html"
M_INDEX = ROOT / "static" / "m" / "index.html"

# node 侧跑 ErrorGuard 的沙箱脚本。占位符 __CORE__ / __BODY__ 由 Python 填。
# 用占位符替换而不是 f-string：JS 里的 `{` 在 f-string 中必须写成 `{{`，
# 极易写错（本项目已踩过一次 SyntaxError）。
_JS_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(__CORE__, 'utf8');
const chunk = src.slice(src.indexOf('const ErrorGuard'),
                        src.indexOf('/* shared-core:end */'));

const toasts = [];
const logs = [];
const win = { addEventListener(ev, fn) { (this._h = this._h || {})[ev] = fn; } };
const doc = {
  documentElement: {},
  body: { appendChild() {} },
  querySelector() { return null; },
  createElement() {
    return { setAttribute() {}, style: {}, remove() {}, set textContent(v) {} };
  },
};

// body 在 make 的函数作用域内执行，可直接用 window / toast / guard。
// 注意：body 是**运行时**形参，不能在构造 make 的字符串时就拼进去 ——
// 那会在外层作用域求值 body（未定义）。
const make = new Function(
  'window', 'document', 'console', 'setTimeout', 'toast', 'Pref',
  'Date', 'Object', 'String', 'JSON', 'body',
  chunk + '\nreturn function () {\n' +
  '  return (new Function("window", "toast", "guard", body))' +
  '(window, toast, ErrorGuard);\n};');

make(win, doc, { error(msg) { logs.push(String(msg)); } }, function () { return 0; },
     function (msg, ms) { toasts.push([msg, ms]); },
     { get() { return 'auto'; }, set() {} },
     Date, Object, String, JSON, __BODY__)();

console.log(JSON.stringify({ toasts: toasts, console: logs }));
"""


def _norm(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def _find_node():
    for name in ("node", "node.exe"):
        p = shutil.which(name)
        if p:
            return p
    bundled = (Path.home() / ".dsh" / "dsh-runtimes" / "dsh-primary-runtime"
               / "dependencies" / "node" / "bin" / "node.exe")
    return str(bundled) if bundled.exists() else None


def _run_guard(body: str) -> dict:
    """在 node 沙箱里跑 ErrorGuard，返回它产生的提示列表 [ [msg, ms], ... ]。

    用 node 而不是在 pytest 侧模拟：ErrorGuard 是浏览器全局脚本，只有真跑一遍
    才知道 `this` 绑定、事件对象形状、以及 toast 的第二个参数有没有写错。
    """
    node = _find_node()
    if node is None:
        pytest.skip("找不到 node，跳过前端行为验证")
    script = _JS_HARNESS.replace("__CORE__", json.dumps(str(CORE)))
    script = script.replace("__BODY__", json.dumps(body))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def guard_max() -> int:
    src = _norm(CORE)
    m = re.search(r"_MAX_SHOW:\s*(\d+)", src)
    assert m, "ErrorGuard._MAX_SHOW 未定义"
    return int(m.group(1))


# ---------------- 静态约束 ----------------

def test_hooks_are_registered():
    """两个钩子都要真的挂上 addEventListener，且 init 被调用过。"""
    src = _norm(CORE)
    assert 'window.addEventListener("error"' in src
    assert 'window.addEventListener("unhandledrejection"' in src
    assert re.search(r"ErrorGuard\.init\(\)", src), "ErrorGuard.init() 未被调用"


def test_hooks_live_in_shared_core_not_per_platform():
    """兜底必须放在双端共用的 core.js：各写一份必然漂移。"""
    assert "const ErrorGuard" in _norm(CORE)
    for path in (ROOT / "static" / "app.js", ROOT / "static" / "m" / "m.js"):
        src = _norm(path)
        assert "unhandledrejection" not in src, (
            f"{path.name} 里出现了 unhandledrejection —— 兜底应只在 shared/core.js 维护一份")


@pytest.mark.parametrize("html", [INDEX, M_INDEX])
def test_core_loaded_before_own_bundle(html: Path):
    """core.js 必须在 app.js / m.js 之前加载，否则启动期的错误抓不到。"""
    src = _norm(html)
    own = "/app.js" if html == INDEX else "/m/m.js"
    assert "/shared/core.js" in src
    assert src.index("/shared/core.js") < src.index(own)


def test_does_not_wipe_view_on_error():
    """兜底不能把整页清空 —— 局部报错不该让用户失去可用的部分。"""
    src = _norm(CORE)
    guard = src[src.index("const ErrorGuard"):src.index("ErrorGuard.init()")]
    assert "replaceChildren" not in guard
    assert 'innerHTML = ""' not in guard
    assert "location.reload" not in guard


# ---------------- 行为约束（真跑） ----------------

def test_error_is_toasted_once_per_message():
    """同一条错误重复抛（渲染循环里每帧一次）只提示一次，不能刷屏。"""
    result = _run_guard("""
for (let i = 0; i < 20; i++) {
  window._h['error']({ message: 'boom', filename: 'a.js', lineno: 1 });
}
""")
    assert len(result["toasts"]) == 1, result["toasts"]
    msg, ms = result["toasts"][0]
    assert "页面出错：boom" in msg
    # 第二个参数必须是毫秒数（曾误传类型名 "error"，会让提示一闪而过）
    assert isinstance(ms, int), result["toasts"][0]


def test_rejection_is_reported_separately():
    """未处理的 Promise 拒绝走「后台操作失败」，与同步错误区分开。"""
    result = _run_guard("""
window._h['unhandledrejection']({ reason: new Error('net down') });
""")
    assert len(result["toasts"]) == 1
    assert "后台操作失败：net down" in result["toasts"][0][0]


def test_toast_count_is_capped():
    """连环报错（每条都不同）不能把页面刷满提示。"""
    result = _run_guard("""
for (let i = 0; i < 50; i++) {
  window._h['error']({ message: 'e' + i, filename: 'a.js', lineno: i });
}
""")
    assert len(result["toasts"]) == guard_max(), result["toasts"]


def test_resource_load_failure_is_labelled():
    """图标 404 不该被说成「页面出错」——那类 error 事件没有 message。

    而且不能弹提示：坏图浏览器自带破图图标，再弹一条既误导又浪费提示预算
    （_MAX_SHOW 只有 3 条，一道题 3 张图就把真正的脚本错误挤没了）。
    这里断言「归类为 resource、但不产生 toast」。
    """
    result = _run_guard("""
window._h['error']({ target: { tagName: 'IMG', src: '/icons/x.png' } });
""")
    assert result["toasts"] == [], result["toasts"]
    assert result["console"] == ["[goshore:resource]"], result["console"]
