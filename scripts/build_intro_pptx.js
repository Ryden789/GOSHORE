// 由 docs/05-宣传/软件介绍PPT.html 转制的可编辑 PPTX
// 配色沿用产品「书房纸墨风」：宣纸底 / 墨色字 / 朱砂印章
const pptxgen = require("pptxgenjs");

// ---- 品牌色（pptxgenjs 要求 6 位、不带 #）----
const PAPER = "F7F2E7";
const PAPER_DEEP = "EFE7D5";
const INK = "2F2A26";
const INK_SOFT = "5C534A";
const CINNABAR = "B03A2E";
const INDIGO = "2C4A6E";
const WHITE = "FFFFFF";

const FONT = "Microsoft YaHei";

const W = 13.333;
const H = 7.5;
const M = 0.65;              // 页边距

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";  // 必须先设，否则默认只有 10 英寸宽
pres.author = "GOSHORE";
pres.company = "GOSHORE";
pres.title = "上岸题库 · 软件介绍";
pres.subject = "为事业单位联考 C 类打造的本地 AI 题库";

// ---- 复用的视觉母题：朱砂印章（每页左上角一枚）----
function seal(slide, x, y, size, text, opts = {}) {
  const fillColor = opts.invert ? PAPER : CINNABAR;
  const textColor = opts.invert ? CINNABAR : WHITE;
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w: size, h: size, fill: { color: fillColor },
    line: { color: fillColor, width: 0 }, rectRadius: 0.08,
  });
  slide.addText(text, {
    x, y, w: size, h: size, margin: 0,
    align: "center", valign: "middle",
    fontSize: opts.fontSize || size * 26, bold: true,
    color: textColor, fontFace: FONT,
  });
}

// ---- 页眉：印章 + 栏目名 + 小标题 ----
function header(slide, kicker, title, dark = false) {
  seal(slide, M, 0.52, 0.52, "岸", { fontSize: 15 });
  slide.addText(kicker, {
    x: M + 0.72, y: 0.56, w: 6, h: 0.28, margin: 0,
    fontSize: 11, color: CINNABAR, bold: true, charSpacing: 2, fontFace: FONT,
  });
  slide.addText(title, {
    x: M + 0.72, y: 0.84, w: W - 2 * M - 0.72, h: 0.62, margin: 0,
    fontSize: 34, bold: true, color: dark ? PAPER : INK, fontFace: FONT,
  });
}

// ---- 页脚 ----
function footer(slide, n, dark = false) {
  slide.addText("GOSHORE · 上岸题库", {
    x: M, y: H - 0.5, w: 5, h: 0.26, margin: 0,
    fontSize: 9, color: dark ? "9A8F82" : "8B8073", fontFace: FONT,
  });
  slide.addText(`${n} / 12`, {
    x: W - M - 1, y: H - 0.5, w: 1, h: 0.26, margin: 0,
    fontSize: 9, color: dark ? "9A8F82" : "8B8073", align: "right", fontFace: FONT,
  });
}

// ============================================================ 1 封面
{
  const s = pres.addSlide();
  s.background = { color: INK };

  seal(s, M, 0.75, 0.66, "岸", { fontSize: 20, invert: true });
  s.addText("GOSHORE · 备考工具发布", {
    x: M + 0.86, y: 0.82, w: 7, h: 0.5, margin: 0,
    fontSize: 14, color: "C8BDAE", charSpacing: 3, fontFace: FONT,
  });

  s.addText("上岸题库", {
    x: M, y: 2.05, w: 9, h: 1.15, margin: 0,
    fontSize: 66, bold: true, color: PAPER, fontFace: FONT,
  });
  s.addText("为事业单位联考 C 类考生打造的本地 AI 题库应用 —— 你的口袋私教", {
    x: M, y: 3.3, w: 10.5, h: 0.5, margin: 0,
    fontSize: 18, color: "C8BDAE", fontFace: FONT,
  });

  // 四个标签
  const tags = ["23,491 篇题库", "完全离线", "AI 错题讲解", "零会员费"];
  let tx = M;
  tags.forEach((t) => {
    const w = 0.55 + t.length * 0.155;
    s.addShape(pres.ShapeType.roundRect, {
      x: tx, y: 4.28, w, h: 0.5, fill: { color: "423A33" },
      line: { color: "5A4F46", width: 1 }, rectRadius: 0.1,
    });
    s.addText(t, {
      x: tx, y: 4.28, w, h: 0.5, margin: 0,
      align: "center", valign: "middle", fontSize: 13, color: PAPER, fontFace: FONT,
    });
    tx += w + 0.22;
  });

  s.addText("逢 考 必 过 · 上 岸", {
    x: M, y: 5.75, w: 9, h: 0.4, margin: 0,
    fontSize: 15, color: CINNABAR, bold: true, charSpacing: 5, fontFace: FONT,
  });
  footer(s, 1, true);
  s.addNotes("开场 30 秒：这是一个为事业单位联考 C 类考生做的本地 AI 题库。四个关键词：两万三千篇题库、完全离线、AI 错题讲解、零会员费。");
}

// ============================================================ 2 三道坎
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "为 什 么 还 要 一 款 新 工 具", "备考路上，有三道坎");

  const items = [
    ["坎 · 一", "会员墙太高", "AI 讲解、视频解析、模考精讲……最有价值的功能，全锁在会员付费墙后面。"],
    ["坎 · 二", "体验太嘈杂", "开屏广告、推送轰炸、课程推销，刷题心流不断被打断，专注成了奢侈品。"],
    ["坎 · 三", "数据不在手", "作答记录、错题本存放在别人的服务器上，想离线刷题？想导出数据？很难。"],
  ];
  const cw = (W - 2 * M - 2 * 0.34) / 3;
  items.forEach((it, i) => {
    const x = M + i * (cw + 0.34);
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 1.95, w: cw, h: 3.15, fill: { color: WHITE },
      line: { color: "E3D9C6", width: 1 }, rectRadius: 0.08,
    });
    s.addText(it[0], {
      x: x + 0.34, y: 2.2, w: cw - 0.68, h: 0.3, margin: 0,
      fontSize: 11, color: CINNABAR, bold: true, charSpacing: 2, fontFace: FONT,
    });
    s.addText(it[1], {
      x: x + 0.34, y: 2.62, w: cw - 0.68, h: 0.55, margin: 0,
      fontSize: 21, bold: true, color: INK, fontFace: FONT,
    });
    s.addText(it[2], {
      x: x + 0.34, y: 3.28, w: cw - 0.68, h: 1.55, margin: 0,
      fontSize: 13, color: INK_SOFT, lineSpacingMultiple: 1.5, fontFace: FONT,
    });
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 5.42, w: W - 2 * M, h: 0.86, fill: { color: PAPER_DEEP },
    line: { color: PAPER_DEEP, width: 0 }, rectRadius: 0.08,
  });
  s.addText("能不能有一款工具，不收会员、不打广告、只为你上岸？", {
    x: M, y: 5.42, w: W - 2 * M, h: 0.86, margin: 0,
    align: "center", valign: "middle",
    fontSize: 19, bold: true, color: INK, fontFace: FONT,
  });
  footer(s, 2);
  s.addNotes("45 秒：第一坎会员墙，最有价值的 AI 讲解都在付费墙后；第二坎注意力被广告打断；第三坎数据不在自己手里。所以想做一款不收会员不打广告的工具。");
}

// ============================================================ 3 产品定位
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "产 品 定 位", "把会员功能，做成默认能力");

  const items = [
    ["本地", INDIGO, "数据与题库都在本机", "FastAPI + SQLite 全本地运行，题库离线可用，作答记录永不上传。"],
    ["智能", CINNABAR, "AI 深度参与学习闭环", "DeepSeek 驱动错题讲解、变式出题、AI 模拟卷，不止刷题，更懂纠错。"],
    ["免费", "5C534A", "零会员 · 全开源", "代码托管 GitHub，功能全量开放，没有付费墙，也没有广告位。"],
  ];
  const cw = (W - 2 * M - 2 * 0.4) / 3;
  items.forEach((it, i) => {
    const x = M + i * (cw + 0.4);
    // 印章式图标
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 1.95, w: 0.78, h: 0.78, fill: { color: it[1] },
      line: { color: it[1], width: 0 }, rectRadius: 0.12,
    });
    s.addText(it[0].charAt(0), {
      x, y: 1.95, w: 0.78, h: 0.78, margin: 0,
      align: "center", valign: "middle", fontSize: 30, bold: true,
      color: WHITE, fontFace: FONT,
    });
    s.addText(it[2], {
      x, y: 2.95, w: cw, h: 0.45, margin: 0,
      fontSize: 19, bold: true, color: INK, fontFace: FONT,
    });
    s.addText(it[3], {
      x, y: 3.5, w: cw, h: 1.35, margin: 0,
      fontSize: 13, color: INK_SOFT, lineSpacingMultiple: 1.5, fontFace: FONT,
    });
    // 大字标签：42pt 行高约 52pt(0.73")，框给 0.9" 留余量，避免被裁切
    s.addText(it[0], {
      x, y: 5.05, w: cw, h: 0.9, margin: 0,
      fontSize: 42, bold: true, color: it[1], fontFace: FONT,
    });
  });
  footer(s, 3);
  s.addNotes("40 秒：三个定位词——本地、智能、免费。本地是数据和题库都在本机；智能是 AI 真正进入学习闭环；免费是全量开源，没有付费墙。");
}

// ============================================================ 4 题库家底
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "题 库 家 底", "精筛过的 23,491 篇题库");

  const stats = [
    ["23,491", "篇", "真题 12,393 · 考点 10,375", "言语 · 判断 · 数量 · 资料 · 综应"],
    ["3", "档难度", "easy / mid / hard 智能打标", "空难度题自动兜底补全"],
    ["100", "% 可离线", "题库预置本机", "无网也能整套刷"],
    ["1,000", "词", "花生高频词表", "言语理解专项弹药"],
    ["1,150", "张卡", "高质量词语辨析卡", "支持搜索与筛选联动"],
    ["只增", "不删", "zip 热更新增量升级", "废弃题仅标记，记录不丢"],
  ];
  const cols = 3, rows = 2;
  const gapX = 0.3, gapY = 0.3;
  const cw = (W - 2 * M - (cols - 1) * gapX) / cols;
  const ch = 1.72;
  stats.forEach((it, i) => {
    const x = M + (i % cols) * (cw + gapX);
    const y = 1.92 + Math.floor(i / cols) * (ch + gapY);
    s.addShape(pres.ShapeType.roundRect, {
      x, y, w: cw, h: ch, fill: { color: WHITE },
      line: { color: "E3D9C6", width: 1 }, rectRadius: 0.08,
    });
    s.addText([
      { text: it[0], options: { fontSize: 34, bold: true, color: CINNABAR } },
      { text: " " + it[1], options: { fontSize: 13, color: INK_SOFT } },
    ], {
      x: x + 0.3, y: y + 0.2, w: cw - 0.6, h: 0.62, margin: 0, fontFace: FONT,
    });
    s.addText(it[2], {
      x: x + 0.3, y: y + 0.85, w: cw - 0.6, h: 0.36, margin: 0,
      fontSize: 13, bold: true, color: INK, fontFace: FONT,
    });
    s.addText(it[3], {
      x: x + 0.3, y: y + 1.22, w: cw - 0.6, h: 0.34, margin: 0,
      fontSize: 11, color: "7B7069", fontFace: FONT,
    });
  });
  footer(s, 4);
  s.addNotes("40 秒：题库两万三千四百九十一篇，其中真题一万二千三百九十三篇，覆盖行测五模块加综应。三档难度智能打标，百分百可离线，还有一千词的高频词表和一千一百五十张辨析卡。热更新只增不删。");
}

// ============================================================ 5 功能全景
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "功 能 全 景", "一处集成，八项能力");

  const feats = [
    ["AI", "错题讲解", "拆解思路、逐项辨析，变式题再练一轮"],
    ["AI", "模拟卷", "按真题结构生成新卷，与真题清晰区分"],
    ["卷", "真题套卷", "整卷计时，最后 1 分钟预警，到点自动交卷"],
    ["算", "速算练习", "资料分析提速专训，同类会员专属此处免费"],
    ["灭", "错题歼灭", "自动归档重练，答对即歼灭，正反馈即时"],
    ["称", "成就称号", "七级称号进阶，连对即有动效"],
    ["报", "学习报告", "每日战报结构化导出，可保存可分享"],
    ["卡", "辨析卡库", "高频成语实词卡，即输即搜"],
  ];
  const cols = 4;
  const gapX = 0.24, gapY = 0.28;
  const cw = (W - 2 * M - (cols - 1) * gapX) / cols;
  const ch = 2.05;
  feats.forEach((f, i) => {
    const x = M + (i % cols) * (cw + gapX);
    const y = 1.92 + Math.floor(i / cols) * (ch + gapY);
    s.addShape(pres.ShapeType.roundRect, {
      x, y, w: cw, h: ch, fill: { color: i % 2 ? WHITE : PAPER_DEEP },
      line: { color: "E3D9C6", width: 1 }, rectRadius: 0.08,
    });
    s.addShape(pres.ShapeType.roundRect, {
      x: x + 0.24, y: y + 0.24, w: 0.52, h: 0.52, fill: { color: CINNABAR },
      line: { color: CINNABAR, width: 0 }, rectRadius: 0.1,
    });
    s.addText(f[0], {
      x: x + 0.24, y: y + 0.24, w: 0.52, h: 0.52, margin: 0,
      align: "center", valign: "middle", fontSize: f[0].length > 1 ? 12 : 17,
      bold: true, color: WHITE, fontFace: FONT,
    });
    s.addText(f[1], {
      x: x + 0.24, y: y + 0.88, w: cw - 0.48, h: 0.34, margin: 0,
      fontSize: 15, bold: true, color: INK, fontFace: FONT,
    });
    s.addText(f[2], {
      x: x + 0.24, y: y + 1.24, w: cw - 0.48, h: 0.66, margin: 0,
      fontSize: 10.5, color: INK_SOFT, lineSpacingMultiple: 1.3, fontFace: FONT,
    });
  });
  footer(s, 5);
  s.addNotes("50 秒：八项能力。AI 错题讲解和 AI 模拟卷是两块 AI 能力；真题套卷整卷计时；速算练习在同类产品是会员专属；后面是错题歼灭、成就称号、学习报告、辨析卡库。");
}

// ============================================================ 6 持续迭代
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "持 续 迭 代", "把细节补齐");

  const items = [
    ["断点续做", "中途退出自动存草稿，回来接着做，题号与已答态完整还原。"],
    ["提醒与倒计时", "每日定时提醒 + 考前 7/3/1 天；首页倒计时按天数分档配色。"],
    ["每日目标环", "做题数与时长双目标取最小值，连续达标天数一目了然。"],
    ["用时分析", "区分「不会做」与「会做但超时」，后者才是提速空间所在。"],
    ["内置速查手册", "行测 5 模块 58 考点、综应 6 板块 159 考点，可搜可跳转。"],
    ["移动端专项", "单手翻题底栏 + 左右滑动；夜间三态 + 字号四档。"],
    ["多设备加密同步", "WebDAV + 信封加密，口令走 DPAPI，服务端只见密文。"],
    ["数据自主", "错题导出可打印页、分级清空需二次确认、备份走一致性快照。"],
  ];
  const cols = 2;
  const gapX = 0.4, gapY = 0.22;
  const cw = (W - 2 * M - gapX) / cols;
  const ch = 1.12;
  items.forEach((it, i) => {
    const x = M + (i % cols) * (cw + gapX);
    const y = 1.88 + Math.floor(i / cols) * (ch + gapY);
    s.addText(it[0], {
      x, y, w: cw, h: 0.32, margin: 0,
      fontSize: 14, bold: true, color: INK, fontFace: FONT,
    });
    s.addText(it[1], {
      x, y: y + 0.36, w: cw, h: 0.68, margin: 0,
      fontSize: 11.5, color: INK_SOFT, lineSpacingMultiple: 1.35, fontFace: FONT,
    });
  });
  footer(s, 6);
  s.addNotes("45 秒：这是持续补齐的细节。断点续做、提醒和倒计时、每日目标环、用时分析区分不会做和超时、内置速查手册、移动端专项适配，还有多设备加密同步和数据自主可控。");
}

// ============================================================ 7 AI 讲解深入
{
  const s = pres.addSlide();
  s.background = { color: INK };
  seal(s, M, 0.52, 0.52, "岸", { fontSize: 15, invert: true });
  s.addText("王 牌 功 能 · 深 入", {
    x: M + 0.72, y: 0.56, w: 6, h: 0.28, margin: 0,
    fontSize: 11, color: "C8BDAE", bold: true, charSpacing: 2, fontFace: FONT,
  });
  s.addText("不止告诉你选 C", {
    x: M + 0.72, y: 0.84, w: 9, h: 0.62, margin: 0,
    fontSize: 34, bold: true, color: PAPER, fontFace: FONT,
  });
  s.addText("普通题库只告诉你「选 C」。上岸题库告诉你：为什么选 C、B 错在哪、换个数字再考你一遍。", {
    x: M, y: 1.82, w: W - 2 * M, h: 0.66, margin: 0,
    fontSize: 15, color: "C8BDAE", lineSpacingMultiple: 1.5, fontFace: FONT,
  });

  const steps = [
    ["1", "错题自动进入", "AI 讲解队列"],
    ["2", "解题路径", "选项逐项辨析"],
    ["3", "同型变式题", "答案自算校验"],
  ];
  const cw = (W - 2 * M - 2 * 0.3) / 3;
  steps.forEach((st, i) => {
    const x = M + i * (cw + 0.3);
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 2.92, w: cw, h: 1.85, fill: { color: "423A33" },
      line: { color: "5A4F46", width: 1 }, rectRadius: 0.08,
    });
    s.addText(st[0], {
      x: x + 0.32, y: 3.12, w: 1, h: 0.5, margin: 0,
      fontSize: 30, bold: true, color: CINNABAR, fontFace: FONT,
    });
    s.addText(st[1], {
      x: x + 0.32, y: 3.68, w: cw - 0.64, h: 0.36, margin: 0,
      fontSize: 15, bold: true, color: PAPER, fontFace: FONT,
    });
    s.addText(st[2], {
      x: x + 0.32, y: 4.08, w: cw - 0.64, h: 0.5, margin: 0,
      fontSize: 12, color: "C8BDAE", fontFace: FONT,
    });
  });

  s.addText("✗ 选项 B 错题归档   →   AI 拆解 · 辨析   →   ✓ 变式题再练验证", {
    x: M, y: 5.32, w: W - 2 * M, h: 0.5, margin: 0,
    align: "center", fontSize: 14, color: PAPER, fontFace: FONT,
  });
  footer(s, 7, true);
  s.addNotes("50 秒：这是王牌。错题自动进队列，AI 给解题路径并逐项辨析每个选项，然后生成同型变式题，答案自己算还要校验，直到真正掌握。");
}

// ============================================================ 8 学习闭环
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "学 习 方 法 论", "把错题变成分数");

  const steps = [
    ["1", "精准刷题", "按模块、按难度覆盖行测与综应"],
    ["2", "自动归集", "错题进错题本，无需手动整理"],
    ["3", "AI 拆解", "拆解思路、逐项辨析讲透"],
    ["4", "变式再练", "同型题再练，答案自算校验"],
    ["5", "数据复盘", "看清强弱项，规划明天练什么"],
  ];
  const n = steps.length;
  const gap = 0.26;
  const cw = (W - 2 * M - (n - 1) * gap) / n;
  steps.forEach((st, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 2.0, w: cw, h: 2.5, fill: { color: WHITE },
      line: { color: "E3D9C6", width: 1 }, rectRadius: 0.08,
    });
    s.addShape(pres.ShapeType.ellipse, {
      x: x + 0.28, y: 2.24, w: 0.62, h: 0.62, fill: { color: CINNABAR },
      line: { color: CINNABAR, width: 0 },
    });
    s.addText(st[0], {
      x: x + 0.28, y: 2.24, w: 0.62, h: 0.62, margin: 0,
      align: "center", valign: "middle", fontSize: 20, bold: true,
      color: WHITE, fontFace: FONT,
    });
    s.addText(st[1], {
      x: x + 0.28, y: 3.02, w: cw - 0.56, h: 0.36, margin: 0,
      fontSize: 15, bold: true, color: INK, fontFace: FONT,
    });
    s.addText(st[2], {
      x: x + 0.28, y: 3.42, w: cw - 0.56, h: 0.92, margin: 0,
      fontSize: 11, color: INK_SOFT, lineSpacingMultiple: 1.35, fontFace: FONT,
    });
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 5.02, w: W - 2 * M, h: 0.82, fill: { color: PAPER_DEEP },
    line: { color: PAPER_DEEP, width: 0 }, rectRadius: 0.08,
  });
  s.addText("每天走一遍闭环，进步看得见。", {
    x: M, y: 5.02, w: W - 2 * M, h: 0.82, margin: 0,
    align: "center", valign: "middle", fontSize: 19, bold: true,
    color: INK, fontFace: FONT,
  });
  footer(s, 8);
  s.addNotes("40 秒：五步闭环——精准刷题、错题自动归集、AI 拆解、变式再练、数据复盘。每天走一遍，进步看得见。");
}

// ============================================================ 9 横向对比
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "横 向 对 比", "正面对照");

  const rows = [
    ["维度", "主流题库 App", "上岸题库"],
    ["AI 错题讲解", "会员专属付费功能", "全量免费开放"],
    ["离线刷题", "核心功能依赖联网", "题库预置，完全离线"],
    ["个人数据", "存储于平台云端", "全本机 SQLite，自主可控"],
    ["速算 / 专项工具", "部分需开会员", "内置免费速算练习"],
    ["广告与推销", "开屏广告、课程推送", "零广告，纯净刷题"],
    ["价格", "会员订阅制", "永久免费 · 代码开源"],
  ];
  const border = { type: "solid", color: "E3D9C6", pt: 1 };
  const tableRows = rows.map((r, ri) =>
    r.map((cell, ci) => ({
      text: cell,
      options: {
        fontSize: ri === 0 ? 13 : 12.5,
        bold: ri === 0 || ci === 2,
        color: ri === 0 ? PAPER : ci === 2 ? CINNABAR : INK_SOFT,
        fill: { color: ri === 0 ? INK : ci === 2 ? "FBF6EC" : WHITE },
        align: ci === 0 ? "left" : "center",
        valign: "middle",
        margin: [0.06, 0.14, 0.06, 0.14],
        fontFace: FONT,
        border: [border, border, border, border],
      },
    })),
  );
  s.addTable(tableRows, {
    x: M + 0.3, y: 1.95, w: W - 2 * M - 0.6,
    colW: [3.3, 4.1, 4.1],
    rowH: 0.52,
    border,
  });
  footer(s, 9);
  s.addNotes("40 秒：横向对照六个维度。AI 讲解、离线、数据归属、专项工具、广告、价格。上岸题库在这六项上是全量开放。");
}

// ============================================================ 10 如何使用
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "如 何 使 用", "三种方式，即刻上手");

  const opts = [
    ["全平台", INDIGO, "电脑启动本地服务，手机 / 平板浏览器直接访问。跨设备同题库，零安装门槛。"],
    ["独立运行", CINNABAR, "内置 Python 后端 + SQLite + 全量题库，安装即用，不依赖电脑、不依赖网络。"],
  ];
  const cw = (W - 2 * M - 0.4) / 2;
  opts.forEach((o, i) => {
    const x = M + i * (cw + 0.4);
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 1.92, w: cw, h: 2.52, fill: { color: WHITE },
      line: { color: "E3D9C6", width: 1 }, rectRadius: 0.08,
    });
    s.addShape(pres.ShapeType.roundRect, {
      x: x + 0.36, y: 2.2, w: 1.5, h: 0.44, fill: { color: o[1] },
      line: { color: o[1], width: 0 }, rectRadius: 0.08,
    });
    s.addText(o[0], {
      x: x + 0.36, y: 2.2, w: 1.5, h: 0.44, margin: 0,
      align: "center", valign: "middle", fontSize: 12.5, bold: true,
      color: WHITE, fontFace: FONT,
    });
    s.addText(o[2], {
      x: x + 0.36, y: 2.84, w: cw - 0.72, h: 1.4, margin: 0,
      fontSize: 13, color: INK_SOFT, lineSpacingMultiple: 1.5, fontFace: FONT,
    });
  });

  // 桌面版横幅
  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 4.62, w: W - 2 * M, h: 0.64, fill: { color: "F3E7DD" },
    line: { color: CINNABAR, width: 0.75 }, rectRadius: 0.08,
  });
  s.addShape(pres.ShapeType.roundRect, {
    x: M + 0.18, y: 4.74, w: 1.02, h: 0.4, fill: { color: CINNABAR },
    line: { color: CINNABAR, width: 0 }, rectRadius: 0.2,
  });
  s.addText("桌面版", {
    x: M + 0.18, y: 4.74, w: 1.02, h: 0.4, margin: 0,
    align: "center", valign: "middle", fontSize: 11, bold: true,
    color: WHITE, fontFace: FONT,
  });
  s.addText([
    { text: "Windows 单文件 exe", options: { bold: true, color: INK } },
    { text: "  ·  89.5 MB，双击即用，内置 Python 运行时与全量题库，免装环境、无需浏览器，冷启动约 4 秒。", options: { color: INK_SOFT } },
  ], {
    x: M + 1.38, y: 4.66, w: W - 2 * M - 1.52, h: 0.56, margin: 0,
    valign: "middle", fontSize: 12.5, fontFace: FONT,
  });

  s.addText("电脑端 http://127.0.0.1:8765      手机端 http://<电脑IP>:8765/m/", {
    x: M, y: 5.52, w: W - 2 * M, h: 0.4, margin: 0,
    align: "center", fontSize: 13, color: "7B7069", fontFace: FONT,
  });
  footer(s, 10);
  s.addNotes("45 秒：三种方式。桌面版是 Windows 单文件 exe，双击就出原生窗口，不用装 Python 也不用开浏览器；网页版是电脑起服务、手机浏览器访问；独立运行是安卓包内置后端和题库，不依赖电脑也不依赖网络。");
}

// ============================================================ 11 工程质量
{
  const s = pres.addSlide();
  s.background = { color: PAPER };
  header(s, "工 程 质 量", "用工程师的方式打磨");

  const big = [
    ["100%", "回归测试通过率", "856 条单元 + 79 项端到端"],
    ["6.1万", "手写代码行数", "含数据共 6.9 万行 · Python 56%"],
  ];
  big.forEach((b, i) => {
    const x = M + i * 3.55;
    s.addText(b[0], {
      x, y: 1.9, w: 3.3, h: 0.85, margin: 0,
      fontSize: 48, bold: true, color: CINNABAR, fontFace: FONT,
    });
    s.addText(b[1], {
      x, y: 2.8, w: 3.3, h: 0.3, margin: 0,
      fontSize: 13, bold: true, color: INK, fontFace: FONT,
    });
    s.addText(b[2], {
      x, y: 3.12, w: 3.3, h: 0.3, margin: 0,
      fontSize: 10.5, color: "7B7069", fontFace: FONT,
    });
  });

  // 语言构成：原生条形图
  s.addChart(
    pres.ChartType.bar,
    [{
      name: "占比",
      labels: ["Python 后端", "JS 前端", "CSS 样式", "安卓原生"],
      values: [56, 35, 5, 2],
    }],
    {
      x: 7.5, y: 1.8, w: 5.2, h: 2.0,
      showTitle: true, title: "代码构成（%）", titleFontSize: 11, titleColor: "5C534A",
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 9,
      chartColors: [CINNABAR],
      barDir: "bar",
      catAxisLabelColor: "5C534A", catAxisLabelFontSize: 9,
      valAxisLabelColor: "7B7069", valAxisLabelFontSize: 9,
      valGridLine: { color: "E9E0CE", size: 0.5 },
      catGridLine: { style: "none" },
      showLegend: false,
      border: { pt: 0, color: "FFFFFF" },
    },
  );

  const checks = [
    "启动自检：核心接口与配置自动体检，异常红色标注",
    "版本化迁移：schema 版本管理，旧库升级不丢数据",
    "热更新：题库 zip 增量升级，只增不删、记录不丢",
    "本地可备份：数据全在本机，账号与学习记录一键恢复",
    "全量开源：GitHub 接受公开检验，隐私零上传",
  ];
  checks.forEach((c, i) => {
    s.addText("✓", {
      x: M, y: 4.02 + i * 0.5, w: 0.28, h: 0.32, margin: 0,
      fontSize: 13, bold: true, color: CINNABAR, fontFace: FONT,
    });
    s.addText(c, {
      x: M + 0.34, y: 4.02 + i * 0.5, w: W - 2 * M - 0.34, h: 0.32, margin: 0,
      fontSize: 12.5, color: INK_SOFT, fontFace: FONT,
    });
  });
  footer(s, 11);
  s.addNotes("45 秒：工程质量。回归测试百分百通过，856 条单元测试加 79 项端到端，15 个静态校验器零失败。还有启动自检、版本化迁移、热更新、本地备份、全量开源。");
}

// ============================================================ 12 结尾
{
  const s = pres.addSlide();
  s.background = { color: INK };

  seal(s, M, 1.35, 0.66, "岸", { fontSize: 20, invert: true });

  s.addText("开始使用", {
    x: M, y: 2.35, w: 9, h: 1.05, margin: 0,
    fontSize: 58, bold: true, color: PAPER, fontFace: FONT,
  });
  s.addText("上岸题库 · 你的口袋私教", {
    x: M, y: 3.62, w: 9, h: 0.46, margin: 0,
    fontSize: 21, color: "C8BDAE", fontFace: FONT,
  });
  s.addText("免费 · 开源 · 离线 · 为 C 类联考而生", {
    x: M, y: 4.18, w: 9, h: 0.4, margin: 0,
    fontSize: 15, color: CINNABAR, bold: true, charSpacing: 1.5, fontFace: FONT,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 5.12, w: 7.1, h: 0.78, fill: { color: "423A33" },
    line: { color: "5A4F46", width: 1 }, rectRadius: 0.1,
  });
  s.addText("GITHUB · github.com/Ryden789/GOSHORE", {
    x: M + 0.36, y: 5.12, w: 6.5, h: 0.78, margin: 0,
    valign: "middle", fontSize: 14, color: PAPER, fontFace: "Consolas",
  });
  footer(s, 12, true);
  s.addNotes("40 秒：结尾。免费、开源、离线、为 C 类联考而生。代码在 GitHub，欢迎验收和提意见。");
}

pres.writeFile({ fileName: "D:/GOSHORE/output/上岸题库-软件介绍.pptx" })
  .then((f) => console.log("written:", f));
