/* 전개도 도장 — cube net trainer */
(() => {
  const OPP = { F: "B", B: "F", U: "D", D: "U", L: "R", R: "L" };
  // 밖에서 볼 때 시계방향: 북 동 남 서
  const CYCLE = {
    F: ["U", "R", "D", "L"],
    B: ["U", "L", "D", "R"],
    U: ["B", "R", "F", "L"],
    D: ["F", "R", "B", "L"],
    L: ["U", "F", "D", "B"],
    R: ["U", "B", "D", "F"],
  };
  const NAMES = { F: "앞", B: "뒤", U: "위", D: "아래", L: "왼", R: "오" };
  const COLORS = {
    F: "#f4d35e",
    B: "#ee964b",
    U: "#d8e2dc",
    D: "#c9ada7",
    L: "#7eb8da",
    R: "#9b5de5",
  };
  const DIR = [
    { x: 0, y: 1 },
    { x: 1, y: 0 },
    { x: 0, y: -1 },
    { x: -1, y: 0 },
  ];
  const FACE_LIST = ["F", "B", "U", "D", "L", "R"];

  const state = {
    mode: "lab",
    fold: 1,
    selected: "F",
    stickers: {},
    layout: null,
    tree: null,
    showOnlyOpp: false,
    stats: { ok: 0, streak: 0 },
    quiz: null,
    picked: null,
    drill: null,
  };

  function loadStats() {
    try {
      const s = JSON.parse(localStorage.getItem("cube-dojang") || "null");
      if (s) state.stats = s;
    } catch (_) {}
    paintStats();
  }
  function saveStats() {
    localStorage.setItem("cube-dojang", JSON.stringify(state.stats));
    paintStats();
  }
  function paintStats() {
    const el = document.getElementById("stats");
    if (el) el.textContent = `맞힘 ${state.stats.ok} · 연속 ${state.stats.streak}`;
  }

  function freshStickers() {
    const s = {};
    for (const f of FACE_LIST) {
      s[f] = { id: f, color: COLORS[f], sym: null, rot: 0, edge: 0 };
    }
    s.F.sym = "arrow";
    s.F.rot = 0;
    s.F.edge = 0;
    s.U.sym = "arrow";
    s.U.rot = 2;
    s.U.edge = 2;
    s.F.mark = "A";
    s.B.mark = "B";
    s.U.mark = "C";
    s.D.mark = "D";
    s.L.mark = "E";
    s.R.mark = "F";
    s.F.pips = 1;
    s.B.pips = 6;
    s.U.pips = 2;
    s.D.pips = 5;
    s.L.pips = 3;
    s.R.pips = 4;
    return s;
  }

  function sideOfNeighbor(face, neighbor) {
    return CYCLE[face].indexOf(neighbor);
  }

  function layoutFromTree(root, children) {
    const pos = { [root]: { x: 0, y: 0, rot: 0 } };
    const occ = { "0,0": root };
    const q = [root];
    while (q.length) {
      const a = q.shift();
      const kids = children[a] || [];
      for (const b of kids) {
        const sA = sideOfNeighbor(a, b);
        if (sA < 0) return null;
        const netDir = (sA + pos[a].rot) % 4;
        const nx = pos[a].x + DIR[netDir].x;
        const ny = pos[a].y + DIR[netDir].y;
        const key = `${nx},${ny}`;
        if (occ[key]) return null;
        const sB = sideOfNeighbor(b, a);
        const back = (netDir + 2) % 4;
        const rotB = (back - sB + 4) % 4;
        pos[b] = { x: nx, y: ny, rot: rotB };
        occ[key] = b;
        q.push(b);
      }
    }
    if (Object.keys(pos).length !== 6) return null;
    return pos;
  }

  function randomTree() {
    for (let attempt = 0; attempt < 80; attempt++) {
      const children = { F: [], B: [], U: [], D: [], L: [], R: [] };
      const seen = new Set(["F"]);
      const stack = ["F"];
      while (stack.length) {
        const a = stack[stack.length - 1];
        const opts = CYCLE[a].filter((n) => !seen.has(n));
        if (!opts.length) {
          stack.pop();
          continue;
        }
        const b = opts[Math.floor(Math.random() * opts.length)];
        children[a].push(b);
        seen.add(b);
        stack.push(b);
      }
      const lay = layoutFromTree("F", children);
      if (lay) return { children, layout: lay };
    }
    return crossTree();
  }

  function emptyKids() {
    return { F: [], B: [], U: [], D: [], L: [], R: [] };
  }

  function cloneKids(k) {
    const o = emptyKids();
    for (const f of FACE_LIST) o[f] = [...(k[f] || [])];
    return o;
  }

  function crossTree() {
    const children = emptyKids();
    children.F = ["U", "D", "L", "R"];
    children.R = ["B"];
    return { children, layout: layoutFromTree("F", children) };
  }

  function shapeKey(layout) {
    const cells = Object.values(layout).map((p) => [p.x, p.y]);
    const keys = [];
    for (const flip of [false, true]) {
      for (let r = 0; r < 4; r++) {
        const pts = cells.map(([x, y]) => {
          let xx = flip ? -x : x;
          let yy = y;
          if (r === 1) [xx, yy] = [yy, -xx];
          else if (r === 2) [xx, yy] = [-xx, -yy];
          else if (r === 3) [xx, yy] = [-yy, xx];
          return [xx, yy];
        });
        const mx = Math.min(...pts.map((p) => p[0]));
        const my = Math.min(...pts.map((p) => p[1]));
        const norm = pts
          .map(([x, y]) => [x - mx, y - my])
          .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
        keys.push(norm.map((p) => p.join(",")).join(";"));
      }
    }
    return keys.sort()[0];
  }

  function netIllegal(layout) {
    const cells = Object.values(layout);
    const set = new Set(cells.map((p) => `${p.x},${p.y}`));
    for (const p of cells) {
      if (
        set.has(`${p.x + 1},${p.y}`) &&
        set.has(`${p.x},${p.y + 1}`) &&
        set.has(`${p.x + 1},${p.y + 1}`)
      )
        return true;
      for (const [dx, dy] of [
        [1, 0],
        [0, 1],
      ]) {
        let n = 1;
        let x = p.x + dx;
        let y = p.y + dy;
        while (set.has(`${x},${y}`)) {
          n += 1;
          x += dx;
          y += dy;
        }
        if (n >= 5) return true;
      }
    }
    return false;
  }

  function classifyNet(layout) {
    const pts = Object.values(layout);
    const set = new Set(pts.map((p) => `${p.x},${p.y}`));
    const deg = (x, y) => DIR.filter((d) => set.has(`${x + d.x},${y + d.y}`)).length;
    const degs = pts.map((p) => deg(p.x, p.y));
    const w = Math.max(...pts.map((p) => p.x)) - Math.min(...pts.map((p) => p.x)) + 1;
    const h = Math.max(...pts.map((p) => p.y)) - Math.min(...pts.map((p) => p.y)) + 1;
    const long = Math.max(w, h);
    const short = Math.min(w, h);
    if (Math.max(...degs) === 4) return "십자가";
    if (long === 4 && short === 3 && degs.filter((d) => d === 1).length === 3) return "T자";
    if (long === 4 && short === 2) return "일렬+날개";
    if (long === 5) return "긴 줄기";
    if (short === 2 && long === 3) return "직사각";
    if (degs.filter((d) => d === 1).length === 2 && degs.includes(3)) return "계단(S/Z)";
    return "가지";
  }

  function labelHex(cells, name) {
    const set = new Set(cells.map((c) => `${c[0]},${c[1]}`));
    const dirs = [
      [0, 1],
      [1, 0],
      [0, -1],
      [-1, 0],
    ];
    for (const start of cells) {
      for (let rot0 = 0; rot0 < 4; rot0++) {
        const faceAt = {};
        const layout = {};
        const q = [{ f: "F", x: start[0], y: start[1], rot: rot0 }];
        faceAt[`${start[0]},${start[1]}`] = "F";
        layout.F = { x: start[0], y: start[1], rot: rot0 };
        let ok = true;
        while (q.length && ok) {
          const cur = q.shift();
          for (let nd = 0; nd < 4; nd++) {
            const nx = cur.x + dirs[nd][0];
            const ny = cur.y + dirs[nd][1];
            const nk = `${nx},${ny}`;
            if (!set.has(nk)) continue;
            const local = (nd - cur.rot + 4) % 4;
            const nb = CYCLE[cur.f][local];
            if (faceAt[nk] && faceAt[nk] !== nb) {
              ok = false;
              break;
            }
            if (layout[nb] && (layout[nb].x !== nx || layout[nb].y !== ny)) {
              ok = false;
              break;
            }
            if (!layout[nb]) {
              const sB = sideOfNeighbor(nb, cur.f);
              const rotB = ((nd + 2) - sB + 4) % 4;
              faceAt[nk] = nb;
              layout[nb] = { x: nx, y: ny, rot: rotB };
              q.push({ f: nb, x: nx, y: ny, rot: rotB });
            }
          }
        }
        if (ok && Object.keys(layout).length === 6) {
          const children = emptyKids();
          const seenT = new Set(["F"]);
          const qq = ["F"];
          while (qq.length) {
            const a = qq.shift();
            for (const b of CYCLE[a]) {
              if (!layout[b] || seenT.has(b)) continue;
              const dx = layout[b].x - layout[a].x;
              const dy = layout[b].y - layout[a].y;
              if (Math.abs(dx) + Math.abs(dy) !== 1) continue;
              children[a].push(b);
              seenT.add(b);
              qq.push(b);
            }
          }
          if (seenT.size !== 6) continue;
          return { name, type: name, children, layout };
        }
      }
    }
    return null;
  }

  function enumerateNets() {
    const found = [];
    const seen = new Set();
    const kids = emptyKids();
    const used = new Set(["F"]);

    function rec() {
      if (used.size === 6) {
        const lay = layoutFromTree("F", kids);
        if (!lay || netIllegal(lay)) return;
        const key = shapeKey(lay);
        if (seen.has(key)) return;
        seen.add(key);
        found.push({
          children: cloneKids(kids),
          layout: lay,
          key,
          type: classifyNet(lay),
        });
        return;
      }
      for (const a of [...used]) {
        for (const b of CYCLE[a]) {
          if (used.has(b)) continue;
          kids[a].push(b);
          used.add(b);
          rec();
          used.delete(b);
          kids[a].pop();
        }
      }
    }
    rec();
    found.sort((a, b) => a.type.localeCompare(b.type, "ko") || a.key.localeCompare(b.key));
    const count = {};
    const typeTotal = {};
    found.forEach((n) => {
      typeTotal[n.type] = (typeTotal[n.type] || 0) + 1;
    });
    found.forEach((n) => {
      count[n.type] = (count[n.type] || 0) + 1;
      n.name = typeTotal[n.type] > 1 ? `${n.type} ${count[n.type]}` : n.type;
    });
    return found;
  }

  const ALL_NETS = enumerateNets();

  function applyNet(kind) {
    const byName = ALL_NETS.find((n) => n.name === kind);
    const t = byName || ALL_NETS[0] || crossTree();
    state.tree = t.children;
    state.layout = t.layout;
    state.netName = t.name || kind;
  }

  /* ---------- textures ---------- */
  function drawPips(ctx, n, size) {
    const r = size * 0.055;
    const o = size * 0.16;
    const spots = {
      1: [[0, 0]],
      2: [[-o, -o], [o, o]],
      3: [[-o, -o], [0, 0], [o, o]],
      4: [[-o, -o], [o, -o], [-o, o], [o, o]],
      5: [[-o, -o], [o, -o], [0, 0], [-o, o], [o, o]],
      6: [[-o, -o], [o, -o], [-o, 0], [o, 0], [-o, o], [o, o]],
    };
    for (const [x, y] of spots[n] || spots[1]) {
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function drawSymbol(ctx, kind, rot, edge, size, sticker) {
    if (!kind) return;
    const dir = edge == null ? rot : edge;
    ctx.save();
    ctx.translate(size / 2, size / 2);
    // 0=북(-y) 1=동 2=남 3=서. 기호가 그 변을 향하게.
    ctx.rotate((dir * Math.PI) / 2);
    if (kind === "arrow" || kind === "tri" || kind === "wifi") ctx.translate(0, -size * 0.05);
    ctx.strokeStyle = "#111";
    ctx.fillStyle = "#111";
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (kind === "wifi") {
      ctx.beginPath();
      ctx.arc(0, 10, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineWidth = 5;
      for (let i = 1; i <= 3; i++) {
        ctx.beginPath();
        ctx.arc(0, 12, 8 + i * 9, -Math.PI * 0.75, -Math.PI * 0.25);
        ctx.stroke();
      }
    } else if (kind === "arrow") {
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.moveTo(0, 18);
      ctx.lineTo(0, -14);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(-14, 2);
      ctx.lineTo(0, -20);
      ctx.lineTo(14, 2);
      ctx.stroke();
    } else if (kind === "tri") {
      ctx.beginPath();
      ctx.moveTo(0, -18);
      ctx.lineTo(16, 14);
      ctx.lineTo(-16, 14);
      ctx.closePath();
      ctx.fill();
    } else if (kind === "plus") {
      ctx.lineWidth = 8;
      ctx.beginPath();
      ctx.moveTo(-18, 0);
      ctx.lineTo(18, 0);
      ctx.moveTo(0, -18);
      ctx.lineTo(0, 18);
      ctx.stroke();
    } else if (kind === "dot") {
      ctx.beginPath();
      ctx.arc(0, 0, 16, 0, Math.PI * 2);
      ctx.fill();
    } else if (kind === "letter") {
      ctx.font = "bold 92px Malgun Gothic, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(sticker && sticker.mark ? sticker.mark : "A", 0, 4);
    } else if (kind === "dice") {
      drawPips(ctx, (sticker && sticker.pips) || 1, size);
    }
    ctx.restore();
  }

  function faceTexture(sticker, opts = {}) {
    const size = 256;
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const ctx = c.getContext("2d");
    ctx.fillStyle = opts.exam ? "#fbfaf6" : sticker.color;
    ctx.fillRect(0, 0, size, size);
    ctx.strokeStyle = "#2b261f";
    ctx.lineWidth = 10;
    ctx.strokeRect(6, 6, size - 12, size - 12);
    if (!opts.exam) {
      ctx.fillStyle = "rgba(0,0,0,.35)";
      ctx.font = "bold 36px Malgun Gothic, sans-serif";
      ctx.textAlign = "left";
      ctx.font = "bold 28px Malgun Gothic, sans-serif";
      ctx.fillText(NAMES[sticker.id], 22, 48);
    }
    drawSymbol(ctx, sticker.sym, sticker.rot, sticker.edge, size, sticker);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 8;
    return tex;
  }

  /* ---------- 3D fold ---------- */
  let lab = null;
  let quiz3d = null;

  function disposeScene(pack) {
    if (!pack) return;
    pack.renderer.dispose();
    pack.canvas.replaceChildren();
  }

  function makeFaceMesh(sticker, exam) {
    const geo = new THREE.PlaneGeometry(1, 1);
    const mat = new THREE.MeshStandardMaterial({
      map: faceTexture(sticker, { exam }),
      roughness: 0.55,
      metalness: 0.02,
      side: THREE.DoubleSide,
    });
    const m = new THREE.Mesh(geo, mat);
    m.userData.face = sticker.id;
    return m;
  }

  function buildFoldingCube(stickers, tree, layout, exam) {
    const group = new THREE.Group();
    const hinges = {};
    const meshes = {};

    function attach(child, parent, parentHinge) {
      const p = layout[parent];
      const c = layout[child];
      const dx = c.x - p.x;
      const dy = c.y - p.y;
      let netDir = 0;
      if (dx === 1) netDir = 1;
      else if (dx === -1) netDir = 3;
      else if (dy === 1) netDir = 0;
      else netDir = 2;

      const hinge = new THREE.Group();
      // parent hinge origin = incoming edge of parent (or center if root)
      const parentMesh = meshes[parent];
      const shared = {
        x: parentMesh.position.x + DIR[netDir].x * 0.5,
        y: parentMesh.position.y + DIR[netDir].y * 0.5,
        z: 0,
      };
      hinge.position.set(shared.x, shared.y, shared.z);
      parentHinge.add(hinge);

      const mesh = makeFaceMesh(stickers[child], exam);
      mesh.position.set(DIR[netDir].x * 0.5, DIR[netDir].y * 0.5, 0);
      // rotate mesh so its local up matches layout rot relative to parent?
      // Stickers are drawn in face-local coords. On the net, face has rot.
      // Parent mesh is not extra-rotated (we put rot into texture? No.)
      // Parent F rot 0: texture up = +Y = net north. Good if parent hinge isn't rotated in-plane.
      // Child needs in-plane rotation: (child.rot - parent.rot) but also the hinge is already in parent space.
      // After placing along netDir, child's local up (texture +Y) should point toward child's net north.
      // net north in parent space is +Y.
      // child's texture +Y should be rotated by child.rot (CW) from net north.
      mesh.rotation.z = -(c.rot % 4) * (Math.PI / 2);
      hinge.add(mesh);
      hinges[child] = hinge;
      meshes[child] = mesh;

      hinge.userData.fold = foldAxis(netDir);
      return hinge;
    }

    function foldAxis(netDir) {
      // t=1 → 90° so child goes to -Z
      if (netDir === 0) return { axis: "x", ang: -Math.PI / 2 };
      if (netDir === 2) return { axis: "x", ang: Math.PI / 2 };
      if (netDir === 1) return { axis: "y", ang: Math.PI / 2 };
      return { axis: "y", ang: -Math.PI / 2 };
    }

    const root = new THREE.Group();
    const fMesh = makeFaceMesh(stickers.F, exam);
    fMesh.rotation.z = -((layout.F && layout.F.rot) || 0) * (Math.PI / 2);
    root.add(fMesh);
    group.add(root);
    hinges.F = root;
    meshes.F = fMesh;
    root.userData.fold = null;

    const q = ["F"];
    const built = new Set(["F"]);
    while (q.length) {
      const a = q.shift();
      for (const b of tree[a] || []) {
        if (built.has(b)) continue;
        attach(b, a, hinges[a]);
        built.add(b);
        q.push(b);
      }
    }

    function setFold(t) {
      for (const f of FACE_LIST) {
        const h = hinges[f];
        if (!h || !h.userData.fold) continue;
        const { axis, ang } = h.userData.fold;
        h.rotation.x = h.rotation.y = h.rotation.z = 0;
        h.rotation[axis] = ang * t;
      }
    }

    function layoutCenter() {
      const pts = Object.values(layout);
      const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
      return { cx, cy };
    }

    return { group, meshes, setFold, layoutCenter };
  }

  function setupView(el, exam) {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(exam ? 0xf7f1e4 : 0xf3ead8);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
    camera.position.set(2.7, 2.15, 3.6);
    camera.lookAt(0, 0.05, -0.35);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    const light = new THREE.HemisphereLight(0xffffff, 0x887766, 1.15);
    scene.add(light);
    const dir = new THREE.DirectionalLight(0xffffff, 0.55);
    dir.position.set(2, 4, 3);
    scene.add(dir);

    const rig = new THREE.Group();
    scene.add(rig);

    const pack = { scene, camera, renderer, canvas: el, rig, cube: null, rebuild: null, zoom: 1 };
    function frame() {
      if (!pack.cube) return;
      pack.cube.group.position.set(0, 0, 0);
      pack.cube.group.updateWorldMatrix(true, true);
      const box = new THREE.Box3().setFromObject(pack.cube.group);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      if (!isFinite(center.x)) return;
      pack.cube.group.position.copy(center).multiplyScalar(-1);
      const maxDim = Math.max(size.x, size.y, size.z, 1.2);
      const aspect = pack.camera.aspect || 1;
      const fov = (pack.camera.fov * Math.PI) / 180;
      let dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.55 * pack.zoom;
      if (aspect < 1) dist /= aspect;
      pack.camera.position.set(dist * 0.72, dist * 0.52, dist * 0.9);
      pack.camera.lookAt(0, 0, 0);
      pack.camera.near = Math.max(0.05, dist / 30);
      pack.camera.far = dist * 30;
      pack.camera.updateProjectionMatrix();
    }
    function rebuild() {
      if (pack.cube) pack.rig.remove(pack.cube.group);
      pack.cube = buildFoldingCube(state.stickers, state.tree, state.layout, exam);
      pack.rig.add(pack.cube.group);
      pack.cube.setFold(state.fold);
      frame();
    }
    pack.rebuild = rebuild;
    pack.frame = frame;
    rebuild();
    function resize() {
      const w = el.clientWidth || 400;
      const h = el.clientHeight || 360;
      renderer.setSize(w, h, true);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
      if (pack.frame) pack.frame();
    }
    resize();
    new ResizeObserver(resize).observe(el);

    let drag = false, moved = 0, lx = 0, ly = 0;
    el.addEventListener("pointerdown", (e) => {
      drag = true;
      moved = 0;
      lx = e.clientX;
      ly = e.clientY;
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener("pointerup", (e) => {
      drag = false;
      if (moved < 6) pickFace(pack, e);
    });
    el.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - lx;
      const dy = e.clientY - ly;
      moved += Math.abs(dx) + Math.abs(dy);
      lx = e.clientX;
      ly = e.clientY;
      pack.rig.rotation.y += dx * 0.01;
      pack.rig.rotation.x += dy * 0.01;
    });
    el.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        pack.zoom *= e.deltaY > 0 ? 1.08 : 0.92;
        pack.zoom = Math.min(2.4, Math.max(0.45, pack.zoom));
        frame();
      },
      { passive: false }
    );

    function loop() {
      renderer.render(scene, camera);
      pack.raf = requestAnimationFrame(loop);
    }
    loop();
    return pack;
  }

  function pickFace(pack, e) {
    const rect = pack.canvas.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    const ray = new THREE.Raycaster();
    ray.setFromCamera({ x, y }, pack.camera);
    const meshes = Object.values(pack.cube.meshes);
    const hit = ray.intersectObjects(meshes, false)[0];
    if (!hit) return;
    state.selected = hit.object.userData.face;
    highlight();
    renderFaceCard();
  }

  function highlight() {
    if (!lab || !lab.cube) return;
    const sel = state.selected;
    const opp = OPP[sel];
    for (const [f, m] of Object.entries(lab.cube.meshes)) {
      const dim = state.showOnlyOpp && f !== sel && f !== opp;
      m.material.emissive = new THREE.Color(
        f === sel ? 0x224422 : f === opp ? 0x442222 : 0x000000
      );
      m.material.opacity = dim ? 0.18 : 1;
      m.material.transparent = dim;
    }
  }

  function renderFaceCard() {
    const f = state.selected;
    const st = state.stickers[f];
    const card = document.getElementById("face-card");
    if (!card) return;
    card.classList.remove("empty");
    const adj = CYCLE[f].map((n) => NAMES[n]).join(" · ");
    card.innerHTML = `<b>${NAMES[f]} 면</b><br>반대: ${NAMES[OPP[f]]}<br>맞닿음: ${adj}<br>기호: ${st.sym || "없음"} / 회전 ${st.rot * 90}°`;
  }

  function refreshLabCube() {
    if (!lab) return;
    lab.rebuild();
    lab.cube = arguments[0] || lab.scene.children.find(() => true);
    // rebuild replaces cube on rig
    // setupView.rebuild updates pack.cube
    highlight();
  }

  /* ---------- SVG net ---------- */
  function netSVG(layout, stickers, opts = {}) {
    const cells = Object.entries(layout);
    let minx = 9, miny = 9, maxx = -9, maxy = -9;
    for (const [, p] of cells) {
      minx = Math.min(minx, p.x);
      miny = Math.min(miny, p.y);
      maxx = Math.max(maxx, p.x);
      maxy = Math.max(maxy, p.y);
    }
    const S = opts.size || 48;
    const pad = 8;
    const w = (maxx - minx + 1) * S + pad * 2;
    const h = (maxy - miny + 1) * S + pad * 2;
    let body = "";
    for (const [f, p] of cells) {
      const x = pad + (p.x - minx) * S;
      const y = pad + (maxy - p.y) * S;
      const st = stickers[f];
      const fill = opts.exam ? "#fbfaf6" : st.color;
      body += `<g transform="translate(${x},${y})">
        <rect width="${S}" height="${S}" fill="${fill}" stroke="#1c1914" stroke-width="1.6"/>`;
      if (st.sym) {
        const cx = S / 2, cy = S / 2;
        const pull = st.sym === "arrow" || st.sym === "tri" || st.sym === "wifi" ? 0.1 * S : 0;
        const ox = [0, 1, 0, -1][st.edge || 0] * pull;
        const oy = [-1, 0, 1, 0][st.edge || 0] * pull;
        const deg = (st.rot + p.rot) * 90;
        body += `<g transform="translate(${cx},${cy}) rotate(${deg}) translate(${ox},${oy})">${symbolPath(st.sym, S * 0.85, st)}</g>`;
      }
      if (!opts.exam) {
        body += `<text x="4" y="12" font-size="9" fill="#333">${NAMES[f]}</text>`;
      }
      body += `</g>`;
    }
    return `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">${body}</svg>`;
  }

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
    if (kind === "plus") {
      return `<path d="M ${-8 * k} 0 L ${8 * k} 0 M 0 ${-8 * k} L 0 ${8 * k}" fill="none" stroke="#111" stroke-width="${3 * k}"/>`;
    }
    if (kind === "dot") {
      return `<circle r="${6 * k}" fill="#111"/>`;
    }
    if (kind === "letter") {
      const ch = (st && st.mark) || "A";
      return `<text text-anchor="middle" dominant-baseline="central" font-size="${18 * k}" font-weight="700" font-family="Malgun Gothic, sans-serif">${ch}</text>`;
    }
    if (kind === "dice") {
      const n = (st && st.pips) || 1;
      const o = 5.2 * k;
      const map = {
        1: [[0, 0]],
        2: [[-o, -o], [o, o]],
        3: [[-o, -o], [0, 0], [o, o]],
        4: [[-o, -o], [o, -o], [-o, o], [o, o]],
        5: [[-o, -o], [o, -o], [0, 0], [-o, o], [o, o]],
        6: [[-o, -o], [o, -o], [-o, 0], [o, 0], [-o, o], [o, o]],
      };
      return (map[n] || map[1]).map(([x, y]) => `<circle cx="${x}" cy="${y}" r="${2.1 * k}" fill="#111"/>`).join("");
    }
    return `<path d="M 0 ${-10 * k} L ${8 * k} ${8 * k} L ${-8 * k} ${8 * k} Z" fill="#111"/>`;
  }

  function isoCubeSVG(stickers, vis) {
    const [f, u, r] = vis || ["F", "U", "R"];
    const W = 180, H = 160;
    const facePoly = (pts, st) => {
      const fill = st.color || "#fbfaf6";
      let g = `<polygon points="${pts}" fill="${fill}" stroke="#1c1914" stroke-width="1.6"/>`;
      if (st.sym) {
        const xs = pts.split(" ").map((p) => +p.split(",")[0]);
        const ys = pts.split(" ").map((p) => +p.split(",")[1]);
        const cx = xs.reduce((a, b) => a + b, 0) / 4;
        const cy = ys.reduce((a, b) => a + b, 0) / 4;
        g += `<g transform="translate(${cx},${cy}) scale(0.7)">${symbolPath(st.sym, 36, st)}</g>`;
      }
      return g;
    };
    const top = "70,18 130,48 70,78 10,48";
    const front = "10,48 70,78 70,138 10,108";
    const right = "70,78 130,48 130,108 70,138";
    return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
      ${facePoly(top, stickers[u])}
      ${facePoly(front, stickers[f])}
      ${facePoly(right, stickers[r])}
    </svg>`;
  }

  /* ---------- quiz generation ---------- */
  function cloneStickers(s) {
    const o = {};
    for (const f of FACE_LIST) o[f] = { ...s[f] };
    return o;
  }

  function scrambleCube(stickers) {
    // 24 orientations: pick front and up
    const front = FACE_LIST[Math.floor(Math.random() * 6)];
    const ups = CYCLE[front];
    const up = ups[Math.floor(Math.random() * 4)];
    // map spatial slot -> original sticker id
    const map = { F: front, U: up };
    map.B = OPP[front];
    map.D = OPP[up];
    // right = CYCLE[front] after up
    const i = CYCLE[front].indexOf(up);
    map.R = CYCLE[front][(i + 1) % 4];
    map.L = CYCLE[front][(i + 3) % 4];
    const out = {};
    for (const slot of FACE_LIST) {
      const src = stickers[map[slot]];
      out[slot] = { ...src, id: slot, color: COLORS[slot] };
    }
    return out;
  }

  function decorateStickers(type) {
    const stickers = freshStickers();
    for (const f of FACE_LIST) {
      stickers[f].sym = null;
      stickers[f].rot = 0;
      stickers[f].edge = 0;
    }
    const pairs = [
      ["F", "U"],
      ["F", "R"],
      ["U", "R"],
    ];
    const [a, b] = pairs[Math.floor(Math.random() * pairs.length)];
    const sA = sideOfNeighbor(a, b);
    const sB = sideOfNeighbor(b, a);
    if (type === "dice") {
      const pip = { F: 1, B: 6, U: 2, D: 5, L: 3, R: 4 };
      for (const f of FACE_LIST) {
        stickers[f].sym = "dice";
        stickers[f].pips = pip[f];
      }
    } else if (type === "opp") {
      const marks = { F: "A", B: "A", U: "B", D: "B", L: "C", R: "C" };
      for (const f of FACE_LIST) {
        stickers[f].sym = "letter";
        stickers[f].mark = marks[f];
      }
    } else if (type === "invalid") {
      stickers.F.sym = "letter";
      stickers.F.mark = "가";
      stickers.U.sym = "letter";
      stickers.U.mark = "나";
      stickers.R.sym = "letter";
      stickers.R.mark = "다";
    } else {
      const kinds = ["arrow", "tri", "letter", "plus", "dot"];
      const kind = kinds[Math.floor(Math.random() * kinds.length)];
      stickers[a].sym = kind;
      stickers[b].sym = kind;
      stickers[a].rot = sA;
      stickers[a].edge = sA;
      stickers[b].rot = sB;
      stickers[b].edge = sB;
      if (kind === "letter") {
        stickers[a].mark = "P";
        stickers[b].mark = "Q";
      }
    }
    return { stickers, a, b };
  }

  function makeProblem(level, type) {
    type = type || (document.getElementById("q-type") || {}).value || "net";
    const dec = decorateStickers(type);
    let stickers = dec.stickers;
    const treePack = ALL_NETS[Math.floor(Math.random() * ALL_NETS.length)];
    const layout = treePack.layout;
    const tree = treePack.children;

    const correct = { layout, stickers: cloneStickers(stickers), tree, ok: true };

    const opts = [correct];
    // distractor: rotate one symbol 180
    const d1 = cloneStickers(stickers);
    const marked = FACE_LIST.filter((f) => d1[f].sym);
    if (marked.length) {
      const f = marked[0];
      d1[f] = { ...d1[f], rot: (d1[f].rot + 2) % 4, edge: (d1[f].edge + 2) % 4 };
      opts.push({ layout, stickers: d1, tree, ok: false, why: `${NAMES[f]} 면 기호가 반대 방향을 향한다. 공유 모서리를 봐야 한다.` });
    }
    // distractor: rotate 90
    const d2 = cloneStickers(stickers);
    if (marked.length) {
      const f = marked[marked.length - 1];
      d2[f] = { ...d2[f], rot: (d2[f].rot + 1) % 4, edge: (d2[f].edge + 1) % 4 };
      opts.push({ layout, stickers: d2, tree, ok: false, why: `${NAMES[f]} 면 기호가 90° 돌아가 있다. 입체에서 기호가 가리키는 변과 다르다.` });
    }
    // distractor: different net that separates the two symbol faces
    const d3pack = ALL_NETS[Math.floor(Math.random() * ALL_NETS.length)];
    const d3s = cloneStickers(stickers);
    opts.push({
      layout: d3pack.layout,
      stickers: d3s,
      tree: d3pack.children,
      ok: false,
      why: "전개도 모양은 달라도 된다. 다만 기호 두 면의 맞닿음·방향이 입체와 같아야 한다. 이 선지는 방향 또는 맞닿음이 깨졌다.",
    });
    // if d3 accidentally correct (same geometry), mutate a symbol
    // safer: always twist
    const fTwist = marked[0] || "F";
    d3s[fTwist] = { ...d3s[fTwist], rot: (d3s[fTwist].rot + 2) % 4 };

    // distractor: put opposite faces adjacent conceptually by swapping a sticker onto opposite
    const d4 = cloneStickers(stickers);
    if (marked.length >= 2) {
      const x = marked[0], y = marked[1];
      const tmp = d4[x].sym;
      d4[x] = { ...d4[x], sym: d4[OPP[x]].sym };
      d4[OPP[x]] = { ...d4[OPP[x]], sym: tmp };
      opts.push({ layout, stickers: d4, tree, ok: false, why: "기호가 반대 면으로 옮겨졌다. 입체에서 보이는 두 면은 맞닿아 있다." });
    } else {
      const d4pack = ALL_NETS[Math.floor(Math.random() * ALL_NETS.length)];
      const s = cloneStickers(stickers);
      if (s.F.sym) s.F.rot = (s.F.rot + 3) % 4;
      opts.push({ layout: d4pack.layout, stickers: s, tree: d4pack.children, ok: false, why: "기호 방향이 입체와 다르다." });
    }

    if (type === "opp") {
      const qf = ["F", "U", "L"][Math.floor(Math.random() * 3)];
      const five = shuffle([
        { text: `${NAMES[OPP[qf]]} 면`, ok: true, why: "" },
        { text: `${NAMES[CYCLE[qf][0]]} 면`, ok: false, why: "맞닿은 면이다. 반대가 아니다." },
        { text: `${NAMES[CYCLE[qf][1]]} 면`, ok: false, why: "옆면이다." },
        { text: `${NAMES[CYCLE[qf][2]]} 면`, ok: false, why: "옆면이다." },
        { text: "세 면 모두 맞닿는다", ok: false, why: "한 면의 반대는 하나뿐이다." },
      ]).slice(0, 5);
      return { stickers, tree, layout, options: five, level, type, prompt: `${NAMES[qf]} 면의 반대 면은?`, kind: "text", focus: qf };
    }
    if (type === "invalid") {
      const goods = shuffle(ALL_NETS.slice()).slice(0, 4).map((n) => ({
        layout: n.layout,
        stickers,
        tree: n.children,
        ok: false,
        why: "이건 접을 수 있다. 5칸이 일렬이거나 반대 면이 맞닿으면 불가능하다.",
      }));
      const badLay = {
        F: { x: 0, y: 0, rot: 0 },
        R: { x: 1, y: 0, rot: 0 },
        B: { x: 2, y: 0, rot: 0 },
        L: { x: 3, y: 0, rot: 0 },
        U: { x: 4, y: 0, rot: 0 },
        D: { x: 2, y: -1, rot: 0 },
      };
      goods.push({ layout: badLay, stickers, tree, ok: true, why: "" });
      return {
        stickers,
        tree,
        layout,
        options: shuffle(goods),
        level,
        type,
        prompt: "접어서 정육면체가 될 수 없는 전개도는?",
        kind: "net",
      };
    }
    if (type === "cube") {
      const views = [
        { vis: ["F", "U", "R"], ok: true },
        { vis: ["F", "U", "L"], ok: false, why: "왼/오가 바뀌면 거울이다." },
        { vis: ["B", "U", "R"], ok: false, why: "앞면이 아니다." },
        { vis: ["F", "D", "R"], ok: false, why: "위아래가 뒤집혔다." },
        { vis: ["R", "U", "F"], ok: false, why: "돌린 각도가 입체와 다르다." },
      ];
      const five = views.map((v) => ({
        ...v,
        stickers,
        layout,
        tree,
        iso: v.vis,
      }));
      shuffle(five);
      return { stickers, tree, layout, options: five, level, type, prompt: "이 전개도를 접으면 어느 겨냥도가 되나?", kind: "iso" };
    }

    const five = opts.slice(0, 5);
    shuffle(five);
    return { stickers, tree, layout, options: five, level, type, prompt: "위의 겨냥도를 나타내는 전개도로 옳은 것은?", kind: "net" };
  }

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function renderQuiz() {
    const p = state.quiz;
    document.getElementById("q-title").textContent = p.prompt || "위의 겨냥도를 나타내는 전개도로 옳은 것은?";
    const box = document.getElementById("choices");
    box.innerHTML = "";
    p.options.forEach((opt, i) => {
      const d = document.createElement("button");
      d.className = "choice";
      let body = "";
      if (p.kind === "text") body = `<div style="padding:18px;font-size:18px;font-weight:700">${opt.text}</div>`;
      else if (p.kind === "iso") body = isoCubeSVG(p.stickers, opt.iso);
      else body = netSVG(opt.layout, opt.stickers || p.stickers, { exam: true, size: 52 });
      d.innerHTML = `<div class="num">${["①", "②", "③", "④", "⑤"][i]}</div>${body}`;
      d.addEventListener("click", () => {
        state.picked = i;
        [...box.children].forEach((c) => c.classList.remove("on"));
        d.classList.add("on");
      });
      box.appendChild(d);
    });
    document.getElementById("explain").hidden = true;
    document.getElementById("btn-why").disabled = p.kind === "text";
    const labels = { net: "겨냥→전개", cube: "전개→겨냥", opp: "반대 면", invalid: "불가능", dice: "주사위" };
    document.getElementById("q-diff").textContent = labels[p.type] || "혼합";

    // 3D
    const el = document.getElementById("quiz-canvas");
    if (quiz3d) {
      cancelAnimationFrame(quiz3d.raf);
      el.replaceChildren();
    }
    const saved = { fold: state.fold, tree: state.tree, stickers: state.stickers, layout: state.layout };
    const cross = crossTree();
    const showNetPrompt = p.kind === "iso";
    state.fold = showNetPrompt ? 0 : 1;
    state.tree = showNetPrompt ? p.tree : cross.children;
    state.layout = showNetPrompt ? p.layout : cross.layout;
    state.stickers = p.stickers;
    quiz3d = setupView(el, false);
    quiz3d.cube.setFold(state.fold);
    quiz3d.frame();
    state.fold = saved.fold;
    state.tree = saved.tree;
    state.stickers = saved.stickers;
    state.layout = saved.layout;
  }

  function checkQuiz() {
    const p = state.quiz;
    if (state.picked == null) return;
    const box = document.getElementById("choices");
    let good = false;
    p.options.forEach((opt, i) => {
      const el = box.children[i];
      if (opt.ok) el.classList.add("ok");
      if (i === state.picked && !opt.ok) el.classList.add("bad");
      if (i === state.picked && opt.ok) good = true;
    });
    const exp = document.getElementById("explain");
    exp.hidden = false;
    if (good) {
      state.stats.ok += 1;
      state.stats.streak += 1;
      exp.textContent = "맞았다. 보이는 두 기호가 공유하는 변을 그대로 전개도에 옮기면 된다.";
    } else {
      state.stats.streak = 0;
      const w = p.options[state.picked];
      exp.textContent = "틀렸다. " + (w.why || "공유 모서리와 기호 방향을 다시 보자.");
    }
    saveStats();
    document.getElementById("btn-why").disabled = false;
  }

  function whyQuiz() {
    // show correct net folding in quiz canvas
    const p = state.quiz;
    const correct = p.options.find((o) => o.ok);
    const el = document.getElementById("quiz-canvas");
    if (quiz3d) {
      cancelAnimationFrame(quiz3d.raf);
      el.replaceChildren();
    }
    state.stickers = correct.stickers;
    state.tree = correct.tree;
    state.layout = correct.layout;
    state.fold = 0;
    quiz3d = setupView(el, false);
    quiz3d.cube.setFold(0);
    quiz3d.frame();
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / 1800);
      const e = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
      state.fold = e;
      quiz3d.cube.setFold(e);
      quiz3d.frame();
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    document.getElementById("explain").textContent =
      "펼친 상태에서 접히는 걸 봐. 기호 두 개가 한 모서리로 모이는지 확인하면 된다.";
  }

  /* ---------- drill ---------- */
  function nextDrill() {
    const type = Math.random() < 0.5 ? "opp" : "adj";
    const f = FACE_LIST[Math.floor(Math.random() * 6)];
    const qel = document.getElementById("drill-q");
    const box = document.getElementById("drill-opts");
    box.innerHTML = "";
    if (type === "opp") {
      qel.textContent = `${NAMES[f]} 면의 반대 면은?`;
      const opts = shuffle([OPP[f], ...shuffle(FACE_LIST.filter((x) => x !== f && x !== OPP[f])).slice(0, 3)]);
      opts.forEach((id) => {
        const b = document.createElement("button");
        b.className = "choice";
        b.textContent = NAMES[id];
        b.onclick = () => drillAnswer(id === OPP[f], b);
        box.appendChild(b);
      });
    } else {
      const n = CYCLE[f][Math.floor(Math.random() * 4)];
      qel.textContent = `${NAMES[f]} 면과 ${NAMES[n]} 면은?`;
      [
        ["맞닿아 있다", true],
        ["반대 면이다", false],
        ["절대 한 꼭짓점에 못 만난다", false],
      ].forEach(([t, ok]) => {
        const b = document.createElement("button");
        b.className = "choice";
        b.textContent = t;
        b.onclick = () => drillAnswer(ok, b);
        box.appendChild(b);
      });
    }
  }
  function drillAnswer(ok, btn) {
    if (!state.drill || !state.drill.on) return;
    btn.classList.add(ok ? "ok" : "bad");
    if (ok) {
      state.drill.score += 1;
      state.stats.ok += 1;
      state.stats.streak += 1;
    } else {
      state.stats.streak = 0;
    }
    document.getElementById("drill-score").textContent = `이번 라운드 ${state.drill.score}`;
    saveStats();
    setTimeout(nextDrill, 220);
  }

  /* ---------- wiring ---------- */
  function setMode(m) {
    state.mode = m;
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("on"));
    document.getElementById("view-" + m).classList.add("on");
    if (m === "quiz" && !state.quiz) {
      state.quiz = makeProblem(1);
      renderQuiz();
    }
    if (m === "lab" && lab) {
      lab.frame();
    }
  }

  function initLab() {
    state.stickers = freshStickers();
    applyNet((ALL_NETS.find((n) => n.type === "십자가") || ALL_NETS[0]).name);
    const el = document.getElementById("lab-canvas");
    lab = setupView(el, false);
    highlight();
    renderFaceCard();
    paintLabNet();

    const sel = document.getElementById("net-select");
    sel.innerHTML = ALL_NETS.map((n) => `<option>${n.name}</option>`).join("");
    const firstCross = ALL_NETS.find((n) => n.type === "십자가");
    if (firstCross) sel.value = firstCross.name;
    sel.onchange = () => {
      applyNet(sel.value);
      lab.rebuild();
      highlight();
      paintLabNet();
    };
    const fold = document.getElementById("fold");
    fold.oninput = () => {
      state.fold = Number(fold.value) / 100;
      lab.cube.setFold(state.fold);
      lab.frame();
    };
    document.getElementById("btn-flat").onclick = () => {
      fold.value = 0;
      state.fold = 0;
      lab.cube.setFold(0);
      lab.frame();
    };
    document.getElementById("btn-cube").onclick = () => {
      fold.value = 100;
      state.fold = 1;
      lab.cube.setFold(1);
      lab.frame();
    };
    document.getElementById("btn-anim").onclick = () => {
      const from = state.fold;
      const to = from > 0.5 ? 0 : 1;
      const start = performance.now();
      const tick = (now) => {
        const k = Math.min(1, (now - start) / 1400);
        const e = k < 0.5 ? 2 * k * k : -1 + (4 - 2 * k) * k;
        state.fold = from + (to - from) * e;
        fold.value = String(Math.round(state.fold * 100));
        lab.cube.setFold(state.fold);
        lab.frame();
        if (k < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };
    document.getElementById("btn-reset").onclick = () => {
      lab.rig.rotation.set(0, 0, 0);
      lab.zoom = 1;
      lab.frame();
    };
    document.getElementById("sym-btns").onclick = (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      const st = state.stickers[state.selected];
      st.sym = b.dataset.sym === "none" ? null : b.dataset.sym;
      lab.rebuild();
      highlight();
      renderFaceCard();
      paintLabNet();
    };
    document.getElementById("btn-rot-cw").onclick = () => {
      const st = state.stickers[state.selected];
      st.rot = (st.rot + 1) % 4;
      st.edge = (st.edge + 1) % 4;
      lab.rebuild();
      highlight();
      renderFaceCard();
      paintLabNet();
    };
    document.getElementById("btn-rot-ccw").onclick = () => {
      const st = state.stickers[state.selected];
      st.rot = (st.rot + 3) % 4;
      st.edge = (st.edge + 3) % 4;
      lab.rebuild();
      highlight();
      renderFaceCard();
      paintLabNet();
    };
    document.getElementById("btn-nudge").onclick = () => {
      const st = state.stickers[state.selected];
      st.edge = st.rot;
      lab.rebuild();
      highlight();
      paintLabNet();
    };
    document.getElementById("btn-opp").onclick = () => {
      state.showOnlyOpp = !state.showOnlyOpp;
      highlight();
    };
  }

  document.getElementById("tabs").onclick = (e) => {
    const b = e.target.closest("button");
    if (b) setMode(b.dataset.mode);
  };
  document.getElementById("btn-check").onclick = checkQuiz;
  document.getElementById("btn-next").onclick = () => {
    const lv = state.stats.streak >= 5 ? 2 : 1;
    state.picked = null;
    state.quiz = makeProblem(lv, (document.getElementById("q-type") || {}).value);
    renderQuiz();
  };
  const qType = document.getElementById("q-type");
  if (qType) {
    qType.onchange = () => {
      state.picked = null;
      state.quiz = makeProblem(1, qType.value);
      renderQuiz();
    };
  }
  document.getElementById("btn-why").onclick = whyQuiz;
  document.getElementById("btn-drill").onclick = () => {
    if (state.drill && state.drill.on) return;
    state.drill = { on: true, score: 0, left: 60 };
    document.getElementById("drill-score").textContent = "이번 라운드 0";
    nextDrill();
    const t = setInterval(() => {
      state.drill.left -= 1;
      document.getElementById("timer").textContent = state.drill.left;
      if (state.drill.left <= 0) {
        clearInterval(t);
        state.drill.on = false;
        document.getElementById("drill-q").textContent = `끝. ${state.drill.score}개.`;
      }
    }, 1000);
  };

  const demo = document.getElementById("demo-opp");
  if (demo) {
    const t = crossTree();
    const s = freshStickers();
    demo.innerHTML = netSVG(t.layout, s, { size: 36 });
  }

  function paintLabNet() {
    const el = document.getElementById("lab-net");
    if (!el || !state.layout) return;
    el.innerHTML = netSVG(state.layout, state.stickers, { size: 46 });
  }

  function renderNetGallery() {
    const grid = document.getElementById("net-grid");
    if (!grid) return;
    const blank = {};
    for (const f of FACE_LIST) blank[f] = { id: f, color: COLORS[f], sym: null, rot: 0, edge: 0 };
    const cnt = document.getElementById("net-count");
    if (cnt) cnt.innerHTML = `지금 모은 유효 전개도 <strong>${ALL_NETS.length}개</strong>. 접으면 다 같은 정육면체다. 클릭하면 실험실에서 접어 볼 수 있다.`;
    grid.innerHTML = "";
    ALL_NETS.forEach((n, i) => {
      const card = document.createElement("button");
      card.className = "net-card";
      card.innerHTML = `<div class="nm">${i + 1}. ${n.name}</div>${netSVG(n.layout, blank, { size: 34 })}`;
      card.onclick = () => {
        applyNet(n.name);
        if (lab) {
          lab.rebuild();
          highlight();
          paintLabNet();
          const sel = document.getElementById("net-select");
          if (sel) sel.value = n.name;
        }
        setMode("lab");
      };
      grid.appendChild(card);
    });
  }

  loadStats();
  applyNet((ALL_NETS.find((n) => n.type === "십자가") || ALL_NETS[0]).name);
  initLab();
  renderNetGallery();
})();
