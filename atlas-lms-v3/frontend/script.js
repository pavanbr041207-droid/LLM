/**
 * script.js — Atlas AI LMS
 * Full ChatGPT-like: chat, projects, maps, notes, study tools
 */

const BACKEND = "http://127.0.0.1:5001";

// ── State ──
let sessionId    = 'sess_' + Date.now();
let sessionName  = 'New Chat';
let selectedCmap = "Blues";
let activeCsv    = null;
let isWaiting    = false;
let hasMessages  = false;
let mapSBOpen    = false;
let sbOpen       = true;
let editingEl    = null;
let currentMapId = null;
let currentTitle = "";
let currentProjId= null;   // selected project in projects view
let moveChatId   = null;   // chat being moved
let moveProjSel  = null;   // selected target project
let projIcon     = "📁";
let timerSecs    = 25*60;
let timerRun     = false;
let timerIv      = null;
let activeNoteId = null;
let activeProjectId = null; // project context for current chat

// ─────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────
window.addEventListener("load", () => {
  checkConn();
  loadChatList();
  loadSBProjects();
  document.getElementById("msgInput").focus();
});

// ─────────────────────────────────────────────────────────
// CONNECTION
// ─────────────────────────────────────────────────────────
async function checkConn() {
  const dot = document.getElementById("connDot");
  const lbl = document.getElementById("connLbl");
  try {
    const r = await fetch(`${BACKEND}/api/health`, { signal: AbortSignal.timeout(4000) });
    if (r.ok) {
      dot.className  = "conn-dot ok";
      lbl.textContent = "connected";
    } else { throw new Error(); }
  } catch {
    dot.className  = "conn-dot err";
    lbl.textContent = "offline — run app.py";
  }
}

// ─────────────────────────────────────────────────────────
// SIDEBAR
// ─────────────────────────────────────────────────────────
function toggleSB() {
  sbOpen = !sbOpen;
  document.getElementById("sidebar").classList.toggle("collapsed", !sbOpen);
}

// ─────────────────────────────────────────────────────────
// VIEW SWITCHING
// ─────────────────────────────────────────────────────────
function switchView(name, btn) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById("view-" + name).classList.add("active");
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  if (name === "maps")     { switchMapsTab("history"); }
  if (name === "projects") { loadProjectsList(); }
  if (name === "notes")    loadNotesView();
}

function toggleTheme() {
  const t = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute("data-theme", t === "light" ? "" : "light");
}

// ─────────────────────────────────────────────────────────
// MAP SIDEBAR
// ─────────────────────────────────────────────────────────
function toggleMSB() {
  mapSBOpen = !mapSBOpen;
  document.getElementById("mapSidebar").classList.toggle("open", mapSBOpen);
}
function showMSB() {
  mapSBOpen = true;
  document.getElementById("mapSidebar").classList.add("open");
  document.getElementById("mapTogBtn").style.display = "flex";
}
function msbTab(name, btn) {
  document.querySelectorAll(".msb-tab").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".msb-pane").forEach(p => p.classList.remove("active"));
  document.getElementById("msb-" + name).classList.add("active");
  if (name === "history") loadMapHistory();
}

// ─────────────────────────────────────────────────────────
// COLOR
// ─────────────────────────────────────────────────────────
function pickColor(el) {
  document.querySelectorAll(".cmap").forEach(c => c.classList.remove("selected"));
  el.classList.add("selected");
  selectedCmap = el.dataset.cmap;
  toast("Color: " + selectedCmap);
}

// ─────────────────────────────────────────────────────────
// CHIP FILL
// ─────────────────────────────────────────────────────────
function fillInp(text) {
  const ta = document.getElementById("msgInput");
  ta.value = text;
  autoResize(ta);
  ta.focus();
}

// ─────────────────────────────────────────────────────────
// SEND MESSAGE
// ─────────────────────────────────────────────────────────
async function sendMsg() {
  if (isWaiting) return;
  const ta  = document.getElementById("msgInput");
  const msg = ta.value.trim();
  if (!msg) return;

  if (!hasMessages) {
    sessionName = msg.slice(0, 45);
    document.getElementById("chatTitle").textContent = sessionName;
    document.getElementById("welcome").style.display = "none";
    document.getElementById("messages").style.display = "block";
    hasMessages = true;
  }

  appendMsg("user", msg);
  ta.value = "";
  autoResize(ta);

  const typId = showTyping();
  isWaiting   = true;
  document.getElementById("sendBtn").disabled = true;

  try {
    const res = await fetch(`${BACKEND}/api/chat/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message:      msg,
        csv_path:     activeCsv,
        colormap:     selectedCmap,
        session_id:   sessionId,
        session_name: sessionName,
        project_id:   activeProjectId || null,
      }),
      signal: AbortSignal.timeout(120000)
    });
    const data = await res.json();
    removeTyping(typId);

    if (data.clear_csv) clearCSV(false);
    else if (data.csv_path) activeCsv = data.csv_path;
    if (data.show_sidebar) showMSB();

    if (data.map_url) {
      currentMapId = data.map_id || null;
      currentTitle = msg;
      appendMsgWithMap(data.reply, data.map_url);
      // loadMapHistory only if map sidebar is open — prevents unnecessary fetch
      if (mapSBOpen) loadMapHistory();
    } else if (data.error) {
      appendMsgWithErr(data.reply, data.error);
    } else {
      appendMsg("assistant", data.reply);
    }

    loadChatList(); // sidebar refresh once after reply settled

  } catch (e) {
    removeTyping(typId);
    appendMsg("assistant",
      e.name === "TimeoutError"
        ? "Request timed out. Map generation can take up to 2 minutes. Please try again."
        : `Cannot reach backend.\n\nMake sure python3 app.py is running on port 5001.\n\n${e.message}`
    );
  }

  isWaiting = false;
  document.getElementById("sendBtn").disabled = false;
}

// ─────────────────────────────────────────────────────────
// MESSAGES
// ─────────────────────────────────────────────────────────
function appendMsg(role, text) {
  const list = document.getElementById("messages");
  const div  = document.createElement("div");
  div.className = `msg ${role}`;
  const isUser = role === "user";
  const isPermission = !isUser && text === "This request requires backend map generation.\nAllow execution?\n[YES] [NO]";
  div.innerHTML = `
    <div class="msg-av">${isUser ? "P" : "◈"}</div>
    <div class="msg-body">
      <div class="msg-text">${fmt(text)}</div>
      ${isPermission ? `<div class="perm-row">
        <button class="perm-btn yes" onclick="sendPermission('yes')">YES</button>
        <button class="perm-btn no" onclick="sendPermission('no')">NO</button>
      </div>` : ""}
      <div class="msg-acts">
        <button class="msg-act" onclick="copyMsg(this)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>Copy
        </button>
        ${isUser ? `<button class="msg-act" onclick="editMsg(this)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>Edit
        </button>` : ""}
      </div>
    </div>`;
  list.appendChild(div);
  scrollBottom();
}

function sendPermission(answer) {
  document.getElementById("msgInput").value = answer;
  sendMsg();
}

function appendMsgWithMap(text, mapUrl) {
  const list   = document.getElementById("messages");
  const div    = document.createElement("div");
  div.className = "msg assistant";
  const imgSrc = `${BACKEND}${mapUrl}`;
  div.innerHTML = `
    <div class="msg-av">◈</div>
    <div class="msg-body">
      <div class="msg-text">
        ${text ? `<p>${fmt(text)}</p>` : ""}
        <div class="map-result">
          <img src="${imgSrc}" alt="Choropleth Map"
               onerror="this.parentElement.innerHTML='<p style=padding:14px;color:#e74c3c>Image failed to load.</p>'"/>
          <div class="map-result-btns">
            <button class="map-btn primary" onclick="openDl()">⬇ Download</button>
            <button class="map-btn" onclick="window.open('${imgSrc}','_blank')">🔍 Full size</button>
            <button class="map-btn" onclick="copyMsg(this)">⎘ Copy text</button>
          </div>
        </div>
      </div>
    </div>`;
  list.appendChild(div);
  scrollBottom();
}

function appendMsgWithErr(text, error) {
  const list = document.getElementById("messages");
  const div  = document.createElement("div");
  div.className = "msg assistant";
  div.innerHTML = `
    <div class="msg-av">◈</div>
    <div class="msg-body">
      <div class="msg-text">
        <p>${fmt(text)}</p>
        <div class="err-box">${error}</div>
      </div>
      <div class="msg-acts">
        <button class="msg-act" onclick="copyMsg(this)">⎘ Copy</button>
      </div>
    </div>`;
  list.appendChild(div);
  scrollBottom();
}

function showTyping() {
  const list = document.getElementById("messages");
  const id   = "typ-" + Date.now();
  const div  = document.createElement("div");
  div.className = "msg assistant"; div.id = id;
  div.innerHTML = `
    <div class="msg-av">◈</div>
    <div class="msg-body">
      <div class="msg-text">
        <div class="tdots"><div class="td"></div><div class="td"></div><div class="td"></div></div>
      </div>
    </div>`;
  list.appendChild(div);
  scrollBottom();
  return id;
}
function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

// ─────────────────────────────────────────────────────────
// COPY & EDIT
// ─────────────────────────────────────────────────────────
function copyMsg(btn) {
  // Walk up to .msg-body, then find .msg-text
  const body = btn.closest(".msg-body");
  if (!body) return;
  const textEl = body.querySelector(".msg-text");
  if (!textEl) return;

  // Clone node, remove inner buttons/svgs/map-result-btns so we only get text
  const clone = textEl.cloneNode(true);
  clone.querySelectorAll("button, svg, .map-result-btns, .map-result img, .perm-row").forEach(el => el.remove());
  const text = (clone.innerText || clone.textContent || "").trim();

  // Use clipboard API with fallback for http (non-HTTPS) environments
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text)
      .then(() => toast("Copied!"))
      .catch(() => _copyFallback(text));
  } else {
    _copyFallback(text);
  }
}

function _copyFallback(text) {
  // Works on http://localhost where clipboard API may be blocked
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;left:-9999px;top:-9999px;opacity:0";
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try {
    document.execCommand("copy");
    toast("Copied!");
  } catch(e) {
    toast("Copy failed — select text manually");
  }
  document.body.removeChild(ta);
}
function editMsg(btn) {
  editingEl = btn.closest(".msg");
  document.getElementById("editTa").value = editingEl.querySelector(".msg-text").innerText || "";
  document.getElementById("editOverlay").classList.add("show");
}
function closeEdit() {
  document.getElementById("editOverlay").classList.remove("show");
  editingEl = null;
}
function saveEdit() {
  const txt = document.getElementById("editTa").value.trim();
  if (!txt) return;
  if (editingEl) {
    const list = document.getElementById("messages");
    const all  = [...list.querySelectorAll(".msg")];
    const idx  = all.indexOf(editingEl);
    for (let i = idx; i < all.length; i++) all[i].remove();
  }
  closeEdit();
  document.getElementById("msgInput").value = txt;
  sendMsg();
}

// ─────────────────────────────────────────────────────────
// CSV UPLOAD
// ─────────────────────────────────────────────────────────
async function uploadCSV(event) {
  const file = event.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  toast("Uploading " + file.name + "...");
  try {
    const res  = await fetch(`${BACKEND}/api/map/upload-csv`, { method: "POST", body: fd });
    const data = await res.json();
    if (data.error) { toast("Error: " + data.error); return; }
    activeCsv = data.csv_path;
    document.getElementById("csvPrevBox").style.display = "block";
    document.getElementById("cpbName").textContent      = file.name;
    document.getElementById("cpbPrev").textContent      = data.preview;
    document.getElementById("csvBadgeRow").style.display = "flex";
    document.getElementById("csvBadgeName").textContent  = file.name;
    toast(file.name + " attached — " + data.rows + " rows");
  } catch (e) { toast("Upload failed: " + e.message); }
}

async function convertPasted() {
  const text = document.getElementById("pasteArea").value.trim();
  if (!text) { toast("Paste data first"); return; }
  toast("Converting...");
  try {
    const res  = await fetch(`${BACKEND}/api/chat/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "convert", pasted_data: text,
                             colormap: selectedCmap, session_id: sessionId, session_name: sessionName })
    });
    const data = await res.json();
    if (data.csv_path) {
      activeCsv = data.csv_path;
      document.getElementById("csvBadgeRow").style.display  = "flex";
      document.getElementById("csvBadgeName").textContent   = "pasted_data.csv";
      document.getElementById("pasteArea").value = "";
      toast("Data ready — ask me to generate a map!");
    }
  } catch (e) { toast("Failed: " + e.message); }
}

function clearCSV(showToast = true) {
  activeCsv = null;
  document.getElementById("csvBadgeRow").style.display   = "none";
  document.getElementById("csvPrevBox").style.display    = "none";
  document.getElementById("csvUpload").value = "";
  if (showToast) toast("CSV cleared");
}

// ─────────────────────────────────────────────────────────
// DOWNLOAD
// ─────────────────────────────────────────────────────────
function openDl()  { document.getElementById("dlOverlay").classList.add("show"); }
function closeDl() { document.getElementById("dlOverlay").classList.remove("show"); }
async function dlFmt(fmt) {
  const t = encodeURIComponent(currentTitle || "choropleth_map");
  const i = currentMapId ? `&id=${currentMapId}` : "";
  toast("Downloading ." + fmt.toUpperCase()); closeDl();
  try {
    const res  = await fetch(`${BACKEND}/api/map/download?format=${fmt}&title=${t}${i}`);
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `${currentTitle || "choropleth_map"}.${fmt}`;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { toast("Download failed: " + e.message); }
}
async function dlCSV() {
  if (!currentMapId) { toast("No map CSV snapshot selected"); return; }
  toast("Downloading map CSV snapshot"); closeDl();
  try {
    const res  = await fetch(`${BACKEND}/api/map/download-csv?id=${currentMapId}`);
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `map_${currentMapId}.csv`;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { toast("Download failed: " + e.message); }
}

// ─────────────────────────────────────────────────────────
// CHAT LIST (sidebar)
// ─────────────────────────────────────────────────────────
async function loadChatList() {
  try {
    const res   = await fetch(`${BACKEND}/api/chat/recent`);
    const chats = await res.json();
    const list  = document.getElementById("chatList");
    if (!chats.length) {
      list.innerHTML = `<div class="no-chats">No conversations yet</div>`;
      return;
    }
    list.innerHTML = chats.map(c => `
      <div class="chat-item ${c.id === sessionId ? "active" : ""}" onclick="loadChat('${c.id}','${c.name || "Chat"}')">
        <div class="ci-name">${c.name || "Untitled"}</div>
        <div class="ci-time">${c.updated || c.created || ""}</div>
        <div class="ci-actions">
          <button class="ci-act" onclick="event.stopPropagation();openMoveChat('${c.id}')">Move to project</button>
          <button class="ci-act" onclick="event.stopPropagation();deleteChat('${c.id}')">Delete</button>
        </div>
      </div>`).join("");
  } catch {}
}

async function loadChat(id, name) {
  try {
    const res  = await fetch(`${BACKEND}/api/chat/get/${id}`);
    const data = await res.json();
    sessionId        = id;
    sessionName      = name;
    hasMessages      = true;
    activeProjectId  = data.project_id || null;

    document.getElementById("chatTitle").textContent     = name;
    document.getElementById("welcome").style.display     = "none";
    document.getElementById("messages").style.display    = "block";
    document.getElementById("messages").innerHTML        = "";

    (data.messages || []).forEach(m => appendMsg(m.role, m.content));
    scrollBottom();
    switchView("chat", document.querySelector(".nav-item"));
  } catch {}
}

async function searchChats(q) {
  if (!q.trim()) { loadChatList(); return; }
  try {
    const res   = await fetch(`${BACKEND}/api/chat/search?q=${encodeURIComponent(q)}`);
    const chats = await res.json();
    const list  = document.getElementById("chatList");
    if (!chats.length) { list.innerHTML = `<div class="no-chats">No results</div>`; return; }
    list.innerHTML = chats.map(c => `
      <div class="chat-item" onclick="loadChat('${c.id}','${c.name || "Chat"}')">
        <div class="ci-name">${c.name || "Untitled"}</div>
        <div class="ci-time">${c.updated || ""}</div>
      </div>`).join("");
  } catch {}
}

async function deleteChat(id) {
  if (!confirm("Delete this chat?")) return;
  await fetch(`${BACKEND}/api/chat/delete/${id}`, { method: "DELETE" });
  if (id === sessionId) newChat();
  else { loadChatList(); }
  toast("Chat deleted");
}

function newChat() {
  sessionId       = 'sess_' + Date.now();
  sessionName     = 'New Chat';
  hasMessages     = false;
  activeCsv       = null;
  currentMapId    = null;
  activeProjectId = null;

  document.getElementById("chatTitle").textContent       = "Atlas AI";
  document.getElementById("welcome").style.display       = "flex";
  document.getElementById("messages").style.display      = "none";
  document.getElementById("messages").innerHTML          = "";
  document.getElementById("csvBadgeRow").style.display   = "none";
  document.getElementById("csvPrevBox").style.display    = "none";
  document.getElementById("mapTogBtn").style.display     = "none";
  mapSBOpen = false;
  document.getElementById("mapSidebar").classList.remove("open");

  switchView("chat", document.querySelector(".nav-item"));
  loadChatList(); // single refresh after state reset
}

// ─────────────────────────────────────────────────────────
// MOVE CHAT TO PROJECT
// ─────────────────────────────────────────────────────────
async function openMoveChat(chatId) {
  moveChatId  = chatId;
  moveProjSel = null;
  document.getElementById("moveChatOverlay").classList.add("show");

  const res      = await fetch(`${BACKEND}/api/project/list`);
  const projects = await res.json();
  const list     = document.getElementById("moveProjList");

  list.innerHTML = `
    <button class="move-proj-opt recent-opt" onclick="selectMoveTarget(this, null)">
      <span>📋</span> Recent Chats (remove from project)
    </button>` +
    projects.map(p => `
      <button class="move-proj-opt" onclick="selectMoveTarget(this,'${p.id}')">
        <span>${p.icon || "📁"}</span> ${p.title}
      </button>`).join("");
}

function selectMoveTarget(el, projId) {
  document.querySelectorAll(".move-proj-opt").forEach(b => b.classList.remove("selected"));
  el.classList.add("selected");
  moveProjSel = projId;
}

async function confirmMoveChat() {
  if (!moveChatId) { closeMoveChat(); return; }
  try {
    const res = await fetch(`${BACKEND}/api/project/move-chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: moveChatId, project_id: moveProjSel })
    });
    const data = await res.json();
    if (data.ok) {
      toast(moveProjSel ? "Chat moved to project!" : "Chat moved to Recent");
      loadChatList();
      loadSBProjects();
      if (currentProjId) loadProjectChats(currentProjId);
    }
  } catch (e) { toast("Move failed: " + e.message); }
  closeMoveChat();
}

function closeMoveChat() {
  document.getElementById("moveChatOverlay").classList.remove("show");
  moveChatId  = null;
  moveProjSel = null;
}

// ─────────────────────────────────────────────────────────
// MAP HISTORY
// ─────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────
// MAP SIDEBAR HISTORY (chat sidebar panel)
// View only — no paste into chat, no map reuse
// ─────────────────────────────────────────────────────────
async function loadMapHistory() {
  try {
    const res  = await fetch(`${BACKEND}/api/map/history`);
    const hist = await res.json();
    const list = document.getElementById("mapHistList");
    if (!hist.length) { list.innerHTML = `<div class="empty-state">No maps yet</div>`; return; }
    list.innerHTML = hist.map(h => `
      <div class="mhc">
        <img src="${BACKEND}/storage/history/${h.map_file}?nocache=${h.id}"
             onerror="this.style.display='none'" loading="lazy"/>
        <div class="mhc-info">
          <div class="mhc-title">${h.title || "Untitled"}</div>
          <div class="mhc-meta">${h.colormap || ""} · ${(h.timestamp||"").slice(0,16)}</div>
        </div>
        <div class="mhc-btns">
          <button class="mhc-dl" onclick="histDl('${h.id}','${encodeURIComponent(h.title||'map')}','png')">⬇PNG</button>
          <button class="mhc-dl" onclick="histDl('${h.id}','${encodeURIComponent(h.title||'map')}','csv')">⬇CSV</button>
        </div>
      </div>`).join("");
  } catch(e) { console.error("loadMapHistory:",e); }
}

async function histDl(mapId, title, fmt) {
  try {
    const t   = encodeURIComponent(decodeURIComponent(title));
    const url = fmt === "csv"
      ? `${BACKEND}/api/map/download-csv?id=${mapId}`
      : `${BACKEND}/api/map/download?format=${fmt}&title=${t}&id=${mapId}`;
    const res  = await fetch(url);
    const blob = await res.blob();
    const a    = document.createElement("a");
    a.href     = URL.createObjectURL(blob);
    a.download = `${decodeURIComponent(title)}.${fmt}`;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast(`Downloading .${fmt.toUpperCase()}`);
  } catch(e) { toast("Download failed: " + e.message); }
}

// ─────────────────────────────────────────────────────────
// MAPS VIEW — 2 TABS
// ─────────────────────────────────────────────────────────
function switchMapsTab(tab) {
  document.getElementById("mapsTabHistory").style.display = tab === "history" ? "" : "none";
  document.getElementById("mapsTabManual").style.display  = tab === "manual"  ? "" : "none";
  document.getElementById("tabHistBtn").classList.toggle("active",   tab === "history");
  document.getElementById("tabManualBtn").classList.toggle("active",  tab === "manual");
  if (tab === "history") loadMapsView();
}

async function loadMapsView() {
  try {
    const res  = await fetch(`${BACKEND}/api/map/history`);
    const hist = await res.json();
    const grid = document.getElementById("mapsGrid");
    if (!hist.length) {
      grid.innerHTML = `<div class="empty-state" style="text-align:center;padding:60px 20px">
        <div style="font-size:40px;margin-bottom:12px">🗺️</div>
        <div style="font-size:15px;font-weight:600;margin-bottom:6px">No maps yet</div>
        <div style="font-size:13px;color:var(--muted)">Go to Chat and ask Atlas AI to generate a choropleth map,<br>or use the Manual Generation tab above.</div>
      </div>`;
      return;
    }
    // History: view + download only. NO paste-into-chat button.
    grid.innerHTML = hist.map(h => `
      <div class="map-card">
        <img src="${BACKEND}/storage/history/${h.map_file}?nocache=${h.id}"
             onerror="this.src=''" loading="lazy"/>
        <div class="mc-info">
          <div class="mc-title">${h.title || "Untitled"}</div>
          <div class="mc-meta">${h.colormap||""} · ${h.value_col||""} · ${(h.timestamp||"").slice(0,16)}</div>
        </div>
        <div class="mc-btns">
          <button class="mc-dl-btn" onclick="histDl('${h.id}','${encodeURIComponent(h.title||'map')}','png')">⬇ PNG</button>
          <button class="mc-dl-btn" onclick="histDl('${h.id}','${encodeURIComponent(h.title||'map')}','pdf')">⬇ PDF</button>
          <button class="mc-dl-btn" onclick="histDl('${h.id}','${encodeURIComponent(h.title||'map')}','csv')">⬇ CSV</button>
        </div>
      </div>`).join("");
  } catch(e) { console.error("loadMapsView:",e); }
}

// ─────────────────────────────────────────────────────────
// MANUAL GENERATION TAB
// ─────────────────────────────────────────────────────────
let mgpCsvPath = null;
let mgpMapId   = null;

function mgpDragOver(e) {
  e.preventDefault();
  document.getElementById("mgpDropZone").classList.add("mgp-drag-over");
}
function mgpDragLeave() {
  document.getElementById("mgpDropZone").classList.remove("mgp-drag-over");
}
function mgpDrop(e) {
  e.preventDefault();
  document.getElementById("mgpDropZone").classList.remove("mgp-drag-over");
  const file = e.dataTransfer?.files?.[0];
  if (file) _mgpUpload(file);
}
function mgpFileChosen(e) {
  const file = e.target.files?.[0];
  if (file) _mgpUpload(file);
}
async function _mgpUpload(file) {
  if (!file.name.toLowerCase().endsWith(".csv")) { toast("Please upload a .csv file"); return; }
  const fd = new FormData();
  fd.append("file", file);
  mgpStatus("⏳ Uploading…", false);
  try {
    const res  = await fetch(`${BACKEND}/api/map/upload-csv`, { method:"POST", body:fd });
    const data = await res.json();
    if (data.error) { mgpStatus("⚠️ " + data.error, true); return; }
    mgpCsvPath = data.csv_path;
    document.getElementById("mgpFileName").textContent  = file.name;
    document.getElementById("mgpRowCount").textContent  = `${data.rows} data rows`;
    document.getElementById("mgpPreviewText").textContent = data.preview || "";
    document.getElementById("mgpPreviewBox").style.display = "";
    document.getElementById("mgpDropZone").style.display   = "none";
    document.getElementById("mgpPasteArea").value = "";
    document.getElementById("mgpParseBtn").disabled = true;
    document.getElementById("mgpGenBtn").disabled = false;
    document.getElementById("mgpResult").style.display = "none";
    mgpStatus("✅ File loaded. Set title and colour, then click Generate Map.", false);
    toast("CSV ready");
  } catch(e) { mgpStatus("⚠️ Upload failed: " + e.message, true); }
}
function mgpClearFile() {
  mgpCsvPath = null; mgpMapId = null;
  document.getElementById("mgpPreviewBox").style.display = "none";
  document.getElementById("mgpDropZone").style.display   = "";
  document.getElementById("mgpFileInput").value = "";
  document.getElementById("mgpGenBtn").disabled = true;
  document.getElementById("mgpResult").style.display = "none";
  mgpStatus("", false);
}
function mgpPasteChanged() {
  const has = document.getElementById("mgpPasteArea").value.trim().length > 0;
  document.getElementById("mgpParseBtn").disabled = !has;
}
async function mgpParsePasted() {
  const text = document.getElementById("mgpPasteArea").value.trim();
  if (!text) { toast("Paste some data first"); return; }
  // Save pasted data as CSV via existing csv_handler endpoint
  try {
    const fd = new FormData();
    const blob = new Blob([text], { type: "text/csv" });
    fd.append("file", blob, "pasted_data.csv");
    mgpStatus("⏳ Parsing pasted data…", false);
    const res  = await fetch(`${BACKEND}/api/map/upload-csv`, { method:"POST", body:fd });
    const data = await res.json();
    if (data.error) { mgpStatus("⚠️ " + data.error, true); return; }
    mgpCsvPath = data.csv_path;
    document.getElementById("mgpPreviewBox").style.display = "";
    document.getElementById("mgpFileName").textContent  = "Pasted data";
    document.getElementById("mgpRowCount").textContent  = `${data.rows} rows`;
    document.getElementById("mgpPreviewText").textContent = data.preview || text.slice(0,200);
    document.getElementById("mgpDropZone").style.display   = "none";
    document.getElementById("mgpGenBtn").disabled = false;
    document.getElementById("mgpResult").style.display = "none";
    mgpStatus("✅ Data parsed. Click Generate Map.", false);
  } catch(e) { mgpStatus("⚠️ Parse failed: " + e.message, true); }
}
async function mgpGenerate() {
  if (!mgpCsvPath) { toast("Upload or paste CSV data first"); return; }
  const btn = document.getElementById("mgpGenBtn");
  btn.disabled = true; btn.textContent = "⏳ Generating map…";
  mgpStatus("🔄 Running Python map generation code… this may take 30–60 seconds.", false);
  document.getElementById("mgpResult").style.display = "none";
  try {
    const res  = await fetch(`${BACKEND}/api/map/generate-from-upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        csv_path:   mgpCsvPath,
        colormap:   document.getElementById("mgpColormap").value || "Blues",
        title:      document.getElementById("mgpTitle").value.trim() || "Choropleth Map",
        session_id: "manual_gen",
      }),
      signal: AbortSignal.timeout(150000),
    });
    const data = await res.json();
    if (data.error) {
      mgpStatus("⚠️ Generation failed:\n" + data.error, true);
    } else {
      mgpMapId = data.map_id;
      const img = document.getElementById("mgpResultImg");
      img.src = `${BACKEND}${data.map_url}`;
      document.getElementById("mgpResult").style.display = "";
      mgpStatus("✅ Map generated successfully from your data.", false);
      if (mapSBOpen) loadMapHistory();
      loadMapsView();
    }
  } catch(e) {
    mgpStatus(
      e.name === "TimeoutError"
        ? "⚠️ Timed out (>2.5 min). Try a smaller CSV or check your Ollama server."
        : "⚠️ Error: " + e.message,
      true
    );
  }
  btn.disabled = false; btn.textContent = "🗺️ Generate Map";
}
async function mgpDownload(fmt) {
  if (!mgpMapId) { toast("Generate a map first"); return; }
  const title = document.getElementById("mgpTitle").value.trim() || "map";
  await histDl(mgpMapId, title, fmt);
}
function mgpStatus(msg, isError) {
  const el = document.getElementById("mgpStatus");
  if (!msg) { el.style.display = "none"; return; }
  el.style.display = "";
  el.textContent   = msg;
  el.className     = "mgp-status" + (isError ? " mgp-status-err" : "");
}



// ─────────────────────────────────────────────────────────
// PROJECTS — Sidebar list
// ─────────────────────────────────────────────────────────
async function loadSBProjects() {
  try {
    const res      = await fetch(`${BACKEND}/api/project/list`);
    const projects = await res.json();
    const list     = document.getElementById("sbProjList");
    if (!projects.length) { list.innerHTML = ""; return; }
    list.innerHTML = projects.map(p => `
      <div class="proj-sb-item ${p.id === currentProjId ? "active" : ""}"
           onclick="openProjectFromSB('${p.id}')">
        <span class="psi-icon">${p.icon || "📁"}</span>
        <span class="psi-name">${p.title}</span>
        <span class="psi-count">${p.chat_count || 0}</span>
      </div>`).join("");
  } catch {}
}

async function openProjectFromSB(projId) {
  switchView("projects", document.querySelectorAll(".nav-item")[1]);
  await loadProjectsList();
  selectProject(projId);
}

// ─────────────────────────────────────────────────────────
// PROJECTS — Main view
// ─────────────────────────────────────────────────────────
async function loadProjectsList() {
  try {
    const res      = await fetch(`${BACKEND}/api/project/list`);
    const projects = await res.json();
    const items    = document.getElementById("projItems");

    if (!projects.length) {
      items.innerHTML = `<div class="empty-state">No projects yet.<br>Click "+ New" to create one.</div>`;
      return;
    }

    items.innerHTML = projects.map(p => `
      <div class="proj-item ${p.id === currentProjId ? "active" : ""}"
           onclick="selectProject('${p.id}')">
        <span class="pi-icon">${p.icon || "📁"}</span>
        <div class="pi-info">
          <div class="pi-name">${p.title}</div>
          <div class="pi-meta">${p.chat_count || 0} chats · ${p.updated || p.created}</div>
        </div>
      </div>`).join("");
  } catch {}
}

async function selectProject(projId) {
  currentProjId = projId;

  // Mark active in list
  document.querySelectorAll(".proj-item").forEach(el => {
    el.classList.toggle("active", el.onclick.toString().includes(projId));
  });

  // Load project data
  const res  = await fetch(`${BACKEND}/api/project/get/${projId}`);
  const proj = await res.json();

  // Show detail panel
  document.getElementById("projNoSel").style.display  = "none";
  const detail = document.getElementById("projDetail");
  detail.style.display = "flex";

  document.getElementById("pdIcon").textContent  = proj.icon || "📁";
  document.getElementById("pdTitle").textContent = proj.title;

  // Pre-fill settings
  document.getElementById("settingsProjName").value = proj.title;
  document.getElementById("settingsPrompt").value   = proj.system_prompt || "";
  document.getElementById("settingsMemory").value   = proj.memory || "";

  // Load chats tab
  await loadProjectChats(projId);
  await loadProjectDocs(projId);
}

// Project tabs
function projTab(name, btn) {
  document.querySelectorAll(".proj-tab").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".proj-tab-panel").forEach(p => p.classList.remove("active"));
  document.getElementById("ptab-" + name).classList.add("active");
}

async function loadProjectChats(projId) {
  try {
    const res   = await fetch(`${BACKEND}/api/project/chats/${projId}`);
    const chats = await res.json();
    const list  = document.getElementById("projChatsList");

    if (!chats.length) {
      list.innerHTML = `
        <div class="proj-empty-chats">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <p>No chats in this project yet.</p>
          <p style="font-size:12px;color:var(--muted)">Start a new chat or move an existing chat here.</p>
        </div>`;
      return;
    }

    list.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px">` +
      chats.map(c => `
        <div class="proj-chat-item">
          <div class="pci-name">${c.name || "Untitled"}</div>
          <div class="pci-time">${c.updated || ""}</div>
          <button class="pci-open" onclick="openProjChat('${c.id}','${c.name || "Chat"}')">Open</button>
          <button class="pci-remove" onclick="removeChatFromProj('${c.id}')">Remove</button>
        </div>`).join("") + `</div>`;
  } catch {}
}

async function loadProjectDocs(projId) {
  try {
    const res  = await fetch(`${BACKEND}/api/project/docs/list/${projId}`);
    const docs = await res.json();
    const list = document.getElementById("projDocsList");

    if (!docs.length) {
      list.innerHTML = `<div class="empty-state">No documents uploaded yet.</div>`;
      return;
    }

    const extIcon = { ".pdf":"📄",".txt":"📝",".md":"📝",".docx":"📃",".csv":"📊" };
    list.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px">` +
      docs.map(d => `
        <div class="doc-item">
          <span class="doc-icon">${extIcon[d.ext] || "📄"}</span>
          <div class="doc-info">
            <div class="doc-name">${d.name}</div>
            <div class="doc-meta">${(d.size/1024).toFixed(1)} KB · ${d.uploaded}</div>
          </div>
          <button class="doc-del" onclick="deleteProjDoc('${projId}','${d.id}','${d.name}')">Delete</button>
        </div>`).join("") + `</div>`;
  } catch {}
}

// Open a project chat in chat view
async function openProjChat(chatId, chatName) {
  activeProjectId = currentProjId;
  await loadChat(chatId, chatName);
}

// New chat within project context
function openChatInProject() {
  if (!currentProjId) return;
  activeProjectId = currentProjId;
  newChat();
  // Update session name with project reference
  const proj = document.getElementById("pdTitle").textContent;
  sessionName = `${proj} Chat`;
  document.getElementById("chatTitle").textContent = sessionName;
}

async function removeChatFromProj(chatId) {
  if (!confirm("Remove this chat from the project? It will move to Recent Chats.")) return;
  try {
    const res = await fetch(`${BACKEND}/api/project/remove-chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId })
    });
    const data = await res.json();
    if (data.ok) {
      toast("Chat moved to Recent Chats");
      loadProjectChats(currentProjId);
      loadChatList();
    }
  } catch (e) { toast("Error: " + e.message); }
}

async function uploadProjDoc(event) {
  if (!currentProjId) return;
  const file = event.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  toast("Uploading document...");
  try {
    const res  = await fetch(`${BACKEND}/api/project/docs/upload/${currentProjId}`, { method:"POST", body:fd });
    const data = await res.json();
    if (data.error) { toast("Error: " + data.error); return; }
    toast(`${file.name} uploaded!`);
    loadProjectDocs(currentProjId);
    event.target.value = "";
  } catch (e) { toast("Upload failed: " + e.message); }
}

async function deleteProjDoc(projId, docId, name) {
  if (!confirm(`Delete "${name}"?`)) return;
  try {
    await fetch(`${BACKEND}/api/project/docs/delete/${projId}/${docId}`, { method:"DELETE" });
    toast("Document deleted");
    loadProjectDocs(projId);
  } catch (e) { toast("Error: " + e.message); }
}

// Project settings actions
async function saveProjName() {
  if (!currentProjId) return;
  const name = document.getElementById("settingsProjName").value.trim();
  if (!name) { toast("Enter a project name"); return; }
  await fetch(`${BACKEND}/api/project/update/${currentProjId}`, {
    method:"PUT", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ title: name })
  });
  document.getElementById("pdTitle").textContent = name;
  toast("Project renamed!");
  loadSBProjects();
}

async function saveSystemPrompt() {
  if (!currentProjId) return;
  const prompt = document.getElementById("settingsPrompt").value.trim();
  await fetch(`${BACKEND}/api/project/update-prompt/${currentProjId}`, {
    method:"PUT", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ system_prompt: prompt })
  });
  toast("AI instructions saved!");
}

async function saveMemory() {
  if (!currentProjId) return;
  const memory = document.getElementById("settingsMemory").value.trim();
  await fetch(`${BACKEND}/api/project/update/${currentProjId}`, {
    method:"PUT", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ memory: memory })
  });
  toast("Project memory saved!");
}

async function deleteProject() {
  const name = document.getElementById("pdTitle").textContent;
  if (!confirm(`Delete project "${name}" and all its data? Chats will be moved to Recent.`)) return;
  await fetch(`${BACKEND}/api/project/delete/${currentProjId}`, { method:"DELETE" });
  currentProjId = null;
  document.getElementById("projNoSel").style.display = "flex";
  document.getElementById("projDetail").style.display = "none";
  toast("Project deleted");
  loadProjectsList(); loadSBProjects(); loadChatList();
}

// Create project
function openCreateProj() {
  document.getElementById("createProjOverlay").classList.add("show");
  document.getElementById("projNameInp").focus();
}
function closeCreateProj() {
  document.getElementById("createProjOverlay").classList.remove("show");
  document.getElementById("projNameInp").value = "";
  document.getElementById("projDescTa").value  = "";
}
function selIcon(btn, icon) {
  document.querySelectorAll(".pib").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  projIcon = icon;
}
async function createProj() {
  const name = document.getElementById("projNameInp").value.trim();
  if (!name) { toast("Enter a project name"); return; }
  const desc = document.getElementById("projDescTa").value.trim();
  try {
    const res  = await fetch(`${BACKEND}/api/project/create`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ title:name, description:desc, icon:projIcon })
    });
    const proj = await res.json();
    closeCreateProj();
    toast("Project created!");
    await loadProjectsList();
    selectProject(proj.id);
    loadSBProjects();
  } catch (e) { toast("Failed: " + e.message); }
}

// ─────────────────────────────────────────────────────────
// NOTES
// ─────────────────────────────────────────────────────────
async function loadNotesView() {
  try {
    const res   = await fetch(`${BACKEND}/api/study/notes/list`);
    const notes = await res.json();
    const list  = document.getElementById("notesList");
    if (!notes.length) { list.innerHTML = `<div class="empty-state">No notes yet</div>`; return; }
    list.innerHTML = notes.map(n => `
      <div class="note-item ${n.id === activeNoteId ? "active" : ""}"
           onclick="openNote('${n.id}','${encodeURIComponent(n.title)}','${encodeURIComponent(n.content)}')">
        <div class="ni-title">${n.title}</div>
        <div class="ni-prev">${n.content}</div>
      </div>`).join("");
  } catch {}
}

function newNote() {
  activeNoteId = null;
  document.getElementById("noteTitleInp").value   = "";
  document.getElementById("noteContentTa").value  = "";
  document.getElementById("noteTitleInp").focus();
}

function openNote(id, title, content) {
  activeNoteId = id;
  document.getElementById("noteTitleInp").value  = decodeURIComponent(title);
  document.getElementById("noteContentTa").value = decodeURIComponent(content);
  document.querySelectorAll(".note-item").forEach(n => n.classList.remove("active"));
  event.currentTarget.classList.add("active");
}

async function saveNote() {
  const title   = document.getElementById("noteTitleInp").value.trim();
  const content = document.getElementById("noteContentTa").value.trim();
  if (!title) { toast("Enter a note title"); return; }
  await fetch(`${BACKEND}/api/study/notes/save`, {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ title, content })
  });
  loadNotesView();
  toast("Note saved!");
}

// ─────────────────────────────────────────────────────────
// STUDY TOOLS
// ─────────────────────────────────────────────────────────
async function genMCQ() {
  const topic = document.getElementById("mcqTopic").value.trim();
  const count = document.getElementById("mcqCount").value;
  if (!topic) { toast("Enter a topic"); return; }
  const box = document.getElementById("mcqResult");
  box.style.display = "block"; box.textContent = "Generating...";
  try {
    const res  = await fetch(`${BACKEND}/api/study/generate-mcq`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ topic, count: parseInt(count) })
    });
    const data = await res.json();
    box.textContent = data.mcqs || data.error || "No result";
  } catch (e) { box.textContent = "Failed. Check backend is running."; }
}

async function genAssign() {
  const topic = document.getElementById("assignTopic").value.trim();
  const type  = document.getElementById("assignType").value;
  if (!topic) { toast("Enter a topic"); return; }
  const box = document.getElementById("assignResult");
  box.style.display = "block"; box.textContent = "Generating...";
  try {
    const res  = await fetch(`${BACKEND}/api/study/generate-assignment`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ topic, type })
    });
    const data = await res.json();
    box.textContent = data.assignment || data.error || "No result";
  } catch (e) { box.textContent = "Failed. Check backend is running."; }
}

async function explainIt() {
  const topic = document.getElementById("explainTopic").value.trim();
  const level = document.getElementById("explainLevel").value;
  if (!topic) { toast("Enter a topic"); return; }
  const box = document.getElementById("explainResult");
  box.style.display = "block"; box.textContent = "Generating...";
  try {
    const res  = await fetch(`${BACKEND}/api/study/explain`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ topic, level })
    });
    const data = await res.json();
    box.textContent = data.explanation || data.error || "No result";
  } catch (e) { box.textContent = "Failed. Check backend is running."; }
}

// ─────────────────────────────────────────────────────────
// POMODORO TIMER
// ─────────────────────────────────────────────────────────
function startTimer() {
  if (timerRun) {
    clearInterval(timerIv); timerRun = false;
    document.getElementById("timerBtn").textContent = "Start";
    return;
  }
  timerRun = true;
  document.getElementById("timerBtn").textContent = "Pause";
  timerIv = setInterval(() => {
    timerSecs--;
    if (timerSecs <= 0) {
      clearInterval(timerIv); timerRun = false;
      timerSecs = 5 * 60;
      document.getElementById("timerLbl").textContent  = "Break Time! 🎉";
      document.getElementById("timerDisp").textContent = "05:00";
      document.getElementById("timerBtn").textContent  = "Start";
      toast("Focus session done! Take a 5-minute break.");
      return;
    }
    const m = String(Math.floor(timerSecs/60)).padStart(2,"0");
    const s = String(timerSecs % 60).padStart(2,"0");
    document.getElementById("timerDisp").textContent = `${m}:${s}`;
  }, 1000);
}
function resetTimer() {
  clearInterval(timerIv); timerRun = false;
  timerSecs = 25 * 60;
  document.getElementById("timerDisp").textContent = "25:00";
  document.getElementById("timerLbl").textContent  = "Focus Session";
  document.getElementById("timerBtn").textContent  = "Start";
}

// ─────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────
function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); }
}
function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 200) + "px";
}
function scrollBottom() {
  const m = document.getElementById("messages");
  m.scrollTop = m.scrollHeight;
}
function fmt(text) {
  return text
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g,     "<em>$1</em>")
    .replace(/`(.*?)`/g,       "<code>$1</code>")
    .replace(/\n/g,            "<br>");
}
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent  = msg;
  el.style.display = "block";
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.display = "none"; }, 2600);
}
