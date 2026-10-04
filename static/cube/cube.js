/* 空间折叠训练（折纸盒）——GOSHORE 模块
 * 几何引擎改编自开源项目 cube-net-lab（MIT），中文重写并增加"三面共点红点法"。
 * 依赖全局 THREE（r147 UMD，/static/vendor/three.min.js）。
 */
(() => {
  const OPP = { F: "B", B: "F", U: "D", D: "U", L: "R", R: "L" };
  // 从面外看，四周相邻面顺时针：北 东 南 西
  const CYCLE = {
    F: ["U", "R", "D", "L"],
    B: ["U", "L", "D", "R"],
    U: ["B", "R", "F", "L"],
    D: ["F", "R", "B", "L"],
    L: ["U", "F", "D", "B"],
    R: ["U", "B", "D", "F"],
  };
  const NAMES = { F: "前", B: "后", U: "上", D: "下", L: "左", R: "右" };
  const COLORS = {
    F: "#f4d35e", B: "#ee964b", U: "#d8e2dc",
    D: "#c9ada7", L: "#7eb8da", R: "#9b5de5",
  };
  const DIR = [{ x: 0, y: 1 }, { x: 1, y: 0 }, { x: 0, y: -1 }, { x: -1, y: 0 }];
  const FACE_LIST = ["F", "B", "U", "D", "L", "R"];

  const state = {
    mode: "lab", fold: 1, selected: "F", stickers: {}, layout: null, tree: null,
    showOnlyOpp: false, stats: { ok: 0, streak: 0 }, quiz: null, picked: null, drill: null,
    vertexMode: false, vertexPick: [], vertexDots: [],
  };

  /* ---------------- 枚举全部合法展开图（11 种） ---------------- */
  function sideOfNeighbor(face, neighbor) { return CYCLE[face].indexOf(neighbor); }
  function emptyKids() { return { F: [], B: [], U: [], D: [], L: [], R: [] }; }
  function cloneKids(k) { const o = emptyKids(); for (const f of FACE_LIST) o[f] = [...(k[f] || [])]; return o; }

  function layoutFromTree(root, children) {
    const pos = { [root]: { x: 0, y: 0, rot: 0 } };
    const occ = { "0,0": root };
    const q = [root];
    while (q.length) {
      const a = q.shift();
      for (const b of children[a] || []) {
        const sA = sideOfNeighbor(a, b);
        if (sA < 0) return null;
        const netDir = (sA + pos[a].rot) % 4;
        const nx = pos[a].x + DIR[netDir].x, ny = pos[a].y + DIR[netDir].y;
        const key = `${nx},${ny}`;
        if (occ[key]) return null;
        const sB = sideOfNeighbor(b, a);
        const back = (netDir + 2) % 4;
        pos[b] = { x: nx, y: ny, rot: (back - sB + 4) % 4 };
        occ[key] = b;
        q.push(b);
      }
    }
    return Object.keys(pos).length === 6 ? pos : null;
  }

  function crossTree() {
    const children = emptyKids();
    children.F = ["U", "D", "L", "R"];
    children.R = ["B"];
    return { children, layout: layoutFromTree("F", children) };
  }

  function shapeKey(layout) {
    const cells = Object.values(layout).map(p => [p.x, p.y]);
    const keys = [];
    for (const flip of [false, true]) {
      for (let r = 0; r < 4; r++) {
        const pts = cells.map(([x, y]) => {
          let xx = flip ? -x : x, yy = y;
          if (r === 1) [xx, yy] = [yy, -xx];
          else if (r === 2) [xx, yy] = [-xx, -yy];
          else if (r === 3) [xx, yy] = [-yy, xx];
          return [xx, yy];
        });
        const mx = Math.min(...pts.map(p => p[0])), my = Math.min(...pts.map(p => p[1]));
        const norm = pts.map(([x, y]) => [x - mx, y - my]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
        keys.push(norm.map(p => p.join(",")).join(";"));
      }
    }
    return keys.sort()[0];
  }

  function netIllegal(layout) {
    const cells = Object.values(layout);
    const set = new Set(cells.map(p => `${p.x},${p.y}`));
    for (const p of cells) {
      if (set.has(`${p.x + 1},${p.y}`) && set.has(`${p.x},${p.y + 1}`) && set.has(`${p.x + 1},${p.y + 1}`)) return true;
      for (const [dx, dy] of [[1, 0], [0, 1]]) {
        let n = 1, x = p.x + dx, y = p.y + dy;
        while (set.has(`${x},${y}`)) { n += 1; x += dx; y += dy; }
        if (n >= 5) return true;
      }
    }
    return false;
  }

  function classifyGroup(layout) {
    let pts = Object.values(layout).map(p => [p.x, p.y]);
    const sigs = [];
    let maxLine = 0;
    for (let r = 0; r < 4; r++) {
      const rows = {}, cols = {};
      for (const [x, y] of pts) { rows[y] = (rows[y] || 0) + 1; cols[x] = (cols[x] || 0) + 1; }
      const rv = Object.values(rows), cv = Object.values(cols);
      sigs.push([...rv].sort((a, b) => a - b).join(","));
      sigs.push([...cv].sort((a, b) => a - b).join(","));
      maxLine = Math.max(maxLine, ...rv, ...cv);
      pts = pts.map(([x, y]) => [-y, x]);  // 旋转90°
    }
    if (maxLine === 4) return "一四一型";       // 含四连方的必为一四一（含两个单格同侧变体）
    if (sigs.includes("1,2,3")) return "一三二型";
    if (sigs.includes("2,2,2")) return "二二二型";
    return "三三型";
  }

  function enumerateNets() {
    const found = [], seen = new Set(), kids = emptyKids(), used = new Set(["F"]);
    function rec() {
      if (used.size === 6) {
        const lay = layoutFromTree("F", kids);
        if (!lay || netIllegal(lay)) return;
        const key = shapeKey(lay);
        if (seen.has(key)) return;
        seen.add(key);
        found.push({ children: cloneKids(kids), layout: lay, key, group: classifyGroup(lay) });
        return;
      }
      for (const a of [...used]) {
        for (const b of CYCLE[a]) {
          if (used.has(b)) continue;
          kids[a].push(b); used.add(b);
          rec();
          used.delete(b); kids[a].pop();
        }
      }
    }
    rec();
    const order = { "一四一型": 0, "一三二型": 1, "二二二型": 2, "三三型": 3 };
    found.sort((a, b) => order[a.group] - order[b.group] || a.key.localeCompare(b.key));
    const counter = {};
    const circles = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪"];
    found.forEach(n => { counter[n.group] = (counter[n.group] || 0) + 1; n.name = `${n.group} ${circles[counter[n.group] - 1] || counter[n.group]}`; });
    return found;
  }
  const ALL_NETS = enumerateNets();

  function applyNet(kind) {
    const t = ALL_NETS.find(n => n.name === kind) || ALL_NETS[0];
    state.tree = t.children; state.layout = t.layout; state.netName = t.name;
  }

  /* ---------------- 拍照录题：AI 网格 → 11 种展开图匹配 ----------------
   * AI 输出屏幕网格坐标（c 向右、r 向下）。11 种合法展开图在镜像下封闭，
   * 故只做 0/90/180/270 旋转匹配（不做镜像，避免折出手性相反的立方体）。
   * 匹配后不直接使用库内 net 的朝向，而是以【原图方位】重建 layout：
   * 格坐标取 AI 坐标，面姿态 rot 补偿旋转 k，保证还原的平面图与原图同向。
   */
  const PHOTO_SYM = { arrow: "arrow", triangle: "tri", cross: "plus", circle: "dot", letter: "letter" };
  const PHOTO_DIR = { up: 0, right: 1, down: 2, left: 3 };
  // 斜线朝向由 AI 的 dir 字段区分：tlbr=＼ → slash，trbl=／ → slash2
  function photoSymOf(cl) {
    if (cl.kind === "slash") return cl.dir === "trbl" ? "slash2" : "slash";
    return PHOTO_SYM[cl.kind] || null;
  }

  function normalizePts(pts) {
    const mx = Math.min(...pts.map(p => p.x)), my = Math.min(...pts.map(p => p.y));
    pts.forEach(p => { p.x -= mx; p.y -= my; });
    return pts;
  }
  function ptsKey(pts) { return pts.map(p => `${p.x},${p.y}`).sort().join(";"); }

  function matchRecognizedNet(cells) {
    if (!cells || cells.length !== 6) return null;
    const minc = Math.min(...cells.map(cl => cl.c)), minr = Math.min(...cells.map(cl => cl.r));
    const ai = cells.map(cl => ({ x: cl.c - minc, y: cl.r - minr, cl }));
    for (const net of ALL_NETS) {
      const np = Object.entries(net.layout).map(([f, p]) => ({ x: p.x, y: -p.y, f, prot: p.rot || 0 }));
      normalizePts(np);
      const key = ptsKey(np);
      for (let k = 0; k < 4; k++) {
        const tp = ai.map(p => {
          let x = p.x, y = p.y;
          for (let i = 0; i < k; i++) { const tx = -y; y = x; x = tx; }  // 屏幕顺时针90°:(x,y)→(-y,x)
          return { x, y, cl: p.cl };
        });
        normalizePts(tp);
        if (ptsKey(tp) !== key) continue;
        const aiByKey = new Map(tp.map(p => [`${p.x},${p.y}`, p.cl]));
        const map = np.map(p => ({ f: p.f, prot: p.prot, cl: aiByKey.get(`${p.x},${p.y}`) }));
        // 以原图方位重建 layout：数学坐标 x=c、y=-r；面姿态补偿旋转 k
        const layout = {};
        for (const { f, prot, cl } of map) {
          layout[f] = { x: cl.c - minc, y: -(cl.r - minr), rot: (prot - k + 4) % 4 };
        }
        return { net, k, map, layout };
      }
    }
    return null;
  }

  // 2D 平面预览里图案屏幕朝向 = (sticker.rot + 面布局rot) mod 4；新 layout 与原图同向，直接反推
  function stickersFromRecognized(matched) {
    const stickers = freshStickers();
    for (const f of FACE_LIST) stickers[f].sym = null;
    for (const { f, cl } of matched.map) {
      if (!cl) continue;
      const sym = photoSymOf(cl);
      if (!sym) continue;
      stickers[f].sym = sym;
      if (sym === "letter") stickers[f].mark = (cl.label || "?").slice(0, 1);
      if (cl.dir in PHOTO_DIR) {
        const rot = (PHOTO_DIR[cl.dir] - matched.layout[f].rot + 4) % 4;
        stickers[f].rot = rot; stickers[f].edge = rot;
      }
    }
    return stickers;
  }

  function freshStickers() {
    const s = {};
    for (const f of FACE_LIST) s[f] = { id: f, color: COLORS[f], sym: null, rot: 0, edge: 0 };
    s.F.sym = "arrow"; s.F.rot = 0; s.F.edge = 0;
    s.U.sym = "arrow"; s.U.rot = 2; s.U.edge = 2;
    const marks = { F: "A", B: "B", U: "C", D: "D", L: "E", R: "F" };
    const pips = { F: 1, B: 6, U: 2, D: 5, L: 3, R: 4 };
    for (const f of FACE_LIST) { s[f].mark = marks[f]; s[f].pips = pips[f]; }
    return s;
  }

  // 原图纹理使用截图方向；抵消布局旋转后，2D 预览与展开的 3D 面保持一致。
  function cropFaceImage(source, bbox) {
    if (!Array.isArray(bbox) || bbox.length !== 4 || bbox.some(v => !Number.isFinite(v) || v < 0 || v > 1) || bbox[0] >= bbox[2] || bbox[1] >= bbox[3]) {
      throw new Error("裁剪范围无效：请填写图片内的左、上、右、下边界");
    }
    const width = source.naturalWidth || source.width, height = source.naturalHeight || source.height;
    const sx = bbox[0] * width, sy = bbox[1] * height;
    const sw = (bbox[2] - bbox[0]) * width, sh = (bbox[3] - bbox[1]) * height;
    if (sw < 2 || sh < 2) throw new Error("裁剪范围太小，请重新框选完整面");
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = Math.min(1024, Math.max(256, Math.ceil(Math.max(sw, sh))));
    canvas.getContext("2d").drawImage(source, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    return { imageCanvas: canvas, imageUrl: canvas.toDataURL("image/png"), bbox: [...bbox] };
  }

  function imageStickersFromRecognized(matched, source) {
    const stickers = freshStickers();
    for (const { f, cl } of matched.map) {
      const rot = (4 - matched.layout[f].rot) % 4;
      Object.assign(stickers[f], cropFaceImage(source, cl.bbox), { sym: "image", rot, edge: rot });
    }
    return stickers;
  }

  function loadPhotoImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("原图读取失败，请重新选择图片"));
      img.src = url;
    });
  }

  /* ---------------- 面贴图（Canvas 纹理） ---------------- */
  function drawPips(ctx, n) {
    const r = 14, o = 41;
    const spots = {
      1: [[0, 0]],
      2: [[-o, -o], [o, o]],
      3: [[-o, -o], [0, 0], [o, o]],
      4: [[-o, -o], [o, -o], [-o, o], [o, o]],
      5: [[-o, -o], [o, -o], [0, 0], [-o, o], [o, o]],
      6: [[-o, -o], [o, -o], [-o, 0], [o, 0], [-o, o], [o, o]],
    };
    for (const [x, y] of spots[n] || spots[1]) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); }
  }

  function drawSymbol(ctx, kind, dir, size, sticker) {
    if (!kind) return;
    ctx.save();
    ctx.translate(size / 2, size / 2);
    ctx.rotate((dir * Math.PI) / 2); // 0=北 1=东 2=南 3=西
    if (kind === "arrow" || kind === "tri" || kind === "wifi") ctx.translate(0, -size * 0.05);
    ctx.strokeStyle = "#111"; ctx.fillStyle = "#111"; ctx.lineCap = "round"; ctx.lineJoin = "round";
    if (kind === "wifi") {
      ctx.beginPath(); ctx.arc(0, 10, 4, 0, Math.PI * 2); ctx.fill();
      ctx.lineWidth = 5;
      for (let i = 1; i <= 3; i++) { ctx.beginPath(); ctx.arc(0, 12, 8 + i * 9, -Math.PI * 0.75, -Math.PI * 0.25); ctx.stroke(); }
    } else if (kind === "arrow") {
      ctx.lineWidth = 6;
      ctx.beginPath(); ctx.moveTo(0, 18); ctx.lineTo(0, -14); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(-14, 2); ctx.lineTo(0, -20); ctx.lineTo(14, 2); ctx.stroke();
    } else if (kind === "tri") {
      ctx.beginPath(); ctx.moveTo(0, -18); ctx.lineTo(16, 14); ctx.lineTo(-16, 14); ctx.closePath(); ctx.fill();
    } else if (kind === "plus") {
      ctx.lineWidth = 8;
      ctx.beginPath(); ctx.moveTo(-18, 0); ctx.lineTo(18, 0); ctx.moveTo(0, -18); ctx.lineTo(0, 18); ctx.stroke();
    } else if (kind === "dot") {
      ctx.beginPath(); ctx.arc(0, 0, 16, 0, Math.PI * 2); ctx.fill();
    } else if (kind === "letter") {
      ctx.font = "bold 92px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText((sticker && sticker.mark) || "A", 0, 4);
    } else if (kind === "dice") {
      drawPips(ctx, (sticker && sticker.pips) || 1);
    } else if (kind === "slash") {
      ctx.lineWidth = 6;
      ctx.beginPath(); ctx.moveTo(-14, -14); ctx.lineTo(14, 14); ctx.stroke(); // ＼
    } else if (kind === "slash2") {
      ctx.lineWidth = 6;
      ctx.beginPath(); ctx.moveTo(14, -14); ctx.lineTo(-14, 14); ctx.stroke(); // ／
    }
    ctx.restore();
  }

  function faceTexture(sticker, exam) {
    const original = sticker.sym === "image" && sticker.imageCanvas;
    const size = original ? original.width : 256;
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const ctx = c.getContext("2d");
    ctx.fillStyle = exam ? "#fbfaf6" : sticker.color;
    ctx.fillRect(0, 0, size, size);
    if (original) {
      ctx.save();
      ctx.translate(size / 2, size / 2);
      ctx.rotate((sticker.rot || 0) * Math.PI / 2);
      ctx.drawImage(original, -size / 2, -size / 2, size, size);
      ctx.restore();
    }
    ctx.strokeStyle = "#2b261f"; ctx.lineWidth = original ? 2 : 10;
    ctx.strokeRect(original ? 1 : 6, original ? 1 : 6, size - (original ? 2 : 12), size - (original ? 2 : 12));
    if (!exam && !original) {
      ctx.fillStyle = "rgba(0,0,0,.45)"; ctx.font = "bold 28px sans-serif"; ctx.textAlign = "left";
      ctx.fillText(NAMES[sticker.id] + "面", 22, 46);
    }
    if (!original) drawSymbol(ctx, sticker.sym, sticker.edge == null ? sticker.rot : sticker.edge, size, sticker);
    const tex = new THREE.CanvasTexture(c);
    tex.encoding = THREE.sRGBEncoding; // r147 写法
    tex.anisotropy = 8;
    return tex;
  }

  /* ---------------- 3D 折叠场景 ---------------- */
  function makeFaceMesh(sticker, exam) {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.MeshStandardMaterial({ map: faceTexture(sticker, exam), roughness: 0.55, metalness: 0.02, side: THREE.DoubleSide })
    );
    m.userData.face = sticker.id;
    return m;
  }

  function buildFoldingCube(stickers, tree, layout, exam) {
    const group = new THREE.Group();
    const hinges = {}, meshes = {}, frames = {};
    const quarterTurn = Math.PI / 2;
    const clamp01 = value => Math.min(1, Math.max(0, Number(value) || 0));

    function rotateNetVector(x, y, quarterTurns) {
      let q = ((quarterTurns % 4) + 4) % 4;
      while (q--) [x, y] = [-y, x];
      return { x, y };
    }

    function attach(child, parent, parentFrame) {
      const p = layout[parent], cc = layout[child];
      if (!p || !cc) return false;
      const dx = cc.x - p.x, dy = cc.y - p.y;
      if (Math.abs(dx) + Math.abs(dy) !== 1) return false;
      const netDir = dx === 1 ? 1 : dx === -1 ? 3 : dy === 1 ? 0 : 2;
      const localDelta = rotateNetVector(dx, dy, p.rot || 0);
      const fold = foldAxis(netDir);
      const worldEdge = fold.axis === "x" ? { x: 1, y: 0 } : { x: 0, y: 1 };
      const localEdge = rotateNetVector(worldEdge.x, worldEdge.y, p.rot || 0);

      const hinge = new THREE.Group();
      hinge.position.set(localDelta.x * 0.5, localDelta.y * 0.5, 0);
      parentFrame.add(hinge);

      const frame = new THREE.Group();
      frame.position.set(localDelta.x * 0.5, localDelta.y * 0.5, 0);
      frame.rotation.z = -(((cc.rot || 0) - (p.rot || 0)) % 4) * quarterTurn;
      hinge.add(frame);
      const mesh = makeFaceMesh(stickers[child], exam);
      frame.add(mesh);

      const axis = new THREE.Vector3(localEdge.x, localEdge.y, 0).normalize();
      hinge.userData.fold = { axis, ang: fold.ang };
      hinges[child] = hinge; meshes[child] = mesh; frames[child] = frame;
      return true;
    }
    function foldAxis(netDir) {
      if (netDir === 0) return { axis: "x", ang: -Math.PI / 2 };
      if (netDir === 2) return { axis: "x", ang: Math.PI / 2 };
      if (netDir === 1) return { axis: "y", ang: Math.PI / 2 };
      return { axis: "y", ang: -Math.PI / 2 };
    }

    const root = new THREE.Group();
    root.rotation.z = -(((layout.F && layout.F.rot) || 0) % 4) * quarterTurn;
    const fMesh = makeFaceMesh(stickers.F, exam);
    root.add(fMesh); group.add(root);
    hinges.F = root; meshes.F = fMesh; frames.F = root;
    root.userData.fold = null;

    const q = ["F"], built = new Set(["F"]);
    while (q.length) {
      const a = q.shift();
      for (const b of tree[a] || []) {
        if (built.has(b)) continue;
        if (attach(b, a, frames[a])) { built.add(b); q.push(b); }
      }
    }

    function setFold(t) {
      t = clamp01(t);
      for (const f of FACE_LIST) {
        const h = hinges[f];
        if (!h || !h.userData.fold) continue;
        h.quaternion.setFromAxisAngle(h.userData.fold.axis, h.userData.fold.ang * t);
      }
    }
    return { group, meshes, setFold };
  }

  function setupView(el, exam) {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(exam ? 0xf7f1e4 : 0xf3ede0);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
    camera.position.set(2.7, 2.15, 3.6);
    camera.lookAt(0, 0.05, -0.35);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    scene.add(new THREE.HemisphereLight(0xffffff, 0x887766, 1.15));
    const dir = new THREE.DirectionalLight(0xffffff, 0.55);
    dir.position.set(2, 4, 3); scene.add(dir);
    const rig = new THREE.Group(); scene.add(rig);

    const pack = { scene, camera, renderer, canvas: el, rig, cube: null, zoom: 1, raf: 0 };
    function frame() {
      if (!pack.cube) return;
      pack.cube.group.position.set(0, 0, 0);
      pack.cube.group.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(pack.cube.group);
      const center = box.getCenter(new THREE.Vector3());
      if (!isFinite(center.x)) return;
      pack.cube.group.position.copy(center).multiplyScalar(-1);
      const size = box.getSize(new THREE.Vector3());
      const fov = (camera.fov * Math.PI) / 180;
      let dist = (Math.max(size.x, size.y, size.z, 1.2) / (2 * Math.tan(fov / 2))) * 1.55 * pack.zoom;
      if ((camera.aspect || 1) < 1) dist /= camera.aspect;
      camera.position.set(dist * 0.72, dist * 0.52, dist * 0.9);
      camera.lookAt(0, 0, 0);
      camera.near = Math.max(0.05, dist / 30); camera.far = dist * 30;
      camera.updateProjectionMatrix();
    }
    function rebuild() {
      if (pack.cube) {
        pack.cube.group.traverse(o => {
          if (o.geometry) o.geometry.dispose();
          const ms = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
          ms.forEach(m => { if (m.map) m.map.dispose(); m.dispose(); });
        });
        pack.rig.remove(pack.cube.group);
      }
      pack.cube = buildFoldingCube(state.stickers, state.tree, state.layout, exam);
      pack.rig.add(pack.cube.group);
      pack.cube.setFold(state.fold);
      frame();
    }
    pack.rebuild = rebuild; pack.frame = frame;
    rebuild();
    function resize() {
      const w = el.clientWidth || 400, h = el.clientHeight || 360;
      renderer.setSize(w, h, true);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix(); frame();
    }
    resize();
    const ro = new ResizeObserver(resize); ro.observe(el);

    let drag = false, moved = 0, lx = 0, ly = 0;
    el.addEventListener("pointerdown", e => { drag = true; moved = 0; lx = e.clientX; ly = e.clientY; el.setPointerCapture(e.pointerId); });
    el.addEventListener("pointerup", e => { drag = false; if (moved < 6) pack.onTap && pack.onTap(e); });
    el.addEventListener("pointermove", e => {
      if (!drag) return;
      const dx = e.clientX - lx, dy = e.clientY - ly;
      moved += Math.abs(dx) + Math.abs(dy); lx = e.clientX; ly = e.clientY;
      rig.rotation.y += dx * 0.01; rig.rotation.x += dy * 0.01;
    });
    el.addEventListener("wheel", e => {
      e.preventDefault();
      pack.zoom = Math.min(2.4, Math.max(0.45, pack.zoom * (e.deltaY > 0 ? 1.08 : 0.92)));
      frame();
    }, { passive: false });

    (function loop() { renderer.render(scene, camera); pack.raf = requestAnimationFrame(loop); })();
    pack.destroy = () => { cancelAnimationFrame(pack.raf); ro.disconnect(); renderer.dispose(); if (renderer.forceContextLoss) renderer.forceContextLoss(); el.replaceChildren(); };
    return pack;
  }

  /* ---------------- 红点法：三面共点 ---------------- */
  function adjacent(a, b) { return CYCLE[a].includes(b); }

  function attachVertexDots(pack, faces) {
    clearVertexDots(pack);
    // 临时折到位，取每个面 4 个角的世界坐标，找三面共有的那个顶点
    const saved = state.fold;
    pack.cube.setFold(1);
    pack.cube.group.updateMatrixWorld(true);
    const corners = {};
    for (const f of faces) {
      const m = pack.cube.meshes[f];
      corners[f] = [];
      for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
        const v = m.localToWorld(new THREE.Vector3(sx * 0.5, sy * 0.5, 0.02));
        corners[f].push({ key: [v.x, v.y, v.z].map(n => n.toFixed(2)).join(","), x: sx, y: sy });
      }
    }
    pack.cube.setFold(saved);
    let common = null;
    for (const c0 of corners[faces[0]]) {
      if (corners[faces[1]].some(c => c.key === c0.key) && corners[faces[2]].some(c => c.key === c0.key)) { common = c0.key; break; }
    }
    if (!common) return false;
    const dotGeo = new THREE.SphereGeometry(0.06, 18, 18);
    for (const f of faces) {
      const c = corners[f].find(x => x.key === common);
      const dot = new THREE.Mesh(dotGeo, new THREE.MeshBasicMaterial({ color: 0xd9261c }));
      dot.position.set(c.x * 0.5, c.y * 0.5, 0.05);
      pack.cube.meshes[f].add(dot);
      state.vertexDots.push(dot);
    }
    return true;
  }
  function clearVertexDots(pack) {
    for (const d of state.vertexDots) { if (d.parent) d.parent.remove(d); }
    state.vertexDots = [];
  }

  function highlight(pack) {
    if (!pack || !pack.cube) return;
    const sel = state.selected, opp = OPP[sel];
    for (const [f, m] of Object.entries(pack.cube.meshes)) {
      const dim = state.showOnlyOpp && f !== sel && f !== opp;
      m.material.emissive = new THREE.Color(f === sel ? 0x224422 : f === opp ? 0x442222 : 0x000000);
      m.material.opacity = dim ? 0.18 : 1;
      m.material.transparent = dim;
    }
  }

  function pickFace(pack, e) {
    const rect = pack.canvas.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    const ray = new THREE.Raycaster();
    ray.setFromCamera({ x, y }, pack.camera);
    const hit = ray.intersectObjects(Object.values(pack.cube.meshes), false)[0];
    if (!hit) return;
    const f = hit.object.userData.face;
    if (state.vertexMode) {
      if (state.vertexPick.includes(f)) return;
      state.vertexPick.push(f);
      renderVertexCard(pack);
      if (state.vertexPick.length === 3) finishVertexPick(pack);
      return;
    }
    state.selected = f;
    highlight(pack);
    renderFaceCard();
  }

  function renderVertexCard(pack) {
    const el = document.getElementById("cb-vertex-card");
    if (!el) return;
    const names = state.vertexPick.map(f => NAMES[f] + "面").join("、") || "（点击立方体选面）";
    el.innerHTML = `已选：<b>${names}</b>${state.vertexPick.length < 3 ? `（还需 ${3 - state.vertexPick.length} 个两两相邻的面）` : ""}`;
  }
  function finishVertexPick(pack) {
    const [a, b, c] = state.vertexPick;
    const ok = adjacent(a, b) && adjacent(b, c) && adjacent(a, c);
    const el = document.getElementById("cb-vertex-card");
    if (!ok) {
      el.innerHTML += `<br><span style="color:var(--cb-red)">这三个面不是两两相邻（含相对面），不存在公共顶点。清除后重选。</span>`;
      state.vertexMode = false;
      const btn = document.getElementById("cb-btn-vertex");
      if (btn) { btn.classList.remove("on"); btn.textContent = "标三面共点"; }
      return;
    }
    attachVertexDots(pack, state.vertexPick);
    el.innerHTML += `<br>红点＝三面公共顶点。把折叠滑块拉到 0，看红点在展开图上可能是<b>分开的几个点</b>；慢慢折起，它们最终<b>重合为一个顶点</b>。箭头题就比箭头头尾与这个红点的关系。`;
    state.vertexMode = false;
    const btn = document.getElementById("cb-btn-vertex");
    if (btn) { btn.classList.remove("on"); btn.textContent = "标三面共点"; }
  }

  /* ---------------- 2D 展开图 SVG / 立体示意 SVG ---------------- */
  function symbolPath(kind, S, st) {
    const k = S / 48;
    if (kind === "wifi") {
      return `<circle r="${3.2 * k}" cy="${4 * k}" fill="#111"/>
        <path d="M ${-7 * k} ${-1 * k} A ${8 * k} ${8 * k} 0 0 1 ${7 * k} ${-1 * k}" fill="none" stroke="#111" stroke-width="${2.2 * k}"/>
        <path d="M ${-11 * k} ${-6 * k} A ${13 * k} ${13 * k} 0 0 1 ${11 * k} ${-6 * k}" fill="none" stroke="#111" stroke-width="${2.2 * k}"/>
        <path d="M ${-15 * k} ${-11 * k} A ${18 * k} ${18 * k} 0 0 1 ${15 * k} ${-11 * k}" fill="none" stroke="#111" stroke-width="${2.2 * k}"/>`;
    }
    if (kind === "arrow") {
      return `<path d="M 0 ${10 * k} L 0 ${-6 * k} M ${-7 * k} ${1 * k} L 0 ${-10 * k} L ${7 * k} ${1 * k}" fill="none" stroke="#111" stroke-width="${2.4 * k}" stroke-linecap="round"/>`;
    }
    if (kind === "plus") return `<path d="M ${-8 * k} 0 L ${8 * k} 0 M 0 ${-8 * k} L 0 ${8 * k}" fill="none" stroke="#111" stroke-width="${3 * k}"/>`;
    if (kind === "dot") return `<circle r="${6 * k}" fill="#111"/>`;
    if (kind === "letter") {
      return `<text text-anchor="middle" dominant-baseline="central" font-size="${18 * k}" font-weight="700" font-family="sans-serif">${(st && st.mark) || "A"}</text>`;
    }
    if (kind === "tri") return `<path d="M 0 ${-10 * k} L ${8 * k} ${8 * k} L ${-8 * k} ${8 * k} Z" fill="#111"/>`;
    if (kind === "slash") return `<path d="M ${-14 * k} ${-14 * k} L ${14 * k} ${14 * k}" fill="none" stroke="#111" stroke-width="${2.6 * k}" stroke-linecap="round"/>`;
    if (kind === "slash2") return `<path d="M ${14 * k} ${-14 * k} L ${-14 * k} ${14 * k}" fill="none" stroke="#111" stroke-width="${2.6 * k}" stroke-linecap="round"/>`;
    if (kind === "dice") {
      const n = (st && st.pips) || 1, o = 5.2 * k;
      const map = {
        1: [[0, 0]], 2: [[-o, -o], [o, o]], 3: [[-o, -o], [0, 0], [o, o]],
        4: [[-o, -o], [o, -o], [-o, o], [o, o]],
        5: [[-o, -o], [o, -o], [0, 0], [-o, o], [o, o]],
        6: [[-o, -o], [o, -o], [-o, 0], [o, 0], [-o, o], [o, o]],
      };
      return (map[n] || map[1]).map(([x, y]) => `<circle cx="${x}" cy="${y}" r="${2.1 * k}" fill="#111"/>`).join("");
    }
    return "";
  }

  function netSVG(layout, stickers, opts = {}) {
    const cells = Object.entries(layout);
    let minx = 9, miny = 9, maxx = -9, maxy = -9;
    for (const [, p] of cells) { minx = Math.min(minx, p.x); miny = Math.min(miny, p.y); maxx = Math.max(maxx, p.x); maxy = Math.max(maxy, p.y); }
    const S = opts.size || 48, pad = 8;
    const w = (maxx - minx + 1) * S + pad * 2, h = (maxy - miny + 1) * S + pad * 2;
    let body = "";
    for (const [f, p] of cells) {
      const x = pad + (p.x - minx) * S, y = pad + (maxy - p.y) * S;
      const st = stickers[f];
      body += `<g data-face="${f}" transform="translate(${x},${y})"><rect width="${S}" height="${S}" fill="${opts.exam ? "#fbfaf6" : st.color}" stroke="#1c1914" stroke-width="1.6"/>`;
      if (opts.sel === f) body += `<rect width="${S}" height="${S}" fill="none" stroke="#b5482e" stroke-width="3.2"/>`;
      if (st.sym === "image" && st.imageUrl) {
        body += `<image href="${st.imageUrl}" width="${S}" height="${S}" transform="rotate(${(st.rot + p.rot) * 90},${S / 2},${S / 2})"/>`;
        body += `<rect width="${S}" height="${S}" fill="none" stroke="${opts.sel === f ? "#b5482e" : "#1c1914"}" stroke-width="${opts.sel === f ? 3.2 : 1.6}"/>`;
      } else if (st.sym) {
        const pull = ["arrow", "tri", "wifi"].includes(st.sym) ? 0.1 * S : 0;
        const ox = [0, 1, 0, -1][st.edge || 0] * pull;
        const oy = [-1, 0, 1, 0][st.edge || 0] * pull;
        body += `<g transform="translate(${S / 2},${S / 2}) rotate(${(st.rot + p.rot) * 90}) translate(${ox},${oy})">${symbolPath(st.sym, S * 0.85, st)}</g>`;
      }
      if (!opts.exam && st.sym !== "image") body += `<text x="4" y="12" font-size="9" fill="#333">${NAMES[f]}</text>`;
      body += `</g>`;
    }
    return `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">${body}</svg>`;
  }

  function isoCubeSVG(stickers, vis) {
    const [f, u, r] = vis || ["F", "U", "R"];
    const facePoly = (pts, st) => {
      let g = `<polygon points="${pts}" fill="${st.color || "#fbfaf6"}" stroke="#1c1914" stroke-width="1.6"/>`;
      if (st.sym) {
        const xs = pts.split(" ").map(p => +p.split(",")[0]);
        const ys = pts.split(" ").map(p => +p.split(",")[1]);
        const cx = xs.reduce((a, b) => a + b, 0) / 4, cy = ys.reduce((a, b) => a + b, 0) / 4;
        g += `<g transform="translate(${cx},${cy}) scale(0.7)">${symbolPath(st.sym, 36, st)}</g>`;
      }
      return g;
    };
    return `<svg viewBox="0 0 180 160" xmlns="http://www.w3.org/2000/svg">
      ${facePoly("70,18 130,48 70,78 10,48", stickers[u])}
      ${facePoly("10,48 70,78 70,138 10,108", stickers[f])}
      ${facePoly("70,78 130,48 130,108 70,138", stickers[r])}
    </svg>`;
  }

  /* ---------------- 测验出题 ---------------- */
  function cloneStickers(s) { const o = {}; for (const f of FACE_LIST) o[f] = { ...s[f] }; return o; }
  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  }

  function decorateStickers(type) {
    const stickers = freshStickers();
    for (const f of FACE_LIST) { stickers[f].sym = null; stickers[f].rot = 0; stickers[f].edge = 0; }
    const pairs = [["F", "U"], ["F", "R"], ["U", "R"]];
    const [a, b] = pairs[Math.floor(Math.random() * pairs.length)];
    if (type === "dice") {
      const pip = { F: 1, B: 6, U: 2, D: 5, L: 3, R: 4 };
      for (const f of FACE_LIST) { stickers[f].sym = "dice"; stickers[f].pips = pip[f]; }
    } else if (type === "opp") {
      const marks = { F: "A", B: "A", U: "B", D: "B", L: "C", R: "C" };
      for (const f of FACE_LIST) { stickers[f].sym = "letter"; stickers[f].mark = marks[f]; }
    } else if (type === "invalid") {
      stickers.F.sym = "letter"; stickers.F.mark = "甲";
      stickers.U.sym = "letter"; stickers.U.mark = "乙";
      stickers.R.sym = "letter"; stickers.R.mark = "丙";
    } else {
      const sA = sideOfNeighbor(a, b), sB = sideOfNeighbor(b, a);
      const kinds = ["arrow", "arrow", "arrow", "tri", "letter", "plus", "dot", "slash", "slash2"];
      const kind = kinds[Math.floor(Math.random() * kinds.length)];
      stickers[a].sym = kind; stickers[b].sym = kind;
      stickers[a].rot = sA; stickers[a].edge = sA; stickers[b].rot = sB; stickers[b].edge = sB;
      if (kind === "letter") { stickers[a].mark = "P"; stickers[b].mark = "Q"; }
    }
    return { stickers, a, b };
  }

  function makeProblem(type) {
    type = type || (document.getElementById("cb-q-type") || {}).value || "net";
    const dec = decorateStickers(type);
    const stickers = dec.stickers;
    const pack0 = ALL_NETS[Math.floor(Math.random() * ALL_NETS.length)];
    const layout = pack0.layout, tree = pack0.children;
    const correct = { layout, stickers: cloneStickers(stickers), tree, ok: true };
    const opts = [correct];
    const marked = FACE_LIST.filter(f => stickers[f].sym && type !== "dice" && type !== "opp" && type !== "invalid");

    const d1 = cloneStickers(stickers);
    if (marked.length) {
      const f = marked[0];
      d1[f] = { ...d1[f], rot: (d1[f].rot + 2) % 4, edge: (d1[f].edge + 2) % 4 };
      opts.push({ layout, stickers: d1, tree, ok: false, why: `${NAMES[f]}面的符号转了180°。折成立体后，符号头部（或尾部）朝向的公共顶点、公共边是固定的——只翻一个面，头尾关系全反，直接排除。` });
    }
    const d2 = cloneStickers(stickers);
    if (marked.length) {
      const f = marked[marked.length - 1];
      d2[f] = { ...d2[f], rot: (d2[f].rot + 1) % 4, edge: (d2[f].edge + 1) % 4 };
      opts.push({ layout, stickers: d2, tree, ok: false, why: `${NAMES[f]}面的符号转了90°，立体图中它指向的那条边与展开图不一致。` });
    }
    const pack3 = ALL_NETS[Math.floor(Math.random() * ALL_NETS.length)];
    const d3s = cloneStickers(stickers);
    (d3s[marked[0] || "F"] || {}).rot != null && (d3s[marked[0] || "F"] = { ...d3s[marked[0] || "F"], rot: (d3s[marked[0] || "F"].rot + 2) % 4 });
    opts.push({ layout: pack3.layout, stickers: d3s, tree: pack3.children, ok: false, why: "展开图的外形可以不同（共11种），但两个符号面的相邻关系和符号指向必须与立体图一致；此项符号被扭转。" });
    const d4 = cloneStickers(stickers);
    if (marked.length >= 2) {
      const x = marked[0];
      const tmp = d4[x].sym;
      d4[x] = { ...d4[x], sym: d4[OPP[x]].sym, rot: d4[OPP[x]].rot, edge: d4[OPP[x]].edge };
      d4[OPP[x]] = { ...d4[OPP[x]], sym: tmp };
      opts.push({ layout, stickers: d4, tree, ok: false, why: `符号被挪到了${NAMES[x]}面的相对面上——立体图中同时可见的三个面两两相邻，相对面永远不可能同时出现。` });
    } else {
      const p4 = ALL_NETS[Math.floor(Math.random() * ALL_NETS.length)];
      const s4 = cloneStickers(stickers);
      if (s4.F.sym) s4.F = { ...s4.F, rot: (s4.F.rot + 3) % 4, edge: (s4.F.edge + 3) % 4 };
      opts.push({ layout: p4.layout, stickers: s4, tree: p4.children, ok: false, why: "符号方向与立体图不一致。" });
    }

    if (type === "opp") {
      const qf = ["F", "U", "L"][Math.floor(Math.random() * 3)];
      const five = shuffle([
        { text: `${NAMES[OPP[qf]]}面`, ok: true, why: "" },
        { text: `${NAMES[CYCLE[qf][0]]}面`, ok: false, why: "这是相邻面，不是相对面。" },
        { text: `${NAMES[CYCLE[qf][1]]}面`, ok: false, why: "这是侧面，与它相邻。" },
        { text: `${NAMES[CYCLE[qf][2]]}面`, ok: false, why: "这是侧面，与它相邻。" },
        { text: "三个面都与它相邻", ok: false, why: "一个面只有一个相对面。" },
      ]).slice(0, 5);
      return { stickers, tree, layout, options: five, type, prompt: `${NAMES[qf]}面的相对面是哪个？`, kind: "text", focus: qf };
    }
    if (type === "invalid") {
      const goods = shuffle(ALL_NETS.slice()).slice(0, 4).map(n => ({
        layout: n.layout, stickers, tree: n.children, ok: false,
        why: "该图可以折成正方体：没有五格连排，也没有 2×2 的方块。",
      }));
      const badLay = {
        F: { x: 0, y: 0, rot: 0 }, R: { x: 1, y: 0, rot: 0 }, B: { x: 2, y: 0, rot: 0 },
        L: { x: 3, y: 0, rot: 0 }, U: { x: 4, y: 0, rot: 0 }, D: { x: 2, y: -1, rot: 0 },
      };
      goods.push({ layout: badLay, stickers, tree, ok: true, why: "" });
      return { stickers, tree, layout, options: shuffle(goods), type, prompt: "下列展开图中，哪一个不能折成正方体？", kind: "net" };
    }
    if (type === "cube") {
      const views = [
        { vis: ["F", "U", "R"], ok: true },
        { vis: ["F", "U", "L"], ok: false, why: "左右颠倒，这是镜像图（相当于把展开图翻到背面），排除。" },
        { vis: ["B", "U", "R"], ok: false, why: "正面与展开图折出的面不符。" },
        { vis: ["F", "D", "R"], ok: false, why: "上下颠倒：该在顶面的到了底面。" },
        { vis: ["R", "U", "F"], ok: false, why: "三个面绕公共顶点的顺时针顺序与展开图不一致。" },
      ];
      const five = shuffle(views.map(v => ({ ...v, stickers, layout, tree, iso: v.vis })));
      return { stickers, tree, layout, options: five, type, prompt: "该展开图折成正方体后，是哪一个立体图？", kind: "iso" };
    }

    const five = opts.slice(0, 5);
    shuffle(five);
    return { stickers, tree, layout, options: five, type, prompt: "右边哪个展开图折成后与左边的立体图一致？", kind: "net" };
  }

  /* ---------------- 统计 ---------------- */
  function loadStats() {
    try { const s = JSON.parse(localStorage.getItem("goshore-cube") || "null"); if (s) state.stats = s; } catch (_) {}
  }
  function saveStats() { localStorage.setItem("goshore-cube", JSON.stringify(state.stats)); }

  /* ---------------- 挂载 ---------------- */
  function mount(root) {
    loadStats();
    state.stickers = freshStickers();
    applyNet((ALL_NETS.find(n => n.group === "一四一型" && n.name.includes("①")) || ALL_NETS[0]).name);

    root.innerHTML = `
      <div class="cb-wrap">
        <div class="cb-pagehead">
          <h1>空间折叠训练（折纸盒）</h1>
          <p>针对判断推理·图形推理空间构造题：相对面 → 公共边 → 三面共点（红点法），把空间想象变成可操作的机械动作</p>
        </div>
        <nav class="cb-tabs">
          <button data-mode="lab" class="on">折叠实验室</button>
          <button data-mode="nets">11种展开图</button>
          <button data-mode="rules">三条法则</button>
          <button data-mode="quiz">专项测验</button>
          <button data-mode="drill">60秒速练</button>
          <button data-mode="photo">拍照录题</button>
          <span class="cb-stats">累计答对 <b id="cb-ok">${state.stats.ok}</b> · 连对 <b id="cb-streak">${state.stats.streak}</b></span>
        </nav>

        <section id="cb-view-lab" class="cb-view on">
          <div class="cb-stage">
            <div id="cb-lab-canvas" class="cb-canvas"></div>
            <aside class="cb-panel">
              <button class="cb-btn ghost" id="cb-btn-back-photo" style="display:none;width:100%;margin-bottom:8px;border-color:#b5482e;color:#b5482e">← 返回录题修正</button>
              <h2>折叠控制</h2>
              <label class="cb-slider"><span>展开</span><input id="cb-fold" type="range" min="0" max="100" value="100"/><span>折起</span></label>
              <div class="cb-row">
                <button class="cb-btn ghost" id="cb-btn-flat">完全展开</button>
                <button class="cb-btn ghost" id="cb-btn-cube">完全折起</button>
              </div>
              <div class="cb-row">
                <button class="cb-btn primary" id="cb-btn-anim">慢动作折叠</button>
                <button class="cb-btn ghost" id="cb-btn-reset">复位视角</button>
              </div>
              <h2>贴符号（先点面，再贴）</h2>
              <p class="cb-tiny">模拟考卷上的箭头、三角、点数等方向性图案</p>
              <div class="cb-row" id="cb-sym-btns">
                <button class="cb-btn" data-sym="arrow">箭头</button>
                <button class="cb-btn" data-sym="tri">三角</button>
                <button class="cb-btn" data-sym="letter">字母</button>
                <button class="cb-btn" data-sym="dice">骰子点</button>
                <button class="cb-btn" data-sym="dot">圆点</button>
                <button class="cb-btn" data-sym="slash">斜线＼</button>
                <button class="cb-btn" data-sym="slash2">斜线／</button>
                <button class="cb-btn" data-sym="plus">十字</button>
                <button class="cb-btn ghost" data-sym="none">清除</button>
              </div>
              <div class="cb-row">
                <button class="cb-btn ghost" id="cb-btn-rot-ccw">↺ 转90°</button>
                <button class="cb-btn ghost" id="cb-btn-rot-cw">↻ 转90°</button>
              </div>
              <h2>当前面</h2>
              <div class="cb-card" id="cb-face-card"></div>
              <div class="cb-row"><button class="cb-btn ghost" id="cb-btn-opp">只看相对面</button></div>
              <h2>红点法（考场杀招）</h2>
              <button class="cb-btn red" id="cb-btn-vertex">标三面共点</button>
              <button class="cb-btn ghost" id="cb-btn-vertex-clear">清除红点</button>
              <div class="cb-card" id="cb-vertex-card" style="margin-top:8px">（点击立方体选面）</div>
              <h2>展开图形状</h2>
              <select class="cb-select" id="cb-net-select"></select>
              <p class="cb-tiny">共11种合法展开图，折起来都是同一个正方体</p>
            </aside>
            <div class="cb-net-preview">
              <div class="cb-tiny">当前展开图（不裁切的2D平面）</div>
              <div id="cb-lab-net"></div>
            </div>
            <div class="cb-hint">拖动旋转 · 滚轮缩放 · 滑块折叠。做箭头题时：先选三个可见面标红点，再把滑块在0和1之间拖动，观察箭头头尾与红点的关系。</div>
          </div>
        </section>

        <section id="cb-view-nets" class="cb-view">
          <div class="panel" style="background:var(--cb-paper);border:1px solid var(--cb-line);border-radius:8px;padding:16px">
            <h3 style="margin-top:0">正方体展开图只有 11 种</h3>
            <p style="color:var(--cb-ink2);line-height:1.8">六格拼法有35种，能折成正方体的只有 <b>11</b> 种：<b>一四一型6种、一三二型3种、三三型1种、二二二型1种</b>。其余折起后会重叠，或让相对面挨在一起。点击任意一种，自动带到实验室折叠。</p>
            <div class="cb-net-grid" id="cb-net-grid"></div>
          </div>
        </section>

        <section id="cb-view-rules" class="cb-view">
          <div class="panel" style="background:var(--cb-paper);border:1px solid var(--cb-line);border-radius:8px;padding:18px 22px">
            <h3 style="margin-top:0">折纸盒只看三件事</h3>
            <div class="cb-rule">
              <div class="n">1</div>
              <div>
                <h3>相对面永不相邻（10秒粗排）</h3>
                <p>上↔下、前↔后、左↔右。展开图中：同一行/列<strong>隔一个格</strong>的两面相对；呈 <strong>"Z"字形</strong>排列时，Z 的两端相对。选项若让一对相对面同时出现（共棱或共顶点），立即排除。</p>
                <div class="cb-demo" id="cb-demo-opp"></div>
              </div>
            </div>
            <div class="cb-rule">
              <div class="n">2</div>
              <div>
                <h3>三个可见面共一个顶点，绕点顺序不变</h3>
                <p>立体图一个顶角露出的三个面，折起后共一个顶点；三个面绕该顶点的<strong>顺时针次序在折叠前后保持不变</strong>。次序反了，等于把展开图翻到背面（镜像），直接排除。可用实验室的"标三面共点"看红点：展开时分开的几个格点，折起后重合为一个顶点。</p>
              </div>
            </div>
            <div class="cb-rule">
              <div class="n">3</div>
              <div>
                <h3>箭头只比"头、尾对公共点/公共边"</h3>
                <p>箭头、三角这类有方向的图案，旋转后就是另一个图案。判定四态：<strong>头部指向公共点／尾部挨着公共点／箭头平行于过点的边／垂直于过点的边</strong>。展开图与立体图必须逐面一致。最高频陷阱：<em>只把其中一个面转180°</em>。</p>
                <ul>
                  <li>立体图中两面箭头都指向公共点 → 展开图中也必须都指向折叠后的同一个点</li>
                  <li>立体图中箭头与公共边平行 → 展开图中也必须平行</li>
                  <li>只翻一个面（方向反掉）→ 排除</li>
                </ul>
              </div>
            </div>
            <div class="cb-rule">
              <div class="n" style="background:var(--cb-ink)">顺</div>
              <div>
                <h3>考场做题顺序（照此执行）</h3>
                <ol>
                  <li>相对面粗排：选项里有相对面同现的，划掉。</li>
                  <li>数三个可见面是否两两相邻、能否共一个顶点。</li>
                  <li>在展开图和选项上各描一个红点（三面公共顶点）。</li>
                  <li>逐个箭头面比"头部／尾部"与红点、公共边的关系。</li>
                  <li>还拿不准：去实验室给对应面贴上一样的箭头，拖滑块折一遍。</li>
                </ol>
              </div>
            </div>
          </div>
        </section>

        <section id="cb-view-quiz" class="cb-view">
          <div class="cb-stage" style="grid-template-columns:1fr">
            <div class="cb-qhead">
              <span id="cb-q-title"></span>
              <select class="cb-select" id="cb-q-type" style="width:auto">
                <option value="net">立体图 → 展开图</option>
                <option value="cube">展开图 → 立体图</option>
                <option value="opp">相对面判断</option>
                <option value="invalid">不能折成的图</option>
                <option value="dice">骰子点数</option>
              </select>
            </div>
            <div class="cb-split">
              <div>
                <div id="cb-quiz-canvas" class="cb-canvas short"></div>
                <p class="cb-center cb-tiny">可拖动旋转观察</p>
              </div>
              <div id="cb-choices" class="cb-choices"></div>
            </div>
            <div class="cb-explain" id="cb-explain"></div>
            <div class="cb-qnav">
              <button class="cb-btn primary" id="cb-btn-check">对答案</button>
              <button class="cb-btn ghost" id="cb-btn-why" disabled>折叠演示</button>
              <button class="cb-btn ghost" id="cb-btn-next">下一题</button>
            </div>
          </div>
        </section>

        <section id="cb-view-drill" class="cb-view">
          <div class="panel" style="background:var(--cb-paper);border:1px solid var(--cb-line);border-radius:8px;padding:18px">
            <div class="cb-qhead"><span>60秒速练——只练"相对面 / 相邻面"的瞬间判断</span><span class="cb-pill cb-timer" id="cb-timer">60</span></div>
            <p class="cb-lead" id="cb-drill-q">点开始后逐题出现</p>
            <div id="cb-drill-opts" class="cb-choices cb-row-choices"></div>
            <div class="cb-row"><button class="cb-btn primary" id="cb-btn-drill">开始60秒</button><span class="cb-tiny" id="cb-drill-score">本轮 0 题</span></div>
          </div>
        </section>

        <section id="cb-view-photo" class="cb-view">
          <div class="panel" style="background:var(--cb-paper);border:1px solid var(--cb-line);border-radius:8px;padding:18px">
            <h3 style="margin-top:0">拍照录题：截图还原展开图</h3>
            <p style="color:var(--cb-ink2);line-height:1.8">上传真题里的<b>平面展开图</b>截图，AI 定位6个面，再从原图裁剪贴到模型上：文字、数字、点数、阴影和复杂组合图案都能保留。点“带到实验室”可拖滑块折成立体。<br>请使用正视或接近正视的展开图；倾斜明显时请先矫正图片。单张立体照片无法还原被遮挡的面。尽量只截一个展开图；支持 <b>Ctrl+V</b> 粘贴。</p>
            <div id="cb-drop" class="cb-drop" tabindex="0">点击选择图片 · 拖入截图 · Ctrl+V 粘贴</div>
            <input type="file" id="cb-file" accept="image/*" hidden/>
            <div class="cb-photo-row">
              <div class="cb-photo-box"><div class="cb-tiny">原图</div><img id="cb-photo-img" alt=""/></div>
              <div class="cb-photo-box"><div class="cb-tiny">识别还原（2D平面图，点格子可修正）</div><div id="cb-photo-rec" class="cb-photo-rec">（识别后显示）</div></div>
            </div>
            <div class="cb-photo-edit" id="cb-photo-edit" style="display:none">
              <div class="cb-row" style="align-items:center;gap:10px">
                <span class="cb-tiny" id="cb-photo-sel">↑ 点击还原图中的格子，即可在这里修正图案</span>
                <button class="cb-btn ghost" id="cb-photo-rot" style="display:none">↻ 旋转90°</button>
              </div>
              <div class="cb-row" id="cb-photo-syms" style="display:none">
                <button class="cb-btn" data-psym="image">恢复原图</button>
                <button class="cb-btn" data-psym="none">空白</button>
                <button class="cb-btn" data-psym="arrow">箭头</button>
                <button class="cb-btn" data-psym="tri">三角</button>
                <button class="cb-btn" data-psym="slash">斜线＼</button>
                <button class="cb-btn" data-psym="slash2">斜线／</button>
                <button class="cb-btn" data-psym="plus">十字</button>
                <button class="cb-btn" data-psym="dot">圆点</button>
                <button class="cb-btn" data-psym="letter">字</button>
              </div>
              <div id="cb-photo-crop" style="display:none">
                <p class="cb-tiny">裁剪边界（占整张原图的百分比）：定位不准时调整边界，应用后对照预览检查。</p>
                <div class="cb-row">
                  ${["左", "上", "右", "下"].map((label, i) => `<label>${label} <input id="cb-crop-${i}" aria-label="裁剪${label}边界百分比" type="number" min="0" max="100" step="0.1" style="width:70px"/>%</label>`).join("")}
                  <button class="cb-btn" id="cb-crop-apply">应用裁剪</button>
                </div>
              </div>
            </div>
            <div class="cb-row">
              <button class="cb-btn primary" id="cb-photo-go" disabled>识别并还原</button>
              <button class="cb-btn ghost" id="cb-photo-lab" disabled>带到实验室折叠 →</button>
              <button class="cb-btn ghost" id="cb-photo-clear">清除</button>
            </div>
            <div class="cb-card" id="cb-photo-msg">六面均保留原图，不限图案种类。自动定位可能存在误差，请对照原图检查；点格子可修正裁剪范围、旋转或恢复原图。</div>
          </div>
        </section>
      </div>`;

    const $ = sel => root.querySelector(sel);
    const $$ = sel => [...root.querySelectorAll(sel)];

    /* ---- tab ---- */
    function setMode(m) {
      state.mode = m;
      $$(".cb-tabs button").forEach(b => b.classList.toggle("on", b.dataset.mode === m));
      $$(".cb-view").forEach(v => v.classList.remove("on"));
      $("#cb-view-" + m).classList.add("on");
      if (m === "lab" && lab) lab.frame();
      if (m === "quiz" && !state.quiz) { state.quiz = makeProblem("net"); renderQuiz(); }
    }
    root.querySelector(".cb-tabs").onclick = e => {
      const b = e.target.closest("button");
      if (b) setMode(b.dataset.mode);
    };

    /* ---- lab ---- */
    let lab = setupView($("#cb-lab-canvas"), false);
    lab.onTap = e => pickFace(lab, e);
    highlight(lab);
    renderFaceCard();
    paintLabNet();

    const netSel = $("#cb-net-select");
    netSel.innerHTML = ALL_NETS.map(n => `<option>${n.name}</option>`).join("");
    netSel.value = state.netName;
    netSel.onchange = () => {
      if (netSel.value === "__photo__" && photoResult) {
        // 从下拉重新选回"拍照还原"：恢复已修正过的模型
        state.tree = photoResult.tree; state.layout = photoResult.layout;
        state.netName = "__photo__"; state.stickers = photoResult.stickers;
        state.selected = "F";
      } else {
        applyNet(netSel.value);
        $("#cb-btn-back-photo").style.display = "none";
      }
      state.vertexPick = []; clearVertexDots(lab); lab.rebuild(); highlight(lab); paintLabNet(); if (state.vertexMode) renderVertexCard(lab);
    };
    const backPhotoBtn = $("#cb-btn-back-photo");
    backPhotoBtn.onclick = () => setMode("photo");

    const fold = $("#cb-fold");
    fold.oninput = () => { state.fold = Number(fold.value) / 100; lab.cube.setFold(state.fold); lab.frame(); };
    $("#cb-btn-flat").onclick = () => { fold.value = 0; state.fold = 0; lab.cube.setFold(0); lab.frame(); };
    $("#cb-btn-cube").onclick = () => { fold.value = 100; state.fold = 1; lab.cube.setFold(1); lab.frame(); };
    $("#cb-btn-reset").onclick = () => { lab.rig.rotation.set(0, 0, 0); lab.zoom = 1; lab.frame(); };
    $("#cb-btn-anim").onclick = () => {
      const from = state.fold, to = from > 0.5 ? 0 : 1, start = performance.now();
      (function tick(now) {
        const k = Math.min(1, (now - start) / 1400);
        const e = k < 0.5 ? 2 * k * k : -1 + (4 - 2 * k) * k;
        state.fold = from + (to - from) * e;
        fold.value = String(Math.round(state.fold * 100));
        lab.cube.setFold(state.fold); lab.frame();
        if (k < 1) requestAnimationFrame(tick);
      })(start);
    };
    $("#cb-sym-btns").onclick = e => {
      const b = e.target.closest("button");
      if (!b) return;
      const st = state.stickers[state.selected];
      st.sym = b.dataset.sym === "none" ? null : b.dataset.sym;
      lab.rebuild(); restoreDots(); highlight(lab); renderFaceCard(); paintLabNet();
    };
    $("#cb-btn-rot-cw").onclick = () => { const st = state.stickers[state.selected]; st.rot = (st.rot + 1) % 4; st.edge = (st.edge + 1) % 4; lab.rebuild(); restoreDots(); highlight(lab); renderFaceCard(); paintLabNet(); };
    $("#cb-btn-rot-ccw").onclick = () => { const st = state.stickers[state.selected]; st.rot = (st.rot + 3) % 4; st.edge = (st.edge + 3) % 4; lab.rebuild(); restoreDots(); highlight(lab); renderFaceCard(); paintLabNet(); };
    $("#cb-btn-opp").onclick = () => { state.showOnlyOpp = !state.showOnlyOpp; highlight(lab); };

    $("#cb-btn-vertex").onclick = () => {
      state.vertexMode = !state.vertexMode;
      const btn = $("#cb-btn-vertex");
      btn.classList.toggle("on", state.vertexMode);
      if (state.vertexMode) {
        state.vertexPick = [];
        btn.textContent = "选点中…再点取消";
        renderVertexCard(lab);
      } else {
        btn.textContent = "标三面共点";
      }
    };
    $("#cb-btn-vertex-clear").onclick = () => {
      state.vertexPick = []; state.vertexMode = false;
      const btn = $("#cb-btn-vertex"); btn.classList.remove("on"); btn.textContent = "标三面共点";
      clearVertexDots(lab); renderVertexCard(lab);
    };
    function restoreDots() {
      const [a, b, c] = state.vertexPick;
      if (state.vertexPick.length === 3 && adjacent(a, b) && adjacent(a, c) && adjacent(b, c)) attachVertexDots(lab, state.vertexPick);
    }

    function renderFaceCard() {
      const f = state.selected, st = state.stickers[f];
      const el = $("#cb-face-card");
      el.innerHTML = `<b>${NAMES[f]}面</b><br>相对面：${NAMES[OPP[f]]}面<br>相邻面：${CYCLE[f].map(n => NAMES[n] + "面").join("、")}<br>符号：${st.sym === "image" ? "原图" : st.sym || "无"} · 旋转 ${st.rot * 90}°`;
    }
    function paintLabNet() { $("#cb-lab-net").innerHTML = netSVG(state.layout, state.stickers, { size: 44 }); }

    /* ---- 11 种 ---- */
    const blank = {};
    for (const f of FACE_LIST) blank[f] = { id: f, color: COLORS[f], sym: null, rot: 0, edge: 0 };
    const grid = $("#cb-net-grid");
    ALL_NETS.forEach(n => {
      const card = document.createElement("button");
      card.className = "cb-net-card";
      card.innerHTML = `<div class="nm">${n.name}</div>${netSVG(n.layout, blank, { size: 32 })}`;
      card.onclick = () => {
        applyNet(n.name);
        state.vertexPick = []; clearVertexDots(lab);
        lab.rebuild(); highlight(lab); paintLabNet(); netSel.value = n.name;
        setMode("lab");
      };
      grid.appendChild(card);
    });
    $("#cb-demo-opp").innerHTML = netSVG(crossTree().layout, blank, { size: 34 });

    /* ---- 测验 ---- */
    let quiz3d = null;
    function renderQuiz() {
      const p = state.quiz;
      $("#cb-q-title").textContent = p.prompt;
      const box = $("#cb-choices");
      box.innerHTML = "";
      p.options.forEach((opt, i) => {
        const d = document.createElement("button");
        d.className = "cb-choice";
        d.innerHTML = `<span class="num">${["①", "②", "③", "④", "⑤"][i]}</span><span>${
          p.kind === "text" ? opt.text : p.kind === "iso" ? isoCubeSVG(opt.stickers, opt.iso) : netSVG(opt.layout, opt.stickers || p.stickers, { exam: true, size: 48 })
        }</span>`;
        d.onclick = () => { state.picked = i; [...box.children].forEach(c => c.classList.remove("on")); d.classList.add("on"); };
        box.appendChild(d);
      });
      const exp = $("#cb-explain");
      exp.classList.remove("show");
      $("#cb-btn-why").disabled = true;
      if (quiz3d) { quiz3d.destroy(); quiz3d = null; }
      const saved = { fold: state.fold, tree: state.tree, stickers: state.stickers, layout: state.layout };
      state.fold = p.kind === "iso" ? 0 : 1;
      state.tree = p.kind === "iso" ? p.tree : crossTree().children;
      state.layout = p.kind === "iso" ? p.layout : crossTree().layout;
      state.stickers = p.stickers;
      quiz3d = setupView($("#cb-quiz-canvas"), false);
      quiz3d.cube.setFold(state.fold); quiz3d.frame();
      Object.assign(state, saved);
    }
    function checkQuiz() {
      const p = state.quiz;
      if (state.picked == null) return;
      const box = $("#cb-choices");
      let good = false;
      p.options.forEach((opt, i) => {
        if (opt.ok) box.children[i].classList.add("ok");
        if (i === state.picked && !opt.ok) box.children[i].classList.add("bad");
        if (i === state.picked && opt.ok) good = true;
      });
      const exp = $("#cb-explain");
      exp.classList.add("show");
      if (good) {
        state.stats.ok += 1; state.stats.streak += 1;
        exp.innerHTML = "<b style='color:var(--cb-green)'>答对了。</b>记住：可见的符号面折起后共享哪条边、哪个顶点，展开图里就必须保持同样的头尾关系。";
      } else {
        state.stats.streak = 0;
        exp.innerHTML = "<b style='color:var(--cb-red)'>答错。</b>" + ((p.options[state.picked] || {}).why || "再核对公共边与符号方向。") + "<br>点「折叠演示」看正确答案折起的全过程。";
      }
      localStorage.setItem("goshore-cube", JSON.stringify(state.stats));
      $("#cb-ok").textContent = state.stats.ok; $("#cb-streak").textContent = state.stats.streak;
      $("#cb-btn-why").disabled = false;
    }
    function whyQuiz() {
      const correct = state.quiz.options.find(o => o.ok);
      if (quiz3d) { quiz3d.destroy(); quiz3d = null; }
      state.stickers = correct.stickers; state.tree = correct.tree; state.layout = correct.layout; state.fold = 0;
      quiz3d = setupView($("#cb-quiz-canvas"), false);
      quiz3d.cube.setFold(0); quiz3d.frame();
      const start = performance.now();
      (function tick(now) {
        const t = Math.min(1, (now - start) / 1800);
        const e = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
        if (!quiz3d) return;
        quiz3d.cube.setFold(e); quiz3d.frame();
        if (t < 1) requestAnimationFrame(tick);
      })(start);
    }
    $("#cb-btn-check").onclick = checkQuiz;
    $("#cb-btn-why").onclick = whyQuiz;
    $("#cb-btn-next").onclick = () => { state.picked = null; state.quiz = makeProblem($("#cb-q-type").value); renderQuiz(); };
    $("#cb-q-type").onchange = () => { state.picked = null; state.quiz = makeProblem($("#cb-q-type").value); renderQuiz(); };

    /* ---- 速练 ---- */
    function nextDrill() {
      const type = Math.random() < 0.5 ? "opp" : "adj";
      const f = FACE_LIST[Math.floor(Math.random() * 6)];
      const qel = $("#cb-drill-q"), box = $("#cb-drill-opts");
      box.innerHTML = "";
      if (type === "opp") {
        qel.textContent = `${NAMES[f]}面的相对面是？`;
        const opts = shuffle([OPP[f], ...shuffle(FACE_LIST.filter(x => x !== f && x !== OPP[f])).slice(0, 3)]);
        opts.forEach(id => {
          const b = document.createElement("button"); b.className = "cb-choice"; b.textContent = NAMES[id] + "面";
          b.onclick = () => drillAnswer(id === OPP[f], b); box.appendChild(b);
        });
      } else {
        const n = CYCLE[f][Math.floor(Math.random() * 4)];
        qel.textContent = `${NAMES[f]}面与${NAMES[n]}面是什么关系？`;
        [["相邻（共一条棱）", true], ["相对（永不相邻）", false], ["不可能共顶点", false]].forEach(([t, ok]) => {
          const b = document.createElement("button"); b.className = "cb-choice"; b.textContent = t;
          b.onclick = () => drillAnswer(ok, b); box.appendChild(b);
        });
      }
    }
    function drillAnswer(ok, btn) {
      if (!state.drill || !state.drill.on) return;
      btn.classList.add(ok ? "ok" : "bad");
      if (ok) { state.drill.score += 1; state.stats.ok += 1; state.stats.streak += 1; } else { state.stats.streak = 0; }
      $("#cb-drill-score").textContent = `本轮 ${state.drill.score} 题`;
      localStorage.setItem("goshore-cube", JSON.stringify(state.stats));
      $("#cb-ok").textContent = state.stats.ok; $("#cb-streak").textContent = state.stats.streak;
      setTimeout(() => { if (state.drill && state.drill.on) nextDrill(); }, 220);
    }
    let drillTimer = null;
    $("#cb-btn-drill").onclick = () => {
      if (state.drill && state.drill.on) return;
      state.drill = { on: true, score: 0, left: 60 };
      $("#cb-drill-score").textContent = "本轮 0 题";
      nextDrill();
      clearInterval(drillTimer);
      drillTimer = setInterval(() => {
        state.drill.left -= 1;
        $("#cb-timer").textContent = state.drill.left;
        if (state.drill.left <= 0) {
          clearInterval(drillTimer); state.drill.on = false;
          $("#cb-drill-q").textContent = `结束：本轮答对 ${state.drill.score} 题。`;
        }
      }, 1000);
    };

    /* ---- 拍照录题 ---- */
    let photoDataURL = null, photoResult = null, photoBusy = false, photoRevision = 0;
    let photoRequest = null;
    const drop = $("#cb-drop"), fileIn = $("#cb-file"), pImg = $("#cb-photo-img");
    const goBtn = $("#cb-photo-go"), labBtn = $("#cb-photo-lab"), clearBtn = $("#cb-photo-clear");
    const recBox = $("#cb-photo-rec"), msgBox = $("#cb-photo-msg");

    function fileToDataURL(file) {
      return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => {
          // 线条图用 PNG 保真度远高于 JPEG，AI 识别更准；限制最大边 1600
          const sc = Math.min(1, 1600 / Math.max(img.width, img.height));
          const w = Math.max(1, Math.round(img.width * sc)), h = Math.max(1, Math.round(img.height * sc));
          const c = document.createElement("canvas");
          c.width = w; c.height = h;
          const cx = c.getContext("2d");
          cx.fillStyle = "#fff"; cx.fillRect(0, 0, w, h);
          cx.drawImage(img, 0, 0, w, h);
          URL.revokeObjectURL(url);
          resolve(c.toDataURL("image/png"));
        };
        img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("图片读取失败")); };
        img.src = url;
      });
    }
    function setPhoto(dataUrl) {
      photoRevision += 1;
      if (photoRequest) photoRequest.abort();
      photoBusy = false;
      photoDataURL = dataUrl; photoResult = null;
      photoEditFace = null; photoEdit.style.display = "none";
      pImg.src = dataUrl; pImg.style.display = "";
      recBox.textContent = "（待识别）";
      goBtn.disabled = false; labBtn.disabled = true;
      msgBox.textContent = "图片已载入，点「识别并还原」（约需 5-15 秒）";
    }
    async function ingestFile(file) {
      if (!file || !file.type.startsWith("image/")) return;
      try { setPhoto(await fileToDataURL(file)); }
      catch (e) { msgBox.textContent = "图片读取失败，请换一张截图"; }
    }
    drop.onclick = () => fileIn.click();
    fileIn.onchange = () => ingestFile(fileIn.files[0]);
    drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", e => {
      e.preventDefault(); drop.classList.remove("over");
      ingestFile(e.dataTransfer.files[0]);
    });
    async function onPaste(e) {
      if (state.mode !== "photo") return;
      const item = [...(e.clipboardData && e.clipboardData.items ? e.clipboardData.items : [])]
        .find(it => (it.type || "").startsWith("image/"));
      if (item) { e.preventDefault(); await ingestFile(item.getAsFile()); }
    }
    document.addEventListener("paste", onPaste);

    goBtn.onclick = async () => {
      if (photoBusy || !photoDataURL) return;
      const revision = ++photoRevision, requestedImage = photoDataURL;
      photoRequest = new AbortController();
      photoBusy = true; goBtn.disabled = true;
      photoResult = null; labBtn.disabled = true;
      photoEdit.style.display = "none"; photoEditFace = null;
      recBox.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;gap:10px;padding:30px 0"><div class="cb-spin"></div><span class="cb-tiny">AI 识别中（5-15秒）…</span></div>';
      msgBox.textContent = "AI 识别中，请稍候……";
      try {
        const r = await fetch("/api/cube/recognize", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image: requestedImage }), signal: photoRequest.signal,
        });
        const d = await r.json().catch(() => ({}));
        if (revision !== photoRevision) return;
        if (!r.ok) throw new Error(d.detail || `识别失败（${r.status}）`);
        if (!d.is_net) {
          msgBox.textContent = "未在图中找到平面六格展开图（立体透视图无法还原）。请只截取平面展开图部分后重试。" + (d.note ? ` AI备注：${d.note}` : "");
          recBox.textContent = "—";
          goBtn.disabled = false;
          return;
        }
        const matched = matchRecognizedNet(d.cells);
        if (!matched) {
          msgBox.textContent = "识别出的6格位置拼不出合法正方体展开图（折起会重叠），可能格子定位有误，请截得更正、更清晰后重试。";
          recBox.textContent = "—";
          goBtn.disabled = false;
          return;
        }
        const sourceImage = await loadPhotoImage(requestedImage);
        if (revision !== photoRevision) return;
        const stickers = imageStickersFromRecognized(matched, sourceImage);
        photoResult = { name: matched.net.name, tree: matched.net.children, layout: matched.layout, stickers, sourceImage };
        renderPhotoRec();
        photoEdit.style.display = "";
        photoRot.style.display = "none"; photoSyms.style.display = "none"; photoCrop.style.display = "none";
        photoSel.textContent = "↑ 点击还原图中的格子，可修正裁剪和方向";
        const marked = matched.map.filter(m => m.cl && m.cl.kind !== "none" && m.cl.kind).length;
        msgBox.textContent = `还原成功：${matched.net.name}，已保留6个面的原始图案（${marked}个面有图案描述）。点格子可修正裁剪和方向，确认无误后带到实验室。`;
        labBtn.disabled = false; goBtn.disabled = false;
      } catch (e) {
        if (revision !== photoRevision || e.name === "AbortError") return;
        msgBox.textContent = String(e.message || e);
        recBox.textContent = "—";
        goBtn.disabled = false;
      } finally { if (revision === photoRevision) { photoBusy = false; photoRequest = null; } }
    };

    /* ---- 拍照结果修正编辑器 ---- */
    const photoEdit = $("#cb-photo-edit"), photoSel = $("#cb-photo-sel"), photoRot = $("#cb-photo-rot"), photoSyms = $("#cb-photo-syms");
    const photoCrop = $("#cb-photo-crop");
    let photoEditFace = null;
    function renderPhotoRec() {
      if (!photoResult) return;
      recBox.innerHTML = netSVG(photoResult.layout, photoResult.stickers, { size: 52, sel: photoEditFace });
      // 绑定点击
      recBox.querySelectorAll("[data-face]").forEach(g => {
        g.style.cursor = "pointer";
        g.onclick = () => {
          photoEditFace = g.dataset.face;
          photoSel.textContent = `已选中：${NAMES[photoEditFace]}面`;
          photoRot.style.display = "";
          photoSyms.style.display = "flex";
          photoCrop.style.display = "";
          photoResult.stickers[photoEditFace].bbox.forEach((v, i) => { $("#cb-crop-" + i).value = Number((v * 100).toFixed(3)); });
          renderPhotoRec();
        };
      });
    }
    photoRot.onclick = () => {
      if (!photoEditFace || !photoResult) return;
      const st = photoResult.stickers[photoEditFace];
      st.rot = ((st.rot || 0) + 1) % 4;
      st.edge = st.rot;
      renderPhotoRec();
    };
    $("#cb-crop-apply").onclick = () => {
      if (!photoEditFace || !photoResult) return;
      try {
        const bbox = [0, 1, 2, 3].map(i => {
          const value = $("#cb-crop-" + i).value;
          return value.trim() ? Number(value) / 100 : NaN;
        });
        Object.assign(photoResult.stickers[photoEditFace], cropFaceImage(photoResult.sourceImage, bbox), { sym: "image" });
        renderPhotoRec();
        msgBox.textContent = "裁剪已更新，请核对是否保留整个面、且未包含邻面。";
      } catch (e) { msgBox.textContent = e.message; }
    };
    photoSyms.querySelectorAll("[data-psym]").forEach(b => {
      b.onclick = () => {
        if (!photoEditFace || !photoResult) return;
        const v = b.dataset.psym;
        const st = photoResult.stickers[photoEditFace];
        if (v === "none") { st.sym = null; }
        else if (v === "image") {
          st.sym = "image";
          st.rot = st.edge = (4 - photoResult.layout[photoEditFace].rot) % 4;
        }
        else { st.sym = v; if (st.sym === "letter") { st.mark = st.mark || "A"; } }
        renderPhotoRec();
      };
    });

    labBtn.onclick = () => {
      if (!photoResult) return;
      // 拍照还原的 layout 以原图方位重建，下拉框用临时项承接，不覆盖 state
      state.tree = photoResult.tree;
      state.layout = photoResult.layout;
      state.netName = "__photo__";
      state.stickers = photoResult.stickers;
      state.selected = "F"; state.vertexMode = false; state.vertexPick = [];
      clearVertexDots(lab);
      state.fold = 0;
      const fold0 = $("#cb-fold"); fold0.value = 0;
      if (!netSel.querySelector('option[value="__photo__"]')) {
        const op = document.createElement("option");
        op.value = "__photo__"; op.textContent = "拍照还原（" + photoResult.name + "）";
        netSel.insertBefore(op, netSel.firstChild);
      }
      netSel.value = "__photo__";
      lab.rebuild(); highlight(lab); renderFaceCard(); paintLabNet();
      const vBtn = $("#cb-btn-vertex"); vBtn.classList.remove("on"); vBtn.textContent = "标三面共点";
      renderVertexCard(lab);
      $("#cb-btn-back-photo").style.display = "";
      setMode("lab");
    };

    clearBtn.onclick = () => {
      photoRevision += 1;
      if (photoRequest) photoRequest.abort();
      photoRequest = null; photoBusy = false;
      photoDataURL = null; photoResult = null; photoEditFace = null;
      photoEdit.style.display = "none";
      pImg.removeAttribute("src"); pImg.style.display = "none";
      fileIn.value = "";
      recBox.textContent = "（识别后显示）";
      goBtn.disabled = true; labBtn.disabled = true;
      msgBox.textContent = "六面均保留原图，不限图案种类。点还原图中的格子可修正裁剪范围、旋转或恢复原图。";
    };

    /* ---- 卸载 ---- */
    function destroy() {
      photoRevision += 1;
      if (photoRequest) photoRequest.abort();
      clearInterval(drillTimer);
      document.removeEventListener("paste", onPaste);
      if (lab) { lab.destroy(); lab = null; }
      if (quiz3d) { quiz3d.destroy(); quiz3d = null; }
      window.removeEventListener("hashchange", destroy);
      delete window.GOSCubeActive;
    }
    window.addEventListener("hashchange", destroy);
    window.GOSCubeActive = destroy;
    return { destroy };
  }

  window.GOSCube = { mount, matchRecognizedNet, stickersFromRecognized };
})();
