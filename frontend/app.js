const API = 'http://localhost:8000';
let collection = 'github_rag';
let repoUrl = '';
let pollTimer = null;
let loading = false;
let qHistory = [];

// ── Marked config ──
const rnd = new marked.Renderer();
rnd.code = (code, lang) => {
  const l = lang || 'plaintext';
  let hi = code;
  try { hi = hljs.getLanguage(l) ? hljs.highlight(code, { language: l }).value : hljs.highlightAuto(code).value; } catch (e) { }
  const id = 'c' + Math.random().toString(36).slice(2);
  return `<div><div class="code-hdr" style="display:flex; justify-content:space-between; padding:8px 16px; background:rgba(0,0,0,0.5); border-bottom:1px solid rgba(255,255,255,0.1);"><span class="code-lang" style="font-family:var(--font-mono);font-size:11px;color:var(--text-dim);text-transform:uppercase;">${l}</span><button class="code-copy-btn" onclick="cpCode('${id}')" style="background:transparent;border:none;color:var(--text-muted);cursor:pointer;font-size:11px;font-family:var(--font-mono);">copy</button></div><pre><code id="${id}" class="hljs" style="display:block;padding:16px;background:transparent;border:none;overflow-x:auto;">${hi}</code></pre></div>`;
};
marked.setOptions({ renderer: rnd, breaks: true, gfm: true });

function cpCode(id) {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent);
  const btn = el.closest('div').querySelector('.code-copy-btn');
  if (btn) { btn.textContent = 'copied!'; setTimeout(() => btn.textContent = 'copy', 2000); }
}

// ── Screen management ──
function show(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  setTimeout(() => {
    document.getElementById(id).classList.add('active');
  }, 50);
}

// ── Onboarding ──
function pick(url) {
  document.getElementById('ob-url').value = url;
}

async function startIndex() {
  const url = document.getElementById('ob-url').value.trim();
  const errEl = document.getElementById('ob-error');
  errEl.style.display = 'none';

  if (!url) { showObErr('Please enter a GitHub repository URL'); return; }
  if (!url.startsWith('http')) { showObErr('Please enter a valid URL starting with https://'); return; }

  repoUrl = url;
  collection = 'github_rag';
  document.getElementById('prog-url').textContent = url;
  document.getElementById('sb-repo-name').textContent = url.replace('https://github.com/', '');
  document.getElementById('ob-btn').disabled = true;

  show('progress');
  resetProgress();

  try {
    const res = await fetch(`${API}/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url: url, collection_name: collection })
    });
    if (!res.ok) throw new Error('Server returned ' + res.status);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(doPoll, 1500);
  } catch (e) {
    showError('Cannot connect to API — make sure the FastAPI server is running at localhost:8000');
  }
}

function showObErr(msg) {
  const el = document.getElementById('ob-error');
  el.textContent = msg;
  el.style.display = 'block';
  document.getElementById('ob-btn').disabled = false;
}

// ── Progress steps ──


function resetProgress() {
  ['clone', 'embed', 'store'].forEach(k => setRow(k, 'wait'));
  const r = document.getElementById('prog-result');
  r.className = 'prog-result';
  document.getElementById('chat-btn').style.display = 'none';
}


// ── Poll backend status ──
async function doPoll() {
  try {
    const res = await fetch(`${API}/status/${collection}`);
    const data = await res.json();
    const s = data.status || 'not_started';
    handleStatus(s);
  } catch (e) { }
}

function handleStatus(s) {
  if (s === 'cloning') {
    setRow('clone', 'active');
    setRow('embed', 'wait');
    setRow('store', 'wait');
  } else if (s === 'embedding') {
    setRow('clone', 'done');
    setRow('embed', 'active');
    setRow('store', 'wait');
  } else if (s === 'storing') {
    setRow('clone', 'done');
    setRow('embed', 'done');
    setRow('store', 'active');
  } else if (s.startsWith('done')) {
    clearInterval(pollTimer);
    ['clone', 'embed', 'store'].forEach(k => setRow(k, 'done'));
    const chunks = s.split('|')[1] || '?';
    showSuccess(`${chunks} chunks indexed — ready to chat`);
  } else if (s.startsWith('failed')) {
    clearInterval(pollTimer);
    const msg = s.split('|').slice(1).join('|') || 'Unknown error';
    showError(msg);
  }
}

function setRow(key, state) {
  const dot = document.getElementById('dot-' + key);
  const label = document.getElementById('label-' + key);
  const val = document.getElementById('val-' + key);
  dot.className = 'state-dot ' + (state === 'active' ? 'dot-active' : state === 'done' ? 'dot-done' : 'dot-wait');
  label.className = 'state-label ' + state;
  val.textContent = state === 'active' ? 'running' : state === 'done' ? 'done' : '';
  val.className = 'state-val' + (state === 'active' ? ' active' : '');
}

function showSuccess(sub) {
  const r = document.getElementById('prog-result');
  r.className = 'prog-result success visible';
  document.getElementById('result-icon').textContent = '✅';
  document.getElementById('result-title').textContent = 'Codebase indexed';
  document.getElementById('result-sub').textContent = sub;
  document.getElementById('chat-btn').style.display = 'inline-block';
}

function showError(msg) {
  const r = document.getElementById('prog-result');
  r.className = 'prog-result error visible';
  document.getElementById('result-icon').textContent = '⚠️';
  document.getElementById('result-title').textContent = 'Indexing failed';
  document.getElementById('result-sub').textContent = msg;
}

// ── Navigation ──
function goChat() { show('chat'); }

function goHome() {
  if (pollTimer) clearInterval(pollTimer);
  document.getElementById('ob-btn').disabled = false;
  document.getElementById('ob-url').value = '';
  document.getElementById('ob-error').style.display = 'none';
  resetChatMessages();
  show('onboarding');
}

function resetChatMessages() {
  const msgs = document.getElementById('chat-msgs');
  msgs.innerHTML = `
    <div class="chat-empty" id="chat-empty">
      <div class="chat-empty-icon">⌘</div>
      <div class="chat-empty-title">Ready to assist.</div>
      <div class="chat-empty-sub">Query your entire repository in natural language. We'll search the vector space and cross-reference exact files for your answer.</div>
    </div>`;
  qHistory = [];
  document.getElementById('sb-hist').innerHTML = '';
}

// ── Chat ──
function resize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 150) + 'px';
}

function suggest(text) {
  document.getElementById('chat-ta').value = text;
  document.getElementById('chat-form').requestSubmit();
}

document.getElementById('chat-ta').addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    document.getElementById('chat-form').requestSubmit();
  }
});

async function send() {
  const ta = document.getElementById('chat-ta');
  const q = ta.value.trim();
  if (!q || loading) return;

  loading = true;
  ta.value = ''; ta.style.height = 'auto';
  document.getElementById('send-btn').disabled = true;

  const empty = document.getElementById('chat-empty');
  if (empty) empty.remove();

  addMsg('user', q, null);
  qHistory.unshift(q);
  updateHist();

  const tid = addTyping();

  try {
    const res = await fetch(`${API}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, collection_name: collection, top_k: 5 })
    });
    const data = await res.json();
    removeTyping(tid);
    addMsg('bot', data.answer || ('Error: ' + (data.detail || 'Unknown server fault')), data.sources);
  } catch (e) {
    removeTyping(tid);
    addMsg('bot', '⚠ Failed to reach the API backend. Verify that the FastAPI server is alive.', null);
  } finally {
    loading = false;
    document.getElementById('send-btn').disabled = false;
  }
}

function icon(f) {
  if (f.endsWith('.py')) return '🐍';
  if (f.endsWith('.js') || f.endsWith('.ts')) return '⚡';
  if (f.endsWith('.html') || f.endsWith('.css')) return '🎨';
  if (f.endsWith('.md')) return '📄';
  if (f.endsWith('.json') || f.endsWith('.yaml') || f.endsWith('.yml')) return '⚙️';
  return '📁';
}

function addMsg(role, text, sources) {
  const c = document.getElementById('chat-msgs');
  const m = document.createElement('div');
  m.className = 'msg ' + role;

  const av = document.createElement('div');
  av.className = 'msg-av ' + role;
  av.innerHTML = role === 'bot' ? '<span>⬡</span>' : '<span>◉</span>';

  const b = document.createElement('div');
  b.className = 'msg-bubble';

  if (role === 'bot' && text) {
    b.innerHTML = marked.parse(text);
  } else {
    b.textContent = text || '';
  }

  if (sources && sources.length > 0) {
    const sw = document.createElement('div');
    sw.className = 'sources-wrap';
    const sl = document.createElement('div');
    sl.className = 'sources-label';
    sl.textContent = 'Reference Sources';
    sw.appendChild(sl);
    const sc = document.createElement('div');
    sc.className = 'sources-chips';
    sources.forEach(s => {
      const ch = document.createElement('div');
      ch.className = 'src-chip';
      ch.innerHTML = `${icon(s.filename)} <span class="src-chip-name">${s.filename}</span><span class="src-chip-lines">L${s.start_line}-${s.end_line}</span>`;
      sc.appendChild(ch);
    });
    sw.appendChild(sc);
    b.appendChild(sw);
  }

  m.appendChild(av); m.appendChild(b);
  c.appendChild(m);
  c.scrollTop = c.scrollHeight;
}

function addTyping() {
  const c = document.getElementById('chat-msgs');
  const id = 't' + Date.now();
  const m = document.createElement('div');
  m.className = 'msg bot'; m.id = id;
  const av = document.createElement('div');
  av.className = 'msg-av bot'; av.textContent = '⬡';
  const b = document.createElement('div');
  b.className = 'msg-bubble';
  b.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
  m.appendChild(av); m.appendChild(b);
  c.appendChild(m); c.scrollTop = c.scrollHeight;
  return id;
}

function removeTyping(id) { const el = document.getElementById(id); if (el) el.remove(); }

function updateHist() {
  const list = document.getElementById('sb-hist');
  list.innerHTML = '';
  qHistory.slice(0, 10).forEach(q => {
    const i = document.createElement('div');
    i.className = 'sb-hist-item'; i.textContent = q;
    i.onclick = () => {
      document.getElementById('chat-ta').value = q;
      document.getElementById('chat-ta').focus();
    };
    list.appendChild(i);
  });
}

// Initial setup
document.addEventListener('DOMContentLoaded', () => {
  show('onboarding');
});
