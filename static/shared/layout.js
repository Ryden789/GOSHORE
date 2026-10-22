/* 功能排版：双端共用分类，业务路由及判分逻辑仍由各端负责。 */
(function () {
  "use strict";
  const groups = [
  {
    "key": "today",
    "title": "今日安排",
    "items": [
      {
        "route": "home",
        "title": "今日书房",
        "desc": "继续学习与今日概况"
      },
      {
        "route": "plan",
        "title": "学习计划",
        "desc": "能力雷达与弱项加权路径"
      }
    ]
  },
  {
    "key": "xingce",
    "title": "行测 / 职测",
    "items": [
      {
        "route": "paper",
        "title": "自由组卷",
        "desc": "智能、随机、顺序与限时练习"
      },
      {
        "route": "logic",
        "title": "判断专项",
        "desc": "图形、定义、类比与逻辑"
      },
      {
        "route": "formula",
        "title": "列式专项",
        "desc": "资料分析列式训练"
      },
      {
        "route": "wordfill",
        "title": "词语填空",
        "desc": "逻辑填空与高频词运用"
      },
      {
        "route": "speed",
        "title": "速算",
        "desc": "限时挑战与成绩趋势"
      },
      {
        "route": "cube",
        "title": "空间折叠",
        "desc": "展开图识别与三维交互"
      }
    ]
  },
  {
    "key": "essay",
    "title": "申论 / 综应",
    "items": [
      {
        "route": "essay",
        "title": "申论综应",
        "desc": "材料练习与题型方法"
      },
      {
        "route": "argument",
        "title": "论证评价",
        "desc": "材料标注与辨析快练"
      },
      {
        "route": "wenxian",
        "title": "科技文献",
        "desc": "长文阅读与材料小题"
      },
      {
        "route": "grade",
        "title": "AI 批改",
        "desc": "评分、命中要点、改写与历史"
      }
    ]
  },
  {
    "key": "interview",
    "title": "面试模拟",
    "items": [
      {
        "route": "interview",
        "title": "面试模拟",
        "desc": "结构化面试与 AI 点评"
      }
    ]
  },
  {
    "key": "share",
    "title": "分享 PK",
    "items": [
      {
        "route": "share",
        "title": "分享 PK",
        "desc": "生成、打开题单与好友对练"
      }
    ]
  },
  {
    "key": "review",
    "title": "复习巩固",
    "items": [
      {
        "route": "review",
        "title": "今日复习",
        "desc": "到期题目与复习驾驶舱"
      },
      {
        "route": "wrong",
        "title": "错题本",
        "desc": "错因、变式歼灭与打印导出"
      },
      {
        "route": "mastery",
        "title": "掌握度",
        "desc": "考点掌握情况与薄弱点"
      },
      {
        "route": "cards",
        "title": "辨析卡",
        "desc": "记忆、默写、测验与不会词本"
      },
      {
        "route": "marks",
        "title": "收藏",
        "desc": "重点题目集中回看"
      },
      {
        "route": "notes",
        "title": "笔记",
        "desc": "题目心得与自由笔记"
      }
    ]
  },
  {
    "key": "knowledge",
    "title": "知识资料",
    "items": [
      {
        "route": "xc-notes",
        "title": "行测速查",
        "desc": "公式、规律与速算技巧"
      },
      {
        "route": "zy-notes",
        "title": "综应考点",
        "desc": "C 类综应知识体系"
      },
      {
        "route": "shizheng",
        "title": "时政",
        "desc": "热点学习与时政自测"
      }
    ]
  },
  {
    "key": "reports",
    "title": "学习报告",
    "items": [
      {
        "route": "report",
        "title": "周报",
        "desc": "本周诊断、对比与导出"
      },
      {
        "route": "time",
        "title": "用时分析",
        "desc": "各模块节奏与会做但超时"
      },
      {
        "route": "history",
        "title": "做题记录",
        "desc": "逐题作答历史"
      }
    ]
  },
  {
    "key": "ai",
    "title": "AI 辅助",
    "items": [
      {
        "route": "ai-ask",
        "title": "AI 答疑",
        "desc": "文字、图片提问与历史会话"
      }
    ]
  },
  {
    "key": "manage",
    "title": "题库管理",
    "items": [
      {
        "route": "search",
        "title": "题库检索",
        "desc": "全文搜索与条件筛选"
      },
      {
        "route": "doubts",
        "title": "疑点",
        "desc": "存疑题目复核与处理"
      },
      {
        "route": "import",
        "title": "导入",
        "desc": "文件抽题、预览与核对"
      }
    ]
  },
  {
    "key": "settings",
    "title": "设置与数据",
    "items": [
      {
        "route": "settings",
        "title": "设置",
        "desc": "外观、提醒、AI、同步与备份"
      }
    ]
  }
];
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function items(key) { return groups.find(g => g.key === key)?.items || []; }
  function cards(key, mobile = false, exclude = []) {
    return `<div class="study-feature-grid">${items(key).filter(it => !exclude.includes(it.route)).map(it => {
      // 空间折叠原先仅桌面提供，手机入口明确跳转桌面功能，不伪装原生移植。
      const href = mobile && it.route === "cube" ? "/#/cube" : "#/" + it.route;
      return `<a class="study-feature" href="${href}"${mobile && it.route === "cube" ? ' target="_blank" rel="noopener"' : ""}><span class="study-feature-icon" aria-hidden="true">${esc(it.title.slice(0,1))}</span><b>${esc(it.title)}</b><small>${esc(it.desc)}${mobile && it.route === "cube" ? " · 打开桌面页" : ""}</small></a>`;
    }).join("")}</div>`;
  }
  function header(title, desc) { return `<header class="page-head study-page-head"><h1 class="page-title">${esc(title)}</h1><p class="page-desc">${esc(desc)}</p></header>`; }
  function tabs(active, mobile = false) {
    const root = mobile ? "training" : "practice";
    return `<nav class="study-tabs" aria-label="训练科目">${[["xingce","行测 / 职测"],["essay","申论 / 综应"],["interview","面试模拟"],["share","分享 PK"]].map(([key,title]) => `<a href="#/${root}/${key}"${key===active ? ' class="active" aria-current="page"' : ""}>${title}</a>`).join("")}</nav>`;
  }
  function sectionFor(route) {
    if (["home","plan"].includes(route)) return "home";
    if (["practice","paper","exam","logic","formula","wordfill","speed","cube","essay","argument","argument-quiz","wenxian","grade","interview","share"].includes(route)) return "practice";
    if (["review-center","review","wrong","mastery","cards","marks","notes"].includes(route)) return "review-center";
    if (["knowledge","xc-notes","zy-notes","shizheng"].includes(route)) return "knowledge";
    if (["reports","overview","summary","report","time","history"].includes(route)) return "reports";
    if (["manage","search","doubts","import","mydocs","doc"].includes(route)) return "manage";
    if (["ai-ask","guide"].includes(route)) return "ai-ask";
    return route;
  }
  function mobileTabFor(route) {
    if (["practice","training","paper","logic","formula","wordfill","speed","essay","argument","argument-quiz","wenxian","grade","interview","share","run"].includes(route)) return "training";
    const section = sectionFor(route);
    if (["home","ai-ask"].includes(section)) return "home";
    if (["review-center","knowledge"].includes(section)) return section;
    return "me";
  }
  globalThis.StudyLayout = { groups, items, cards, header, tabs, sectionFor, mobileTabFor };
})();
