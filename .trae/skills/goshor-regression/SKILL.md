---
name: goshor-regression
description: GOSHORE 项目一键回归自查，编译检查后自动验证后端 API 与全部前端页面（无头浏览器、零 JS 报错）。用户要求自查、回归测试、验证改动或提交前检查时使用；不用于开发功能本身。
---

# GOSHORE 回归自查

对 FastAPI + SQLite + 原生 JS SPA 做端到端回归：后端 API 冒烟 + Playwright 无头浏览器逐页验证。目标是在提交前发现「代码没加载、接口报错、JS 运行时错误、关键交互失效」四类问题。

## 执行步骤

### 1. 编译全部 Python 文件

```powershell
python -m compileall -q app scripts
```

有报错先修复，不进入下一步。

### 2. 重启本地服务器（必须）

Python 代码不会热加载，改动后不重启会测到旧代码（曾因此误判考点抽题异常）。

```powershell
$c = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($c) { Stop-Process -Id $c[0].OwningProcess -Force; Start-Sleep 1 }
```

然后用后台方式在 `d:\GOSHORE` 启动 `python -u run.py`，等待约 5 秒，确认
`curl.exe -s http://127.0.0.1:8765/ -o NUL -w "%{http_code}"` 返回 200。

### 3. 运行回归脚本

```powershell
python .trae/skills/goshor-regression/scripts/regression.py
```

脚本自动完成：

- **API 冒烟**：考点树、按细分点前缀抽题、大类混练抽题、常规组卷、列式生成与结构校验、列式结算落库（测完自动清除测试记录，不污染数据）、周报输出
- **全页面遍历**：自动读取 [index.html](file:///d:/GOSHORE/static/index.html) 侧边栏的全部 hash 入口逐页访问，捕获未捕获的 JS 运行时错误，要求 **0 条 pageerror**
- **深度断言**：列式专项（开始→4 选项→判分讲解）、判断专项（大类与高频考点渲染）、科技文献（就绪→开始→做题面板）、周报（汇总卡与对比表）

### 4. 判定与失败处理

- 退出码 0 且全部 `[PASS]` 才算通过，可进入提交环节。
- 任一 `[FAIL]`：按输出中的路由/接口名定位，修复后从步骤 1 重新执行，不要只重跑单项。
- API 通过但页面 FAIL：优先检查该页渲染函数里的空数据访问和选择器是否与实际 DOM 一致。
- 页面 FAIL 且伴随 pageerror：先修 JS 错误，断言失败通常是连带结果。

## 注意事项

- 环境是 Windows PowerShell：不要用 bash heredoc、不要依赖 `&&` 链式命令。
- POST JSON 不要用 curl 内联引号（PowerShell 会吞引号）；脚本内部用 urllib 发请求，无此问题。
- 不要用 esprima 检查 JS（不支持可选链等 ES2020 语法会误报）；以无头浏览器 pageerror 为准。
- 脚本不创建任何临时文件；测试写入的列式结算记录会立即从 `data/goshor.db` 删除，切勿把数据库提交到 git。

## 维护

- 侧边栏新增页面后，全页面遍历自动覆盖，无需改脚本。
- 新页面需要深度交互断言时，在脚本的 `DEEP_CHECKS` 中按现有格式追加一个处理函数。
