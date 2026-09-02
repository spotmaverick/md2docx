/* Md2docs 前端逻辑 */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const state = {
  files: [],           // {path} 磁盘文件 或 {name, content} 拖入文件（未定位到源目录）
  formats: new Set(["docx"]),
  workdir: "",
  caps: {},
  browse: { path: "", kind: "files", selected: new Set(), drives: [] },
};

const FORMAT_META = {
  docx: { tag: "DOCX", desc: "Word 2007+ 原生" },
  doc:  { tag: "DOC",  desc: "Word 97-2003" },
  wps:  { tag: "WPS",  desc: "WPS 文字" },
  txt:  { tag: "TXT",  desc: "纯文本" },
};

/* ------------------------------------------------------------------ */
async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  const j = await r.json();
  if (!r.ok || j.ok === false) {
    throw new Error(j.error || j.message || "请求失败");
  }
  return j;
}

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 2600);
}

function fmtSize(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), 3);
  return (n / Math.pow(1024, i)).toFixed(i ? 1 : 0) + " " + u[i];
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ---------------------------- 初始化 ---------------------------- */
async function init() {
  try {
    const cfg = await api("/api/config");
    state.workdir = cfg.workdir;
    state.caps = cfg.caps || {};
    state.defaultOut = cfg.default_out || "";
    // 默认「与源文件相同」：输入框禁用，显示源目录（无源文件则为空）
    $("#outDir").disabled = true;
    $("#btnPickDir").disabled = true;
    renderBadges();
    renderFormats(cfg.formats);
    renderNativeHint();
    updateOutDirDisplay();
  } catch (e) {
    toast("无法连接本地服务：" + e.message, "err");
  }
}

/* 浏览添加的源文件所在目录；无则返回空串 */
function sourceDirOf(files) {
  const disk = files.filter((f) => f.path);
  if (!disk.length) return "";
  const dirs = new Set(disk.map((f) => f.path.replace(/[\\/][^\\/]*$/, "")));
  return dirs.size === 1
    ? disk[0].path.replace(/[\\/][^\\/]*$/, "")
    : "（多个文件位于不同目录）";
}

/* 输出目录输入框随模式联动：
   「指定目录」→ 显示/预填 default_out；「与源文件相同」→ 显示源文件所在目录，无则空 */
let _lastSameValue = "";
function updateOutDirDisplay() {
  const mode = $$('input[name="outMode"]').find((r) => r.checked).value;
  const el = $("#outDir");
  const sum = $("#foldOutDirSum");
  if (mode === "same") {
    _lastSameValue = sourceDirOf(state.files);
    el.value = _lastSameValue;
    if (sum) {
      sum.textContent = _lastSameValue
        ? "与源文件相同：" + _lastSameValue
        : "与源文件相同";
    }
  } else {
    // 切回「指定目录」：若输入框还是刚才自动显示的源目录，恢复默认输出目录
    if (!el.value || el.value === _lastSameValue) el.value = state.defaultOut || "";
    if (sum) sum.textContent = el.value ? "指定目录：" + el.value : "指定目录（未选择）";
  }
}

function renderBadges() {
  const c = state.caps;
  const items = [
    { on: c.word, text: c.word ? "Word 已就绪" : "未检测到 Word" },
    { on: c.wps, text: c.wps ? "WPS 已就绪" : "未检测到 WPS" },
  ];
  $("#capBadges").innerHTML = items
    .map((i) => `<span class="badge ${i.on ? "on" : ""}">${i.on ? "● " : "○ "}${i.text}</span>`)
    .join("");
}

function renderNativeHint() {
  const c = state.caps;
  const enabled = Boolean(c.word || c.wps);
  const nm = $("#nativeMode");
  if (nm) {
    nm.disabled = !enabled;
    if (!enabled) nm.checked = false;
  }
  let msg;
  if (enabled) {
    const apps = [c.word ? "Word" : "", c.wps ? "WPS" : ""].filter(Boolean).join(" / ");
    msg = `已检测到本机 ${apps}。开启后 .doc / .wps 会先生成 DOCX 再调用 ${apps} 另存为原生二进制格式（稍慢）；关闭时使用内置 RTF 引擎，秒出、格式同样完整。`;
  } else {
    msg = "本机未检测到 Word / WPS，该选项不可用；.doc 与 .wps 将用内置 RTF 引擎生成（Word、WPS、LibreOffice 均可直接打开，完整保留样式）。";
  }
  const hint = $("#nativeHint");
  if (hint) hint.textContent = msg;
  updateNativeSum();
}

function updateNativeSum() {
  const nm = $("#nativeMode");
  const sum = $("#foldNativeSum");
  if (!sum) return;
  const on = !!(nm && nm.checked && !nm.disabled);
  sum.textContent = on ? "高质量模式 · 本机 Office 原生格式" : "RTF 兼容格式";
}

function renderFormats(list) {
  const order = ["docx", "doc", "wps", "txt"];
  const meta = list.map((f) => ({ id: f.id, label: f.label, ext: f.ext }));
  const sorted = order.map((id) => meta.find((m) => m.id === id)).filter(Boolean)
    .concat(meta.filter((m) => !order.includes(m.id)));

  $("#formats").innerHTML = sorted.map((f) => {
    const on = state.formats.has(f.id) ? "active" : "";
    const m = FORMAT_META[f.id] || { tag: f.id.toUpperCase(), desc: "" };
    return `<label class="fmt ${on}" data-id="${f.id}">
      <input type="checkbox" ${state.formats.has(f.id) ? "checked" : ""}>
      <span class="fmt-ic ${f.id}">${m.tag}</span>
      <span class="fmt-txt">
        <span class="fmt-name">${esc(f.label)}</span><br>
        <span class="fmt-desc">${esc(m.desc)}</span>
      </span>
    </label>`;
  }).join("");

  $$(".fmt").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      const id = el.dataset.id;
      if (state.formats.has(id)) state.formats.delete(id);
      else state.formats.add(id);
      el.classList.toggle("active");
      el.querySelector("input").checked = state.formats.has(id);
      syncTxtOptions();
    });
  });
  syncTxtOptions();
}

/* TXT 格式勾选时自动展开 TXT 选项，取消勾选自动收起 */
function syncTxtOptions() {
  const on = state.formats.has("txt");
  const fold = $("#foldTxt");
  const tag = $("#foldTxtTag");
  if (fold) setFold(fold, on);
  if (tag) {
    tag.textContent = on ? "已选 TXT" : "未选 TXT";
    tag.classList.toggle("on", on);
  }
}

/* 折叠开合：open 为 true/false/null（null 表示切换） */
function setFold(foldEl, open) {
  const head = foldEl ? foldEl.querySelector(".fold-head") : null;
  const next = (open == null) ? !foldEl.classList.contains("open") : !!open;
  foldEl.classList.toggle("open", next);
  if (head) head.setAttribute("aria-expanded", next ? "true" : "false");
  return next;
}

function toggleFold(id) {
  const el = $("#fold" + id);
  if (el) setFold(el, null);
}

/* ---------------------------- 文件列表 ---------------------------- */
function addPaths(paths) {
  let added = 0;
  for (const p of paths) {
    if (state.files.some((f) => f.path === p)) continue;
    state.files.push({ path: p, name: p.split(/[\\/]/).pop() });
    added++;
  }
  renderFiles();
  updateOutDirDisplay();
  if (added) toast(`已添加 ${added} 个文件`);
}

function renderFiles() {
  const ul = $("#fileList");
  const empty = $("#fileEmpty");
  empty.style.display = state.files.length ? "none" : "block";
  ul.innerHTML = state.files.map((f, i) => {
    const src = f.path || (f.dropped
      ? "（拖入，未能自动定位源目录）" : "");
    return `<li class="file-item">
      <span class="fi-name" title="${esc(src)}">${esc(f.name)}</span>
      ${f.dropped ? '<span class="tag">拖入</span>' : ""}
      <span class="fi-path" title="${esc(src)}">${esc(src)}</span>
      <button class="fi-del" data-i="${i}" title="移除">✕</button>
    </li>`;
  }).join("");
  ul.querySelectorAll(".fi-del").forEach((b) => {
    b.addEventListener("click", () => {
      state.files.splice(Number(b.dataset.i), 1);
      renderFiles();
      updateOutDirDisplay();
    });
  });
}

/* ---------------------------- 拖放（自动定位源目录） ---------------------------- */
function initDrop() {
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", async (e) => {
    const files = Array.from(e.dataTransfer.files || []);
    if (!files.length) return;
    let ok = 0, located = 0;
    for (const f of files) {
      const low = f.name.toLowerCase();
      if (!low.endsWith(".md") && !low.endsWith(".markdown")) continue;
      try {
        const text = await f.text();
        // 自动定位：按文件名在文件资源管理器当前打开的目录里找同名文件
        let realPath = "";
        try {
          const r = await api("/api/locate", { name: f.name });
          realPath = (r && r.path) || "";
        } catch (err) { /* 定位失败则按内存文件处理 */ }
        if (realPath) {
          if (state.files.some((x) => x.path === realPath)) continue;
          state.files.push({ path: realPath, name: realPath.split(/[\\/]/).pop() });
          located++;
        } else {
          state.files.push({ name: f.name, content: text, dropped: true });
        }
        ok++;
      } catch (err) {
        toast(f.name + "：" + err.message, "err");
      }
    }
    renderFiles();
    updateOutDirDisplay();
    if (ok) {
      toast(located === ok
        ? `已添加 ${ok} 个文件，源目录已自动定位`
        : `已添加 ${ok} 个文件（${located} 个已定位源目录）`);
    }
  });
}

/* ---------------------------- 浏览弹窗 ---------------------------- */
function openBrowse(kind) {
  state.browse.kind = kind;
  state.browse.selected = new Set();
  state.browse.path = "";
  $("#modalTitle").textContent = kind === "files" ? "选择 Markdown 文件" : "选择输出目录";
  $("#btnNewFolder").style.display = kind === "dirs" ? "" : "none";
  $("#modal").classList.remove("hidden");
  loadBrowse(state.workdir && kind === "files" ? state.workdir : "");
}

async function loadBrowse(path) {
  const list = $("#browserList");
  list.innerHTML = '<div class="brow-empty">加载中…</div>';
  try {
    const j = await api(`/api/browse?path=${encodeURIComponent(path)}&kind=${state.browse.kind}`);
    state.browse.path = j.path || "";
    state.browse.drives = j.drives || [];
    renderDrives();
    renderCrumb(j.path || "", j.parent || "");
    if (!j.path) {
      list.innerHTML = '<div class="brow-empty">请选择一个驱动器</div>';
      $("#modalInfo").textContent = "";
      return;
    }
    if (!j.entries.length) {
      list.innerHTML = '<div class="brow-empty">这个文件夹里没有可显示的内容</div>';
    } else {
      list.innerHTML = j.entries.map((e) => {
        const sel = state.browse.selected.has(e.path) ? "sel" : "";
        const icon = e.is_dir ? "📁" : "📄";
        const meta = e.is_dir ? "" : fmtSize(e.size);
        return `<div class="brow ${sel}" data-path="${esc(e.path)}" data-dir="${e.is_dir ? 1 : 0}">
          <span class="bi">${icon}</span>
          <span class="bn">${esc(e.name)}</span>
          <span class="bm">${meta}</span>
        </div>`;
      }).join("");
      list.querySelectorAll(".brow").forEach((el) => {
        el.addEventListener("click", () => onRowClick(el));
        el.addEventListener("dblclick", () => {
          if (el.dataset.dir === "1") loadBrowse(el.dataset.path);
          else { state.browse.selected = new Set([el.dataset.path]); confirmBrowse(); }
        });
      });
    }
    $("#modalInfo").textContent = j.path || "";
  } catch (e) {
    list.innerHTML = '<div class="brow-empty">' + esc(e.message) + "</div>";
  }
}

function onRowClick(el) {
  const p = el.dataset.path;
  const isDir = el.dataset.dir === "1";
  if (state.browse.kind === "dirs") {
    state.browse.selected = new Set([p]);
    $$(".brow").forEach((n) => n.classList.toggle("sel", n.dataset.path === p));
  } else if (isDir) {
    loadBrowse(p);
  } else {
    if (state.browse.selected.has(p)) state.browse.selected.delete(p);
    else state.browse.selected.add(p);
    el.classList.toggle("sel");
  }
}

function renderDrives() {
  $("#driveBar").innerHTML = state.browse.drives
    .map((d) => `<button class="drive" data-d="${esc(d)}">${esc(d)}</button>`).join("");
  $("#driveBar").querySelectorAll(".drive").forEach((b) => {
    b.addEventListener("click", () => loadBrowse(b.dataset.d));
  });
}

function renderCrumb(path, parent) {
  if (!path) { $("#crumb").innerHTML = "我的电脑"; return; }
  const parts = path.split(/[\\/]/).filter(Boolean);
  let acc = "";
  const segs = [];
  parts.forEach((p, i) => {
    acc = p.endsWith(":") ? p + "\\" : (acc ? acc + "\\" + p : p);
    if (!acc.includes(":")) acc = path.split(/[\\/]/)[0] + acc;
    const last = i === parts.length - 1;
    segs.push(last ? `<b>${esc(p)}</b>` : `<a data-p="${esc(acc)}">${esc(p)}</a>`);
  });
  $("#crumb").innerHTML = `<a data-p="">我的电脑</a> › ` + segs.join(" › ");
  $("#crumb").querySelectorAll("a").forEach((a) => {
    a.addEventListener("click", () => loadBrowse(a.dataset.p));
  });
}

function confirmBrowse() {
  const sel = Array.from(state.browse.selected);
  if (!sel.length) {
    if (state.browse.kind === "dirs" && state.browse.path) {
      sel.push(state.browse.path);
    } else {
      toast("请先选择内容"); return;
    }
  }
  // 定位模式已取消，改为拖入时自动定位：文件选择一律走新增
  if (state.browse.kind === "files") addPaths(sel);
  else {
    $("#outDir").value = sel[0];
    // 选定目录后自动切换到“指定目录”模式，避免仍写到源文件目录
    const custom = $$('input[name="outMode"]').find((r) => r.value === "custom");
    if (custom && !custom.checked) {
      custom.checked = true;
      custom.dispatchEvent(new Event("change"));
    }
  }
  $("#modal").classList.add("hidden");
}

/* ---------------------------- 转换 ---------------------------- */
async function runConvert() {
  if (!state.files.length) { toast("请先添加 Markdown 文件", "err"); return; }
  if (!state.formats.size) { toast("请选择至少一种输出格式", "err"); return; }

  const outMode = $$('input[name="outMode"]').find((r) => r.checked).value;
  const outDir = outMode === "same" ? "" : $("#outDir").value.trim();

  // 「与源文件相同」必须严格生效：只有拖入（无源目录）的文件才无法使用该模式，
  // 此时明确提示（可点列表里的「定位源文件」补上磁盘位置），绝不擅自切换输出位置
  if (outMode === "same") {
    const dropped = state.files.filter((f) => f.dropped);
    const disk = state.files.filter((f) => !f.dropped);
    if (dropped.length) {
      const fix = dropped.length === 1
        ? "请点击文件列表中的「定位源文件」，选择它在磁盘上的位置"
        : `请先为 ${dropped.length} 个拖入的文件点击「定位源文件」`;
      if (!disk.length) {
        toast(`拖入的文件没有源目录（${fix}），或改用「指定目录」`, "err");
      } else {
        toast(`浏览添加的文件将输出到各自源目录；${dropped.length} 个拖入的文件没有源目录（${fix}），或改用「指定目录」`, "err");
      }
      return;
    }
  }
  if (outMode === "custom" && !outDir) { toast("请选择输出目录", "err"); return; }

  const btn = $("#btnRun");
  const prog = $("#progress");
  btn.disabled = true;
  prog.classList.add("show");
  prog.querySelector(".bar").style.width = "25%";
  $("#progressText").textContent = "转换中…";
  $("#results").innerHTML = "";

  try {
    const files = state.files.map((f) =>
      f.path ? { path: f.path } : { name: f.name, content: f.content });
    const j = await api("/api/convert", {
      files: files,
      formats: Array.from(state.formats),
      out_dir: outDir,
      native: $("#nativeMode").checked && !$("#nativeMode").disabled,
      txt_mode: $$('input[name="txtMode"]').find((r) => r.checked).value,
      txt_encoding: $("#txtEnc").value,
      overwrite: true,
    });
    prog.querySelector(".bar").style.width = "100%";
    renderResults(j);
    const ok = j.results.filter((r) => r.ok).length;
    $("#progressText").textContent = `完成 ${ok} / ${j.results.length}`;
    toast(`转换完成：${ok} 个文件`, ok ? "ok" : "err");
  } catch (e) {
    $("#progressText").textContent = "失败";
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    setTimeout(() => prog.classList.remove("show"), 900);
  }
}

function renderResults(j) {
  const box = $("#results");
  if (!j.results.length) { box.innerHTML = ""; return; }

  const dirs = (j.out_dirs || []).filter(Boolean);
  const head = document.createElement("div");
  head.className = "res-head";
  head.innerHTML = `<span>共 ${j.results.length} 项</span>`;
  if (dirs.length) {
    const b = document.createElement("button");
    b.className = "btn-soft sm";
    b.textContent = "打开输出文件夹";
    b.addEventListener("click", () => api("/api/open", { path: dirs[0] }));
    head.appendChild(b);
  }
  box.appendChild(head);

  for (const r of j.results) {
    const el = document.createElement("div");
    el.className = "res " + (r.ok ? "ok" : "bad");
    const title = r.ok
      ? `${esc(r.name)} → .${esc(r.fmt)}`
      : `${esc(r.name)}${r.fmt ? " → ." + esc(r.fmt) : ""}`;
    const sub = r.ok
      ? `${esc(r.target)} · ${fmtSize(r.size)} · ${esc(r.engine)}`
      : esc(r.message || "转换失败");
    const warn = (r.warnings || []).length
      ? `<div class="res-warn">⚠ ${esc(r.warnings.join("；"))}</div>` : "";
    el.innerHTML = `<span class="dot"></span>
      <div class="res-main">
        <div class="res-title">${title}</div>
        <div class="res-sub">${sub}</div>
        ${warn}
      </div>`;
    if (r.ok) {
      const acts = document.createElement("div");
      acts.className = "res-actions";
      const dir = String(r.target).replace(/[\\/][^\\/]*$/, "");
      const b = document.createElement("button");
      b.className = "btn-soft sm";
      b.textContent = "打开所在文件夹";
      b.addEventListener("click", () => api("/api/open", { path: dir })
        .catch((e) => toast(e.message, "err")));
      acts.appendChild(b);
      el.appendChild(acts);
    }
    box.appendChild(el);
  }
}

/* ---------------------------- 事件绑定 ---------------------------- */
function bind() {
  $("#btnPick").addEventListener("click", () => openBrowse("files"));
  $("#btnClear").addEventListener("click", () => {
    state.files = []; renderFiles(); updateOutDirDisplay(); $("#results").innerHTML = "";
  });
  $("#btnPickDir").addEventListener("click", () => openBrowse("dirs"));
  $("#btnRun").addEventListener("click", runConvert);

  $$('input[name="outMode"]').forEach((r) =>
    r.addEventListener("change", () => {
      const custom = r.value === "custom";
      $("#outDir").disabled = !custom;
      $("#btnPickDir").disabled = !custom;
      updateOutDirDisplay();
    }));

  // 折叠头点击开合（native 组内嵌开关不冒泡）
  ["OutDir", "Txt", "Native"].forEach((id) => {
    const head = $("#fold" + id + "Head");
    if (!head) return;
    head.addEventListener("click", (e) => {
      if (e.target.closest(".switch")) return;   // 点开关只切开关
      toggleFold(id);
    });
    head.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (!e.target.closest(".switch")) toggleFold(id);
      }
    });
  });

  // 高质量模式开关：切换状态摘要
  const nativeMode = $("#nativeMode");
  if (nativeMode) {
    nativeMode.addEventListener("change", updateNativeSum);
    const sw = $("#nativeSwitch");
    if (sw) sw.addEventListener("click", (e) => e.stopPropagation());
  }
  // 指定目录输入变化时刷新摘要
  $("#outDir").addEventListener("input", () => {
    const sum = $("#foldOutDirSum");
    if (sum) sum.textContent = $("#outDir").value ? "指定目录：" + $("#outDir").value : "指定目录（未选择）";
  });

  $("#modalClose").addEventListener("click", () => $("#modal").classList.add("hidden"));
  $("#modalCancel").addEventListener("click", () => $("#modal").classList.add("hidden"));
  $("#modalOk").addEventListener("click", confirmBrowse);
  $("#btnUp").addEventListener("click", async () => {
    const j = await api(`/api/browse?path=${encodeURIComponent(state.browse.path)}&kind=${state.browse.kind}`);
    loadBrowse(j.parent || "");
  });
  $("#btnNewFolder").addEventListener("click", async () => {
    const name = prompt("新文件夹名称", "新建文件夹");
    if (!name) return;
    try {
      await api("/api/mkdir", { path: state.browse.path, name });
      loadBrowse(state.browse.path);
    } catch (e) { toast(e.message, "err"); }
  });
  $("#modal").addEventListener("click", (e) => {
    if (e.target.id === "modal") $("#modal").classList.add("hidden");
  });

  initDrop();
}

/* ---------------------------- 心跳 ---------------------------- */
setInterval(() => { fetch("/api/heartbeat", { method: "POST" }).catch(() => {}); }, 20000);

/* 关闭标签页即结束程序（服务端有 20 秒缓冲，刷新不会误退出） */
window.addEventListener("pagehide", () => {
  try {
    if (navigator.sendBeacon) navigator.sendBeacon("/api/page-closed", "");
  } catch (e) { /* 忽略 */ }
});

init();
bind();
