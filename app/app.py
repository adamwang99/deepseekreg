#!/usr/bin/env python3
"""
DeepSeek Account Creator — Web UI
Chạy: python3 app.py (không cần cài thêm gì)
Truy cập: http://localhost:8080
"""
import json, re, time, random, string, html as hm, http.cookiejar, urllib.request, urllib.parse
import sqlite3, os, csv, io, threading, queue, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from playwright.sync_api import sync_playwright

# === CONFIG ===
DB_FILE = os.path.join(os.path.dirname(__file__), 'accounts.db')
HOST = '0.0.0.0'
PORT = 8080

DOMAINS = ["newdelhi.io.vn", "mailo.edu.pl", "nik.edu.pl", "gddp2018.edu.vn",
           "itmo.edu.pl", "mailer.edu.pl", "newyork.io.vn", "dulieu.io.vn", "jakarta.io.vn"]

# === Database ===
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS accounts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT UNIQUE,
                  password TEXT,
                  domain TEXT,
                  proxy TEXT,
                  status TEXT DEFAULT 'created',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS config
                 (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

def save_account(email, password, domain, proxy):
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("INSERT OR IGNORE INTO accounts (email, password, domain, proxy, status) VALUES (?,?,?,?,'created')",
                     (email, password, domain, proxy))
        conn.commit()
    except: pass
    conn.close()

def get_accounts():
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("SELECT email, password, domain, proxy, status, created_at FROM accounts ORDER BY id DESC").fetchall()
    conn.close()
    return rows

def save_config(k, v):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()

def get_config(k, default=''):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT value FROM config WHERE key=?", (k,)).fetchone()
    conn.close()
    return row[0] if row else default

def export_csv():
    rows = get_accounts()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Email', 'Password', 'Domain', 'Proxy', 'Status', 'Created'])
    for r in rows:
        w.writerow(r)
    return out.getvalue()

def export_txt():
    rows = get_accounts()
    lines = ["# DeepSeek Accounts", "# Format: email|password|domain", "---"]
    for r in rows:
        lines.append(f"{r[0]}|{r[1]}|{r[2]}")
    return '\n'.join(lines)

# === Workers ===
worker_running = False
worker_queue = queue.Queue()
worker_progress = {}
worker_logs = []
logs_lock = threading.Lock()

def add_log(msg):
    with logs_lock:
        ts = time.strftime('%H:%M:%S')
        worker_logs.append(f'[{ts}] {msg}')
        if len(worker_logs) > 200:
            worker_logs.pop(0)

class ProxyConfig:
    def __init__(self, auth_str=''):
        self.proxies = []
        self.current = 0
        self.lock = threading.Lock()
        self.parse(auth_str)
    
    def parse(self, s):
        self.proxies = []
        for line in s.strip().split('\n'):
            line = line.strip()
            if not line: continue
            # Format: user:pass@host:port or host:port
            parts = line.split('@')
            if len(parts) == 2:
                auth, server = parts
                u, p = auth.split(':') if ':' in auth else (auth, '')
                self.proxies.append({'server': f'http://{server}', 'username': u, 'password': p})
            else:
                self.proxies.append({'server': f'http://{line}', 'username': '', 'password': ''})
    
    def next(self):
        with self.lock:
            if not self.proxies: return None
            p = self.proxies[self.current % len(self.proxies)]
            self.current += 1
            return p

proxy_config = ProxyConfig()

def create_email(domain):
    """Create temp email via imail.edu.vn."""
    ua = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        resp = opener.open(urllib.request.Request('https://imail.edu.vn/', headers={'User-Agent': ua}), timeout=15)
        content = resp.read().decode('utf-8')
        lw = re.search(r"livewire_token\s*=\s*'([^']+)'", content)
        lw_token = lw.group(1) if lw else ''
        for m in re.finditer(r'wire:id="([^"]+)"[^>]*wire:initial-data="([^"]+)"', content):
            d = json.loads(hm.unescape(m.group(2)))
            if d.get('fingerprint',{}).get('name') == 'frontend.actions':
                uname = ''.join(random.choices(string.ascii_lowercase, k=7))
                email = f'{uname}@{domain}'
                def rd(): return ''.join(random.choices(string.ascii_lowercase+string.digits, k=5))
                payload = {
                    'fingerprint': d['fingerprint'], 'serverMemo': d['serverMemo'],
                    'updates': [
                        {'type':'syncInput','payload':{'id':rd(),'name':'user','value':uname}},
                        {'type':'syncInput','payload':{'id':rd(),'name':'domain','value':domain}},
                        {'type':'callMethod','payload':{'id':rd(),'method':'create','params':[]}}
                    ]
                }
                req2 = urllib.request.Request('https://imail.edu.vn/livewire/message/frontend.actions',
                    data=json.dumps(payload).encode(),
                    headers={'Content-Type':'application/json','X-CSRF-TOKEN':lw_token,'X-Livewire':'true','Accept':'application/json','X-Requested-With':'XMLHttpRequest','User-Agent':ua}, method='POST')
                d2 = json.loads(opener.open(req2, timeout=15).read().decode())
                created = d2.get('serverMemo',{}).get('data',{}).get('email', email)
                if d2.get('effects',{}).get('redirect'):
                    opener.open(urllib.request.Request(d2['effects']['redirect'], headers={'User-Agent': ua}), timeout=15)
                return created, cj, lw_token
    except Exception as e:
        add_log(f'  ❌ Email error: {e}')
    return None, None, None

def poll_otp(cj, lw_token):
    """Poll imail mailbox for OTP."""
    ua = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    for i in range(15):
        time.sleep(5)
        try:
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            resp = opener.open(urllib.request.Request('https://imail.edu.vn/mailbox', headers={'User-Agent': ua}), timeout=15)
            content = resp.read().decode('utf-8')
            lwm = re.search(r"livewire_token\s*=\s*'([^']+)'", content)
            if lwm: lw_token = lwm.group(1)
            for mx in re.finditer(r'wire:id="([^"]+)"[^>]*wire:initial-data="([^"]+)"', content):
                dx = json.loads(hm.unescape(mx.group(2)))
                if dx.get('fingerprint',{}).get('name') == 'frontend.app':
                    def rd(): return ''.join(random.choices(string.ascii_lowercase+string.digits, k=5))
                    pl = {'fingerprint': dx['fingerprint'],'serverMemo': dx['serverMemo'],
                        'updates': [{'type':'fireEvent','payload':{'id':rd(),'event':'fetchMessages','params':[]}}]}
                    rq = urllib.request.Request('https://imail.edu.vn/livewire/message/frontend.app',
                        data=json.dumps(pl).encode(),
                        headers={'Content-Type':'application/json','X-CSRF-TOKEN':lw_token,'X-Livewire':'true','Accept':'application/json','X-Requested-With':'XMLHttpRequest','User-Agent':ua},method='POST')
                    d2 = json.loads(opener.open(rq, timeout=15).read().decode())
                    msgs = d2.get('serverMemo',{}).get('data',{}).get('messages',[])
                    if msgs:
                        code = re.search(r'(\d{4,8})', msgs[0].get('content',''))
                        if code: return code.group(1)
                    break
        except: pass
    return None

def register_one(domain, proxy, password, browser):
    """Register one DeepSeek account using proxy."""
    add_log(f'📧 Creating email ({domain})...')
    email, cj, lw_token = create_email(domain)
    if not email:
        add_log(f'  ❌ Email failed')
        return None
    
    add_log(f'  ✅ {email}')
    add_log(f'🌐 Signing up via proxy...')
    
    try:
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 Chrome/131.0.6778.200 Mobile Safari/537.36',
            viewport={'width': 390, 'height': 844}, locale='zh-CN',
            proxy=proxy,
        )
        ctx.add_init_script('Object.defineProperty(navigator, "webdriver", { get: () => undefined });')
        page = ctx.new_page()
        
        page.goto('https://chat.deepseek.com/', wait_until='commit', timeout=30000)
        time.sleep(8)
        
        page.locator('text=立即注册').first.click()
        time.sleep(2)
        
        inp = page.locator('input')
        inp.nth(0).fill(email); inp.nth(1).fill(password); inp.nth(2).fill(password)
        page.locator('text=发送验证码').first.click()
        time.sleep(5)
        
        text = page.evaluate('document.body?.innerText')
        if '验证码已发送' not in text and '秒后可再次获取' not in text:
            add_log(f'  ❌ Code send failed')
            ctx.close(); return None
        
        add_log(f'  ✅ Code sent, polling OTP...')
        otp = poll_otp(cj, lw_token)
        if not otp:
            add_log(f'  ❌ No OTP')
            ctx.close(); return None
        
        add_log(f'  🔑 OTP: {otp}')
        inp2 = page.locator('input')
        inp2.nth(3).fill(otp)
        page.locator('button:has-text("注册")').first.click()
        time.sleep(5)
        
        if 'chat' in page.url and 'sign' not in page.url.lower():
            add_log(f'  ✅✅ SUCCESS!')
            ctx.close()
            return (email, password)
        else:
            add_log(f'  ⚠️ Register issue')
            ctx.close()
            return None
    except Exception as e:
        add_log(f'  ❌ Error: {str(e)[:60]}')
        try: ctx.close()
        except: pass
        return None

def worker_thread(browser, proxy_config, password, target):
    """Worker thread processing queue items."""
    global worker_running
    domain_idx = 0
    completed = 0
    fails = 0
    
    while worker_running and completed < target:
        domain = DOMAINS[domain_idx % len(DOMAINS)]
        domain_idx += 1
        
        add_log(f'\n[{completed+1}/{target}] {domain}')
        
        proxy = proxy_config.next()
        proxy_label = proxy['server'] if proxy else 'direct'
        
        result = register_one(domain, proxy, password, browser)
        
        if result:
            email, pw = result
            save_account(email, pw, domain, proxy_label)
            completed += 1
            fails = 0
        else:
            fails += 1
            if fails >= 3:
                add_log(f'  ⚠️ 3 consecutive fails, stopping...')
                break
    
    worker_running = False
    add_log(f'\n{"="*40}')
    add_log(f'✅ Done: {completed} accounts')
    add_log(f'{"="*40}')

# === HTTP Server ===
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        
        if path == '/':
            self.send_html(INDEX_HTML)
        elif path == '/api/accounts':
            self.send_json(get_accounts())
        elif path == '/api/logs':
            with logs_lock:
                self.send_json(list(worker_logs))
        elif path == '/api/status':
            self.send_json({'running': worker_running, 'count': len(get_accounts())})
        elif path == '/api/config':
            self.send_json({
                'proxy': get_config('proxy', ''),
                'password': get_config('password', 'abcABC123@@'),
                'target': get_config('target', '10'),
                'workers': get_config('workers', '2'),
            })
        elif path == '/export/csv':
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv')
            self.send_header('Content-Disposition', 'attachment; filename="deepseek_accounts.csv"')
            self.end_headers()
            self.wfile.write(export_csv().encode())
        elif path == '/export/txt':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Disposition', 'attachment; filename="deepseek_accounts.txt"')
            self.end_headers()
            self.wfile.write(export_txt().encode())
        else:
            self.send_error(404)
    
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode() if length else '{}'
        data = json.loads(body) if body else {}
        
        if self.path == '/api/start':
            self.handle_start(data)
        elif self.path == '/api/stop':
            global worker_running
            worker_running = False
            self.send_json({'ok': True, 'msg': 'Stopping...'})
        elif self.path == '/api/clear':
            conn = sqlite3.connect(DB_FILE)
            conn.execute("DELETE FROM accounts")
            conn.commit()
            conn.close()
            global worker_logs
            with logs_lock: worker_logs = []
            self.send_json({'ok': True})
        elif self.path == '/api/save-config':
            for k in ['proxy', 'password', 'target', 'workers']:
                if k in data:
                    save_config(k, str(data[k]))
            self.send_json({'ok': True})
        else:
            self.send_json({'error': 'unknown'})
    
    def handle_start(self, data):
        global worker_running, proxy_config
        if worker_running:
            self.send_json({'ok': False, 'msg': 'Already running'})
            return
        
        # Save config
        proxy_str = data.get('proxy', get_config('proxy', ''))
        password = data.get('password', get_config('password', 'abcABC123@@'))
        target = int(data.get('target', get_config('target', '10')))
        workers = int(data.get('workers', get_config('workers', '2')))
        
        save_config('proxy', proxy_str)
        save_config('password', password)
        save_config('target', str(target))
        save_config('workers', str(workers))
        
        proxy_config = ProxyConfig(proxy_str)
        worker_running = True
        
        with logs_lock:
            worker_logs.clear()
        add_log(f'🚀 Starting: {target} accounts, {workers} workers')
        add_log(f'📋 Proxy: {len(proxy_config.proxies)} configured')
        
        # Start worker threads
        def run():
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
                    threads = []
                    per_worker = max(1, target // workers)
                    for w in range(workers):
                        t = threading.Thread(target=worker_thread, args=(browser, proxy_config, password, per_worker), daemon=True)
                        t.start()
                        threads.append(t)
                    for t in threads:
                        t.join()
                    browser.close()
            except Exception as e:
                add_log(f'❌ Fatal: {e}')
                global worker_running
                worker_running = False
        
        t = threading.Thread(target=run, daemon=True)
        t.start()
        
        self.send_json({'ok': True, 'msg': f'Started {workers} workers, target {target}'})
    
    def send_html(self, html):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args): pass

# === HTML UI ===
INDEX_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DeepSeek Account Creator</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5;color:#333;padding:20px}
.container{max-width:1200px;margin:0 auto}
h1{color:#1a1a2e;margin-bottom:20px}
.card{background:#fff;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,.1);padding:20px;margin-bottom:20px}
.card h2{font-size:16px;margin-bottom:15px;color:#1a1a2e}
.form-row{display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.form-row label{min-width:100px;font-size:13px;color:#666;padding-top:8px}
.form-row input,.form-row textarea{flex:1;padding:8px 12px;border:1px solid #ddd;border-radius:4px;font-size:13px}
.form-row textarea{min-height:80px;font-family:monospace;font-size:12px}
.form-row input[type=number]{max-width:100px}
.btn{padding:10px 24px;border:none;border-radius:4px;cursor:pointer;font-size:14px;font-weight:500}
.btn-primary{background:#4f46e5;color:#fff}
.btn-primary:hover{background:#4338ca}
.btn-danger{background:#ef4444;color:#fff}
.btn-success{background:#10b981;color:#fff}
.btn-sm{padding:6px 14px;font-size:12px}
.btn:disabled{opacity:.5;cursor:not-allowed}
.actions{display:flex;gap:10px;margin-top:15px;flex-wrap:wrap}
.log-box{background:#1a1a2e;color:#0f0;padding:12px;border-radius:4px;font-family:monospace;font-size:12px;height:300px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #eee}
th{background:#f8f8f8;font-weight:600;position:sticky;top:0}
.table-wrap{max-height:400px;overflow-y:auto}
.status-bar{display:flex;gap:20px;margin-bottom:15px;flex-wrap:wrap}
.stat{background:#fff;border-radius:8px;padding:15px 20px;box-shadow:0 2px 4px rgba(0,0,0,.1);flex:1;min-width:120px;text-align:center}
.stat-value{font-size:28px;font-weight:700;color:#4f46e5}
.stat-label{font-size:12px;color:#666;margin-top:4px}
.running .stat-value{color:#10b981}
.stopped .stat-value{color:#ef4444}
</style>
</head>
<body>
<div class="container">
<h1>🚀 DeepSeek Account Creator</h1>

<div class="status-bar" id="statusBar">
  <div class="stat"><div class="stat-value" id="totalAccounts">0</div><div class="stat-label">Total Accounts</div></div>
  <div class="stat" id="statusIndicator"><div class="stat-value" id="workerStatus">⏹️</div><div class="stat-label">Status</div></div>
</div>

<div class="card">
  <h2>⚙️ Configuration</h2>
  <div class="form-row">
    <label>Proxy List</label>
    <textarea id="proxyInput" placeholder="user:pass@host:port&#10;user2:pass2@host2:port2"></textarea>
  </div>
  <div class="form-row">
    <label>Password</label>
    <input type="text" id="passwordInput" value="abcABC123@@">
  </div>
  <div class="form-row">
    <label>Target</label>
    <input type="number" id="targetInput" value="10" min="1" max="100">
    <label>Workers</label>
    <input type="number" id="workersInput" value="2" min="1" max="5">
  </div>
  <div class="actions">
    <button class="btn btn-primary" id="btnStart" onclick="start()">▶ Start</button>
    <button class="btn btn-danger" id="btnStop" onclick="stop()" disabled>⏹ Stop</button>
    <button class="btn btn-sm" onclick="clearAll()">🗑 Clear</button>
  </div>
</div>

<div class="card">
  <h2>📋 Logs</h2>
  <div class="log-box" id="logBox">Ready. Configure proxy and press Start.</div>
</div>

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:10px">
    <h2 style="margin:0">📊 Accounts</h2>
    <div>
      <button class="btn btn-success btn-sm" onclick="exportCSV()">📥 CSV</button>
      <button class="btn btn-success btn-sm" onclick="exportTXT()">📥 TXT</button>
    </div>
  </div>
  <div class="table-wrap" id="accountsTableWrap">
    <table><thead><tr><th>Email</th><th>Password</th><th>Domain</th><th>Proxy</th><th>Status</th><th>Created</th></tr></thead>
    <tbody id="accountsBody"></tbody></table>
  </div>
</div>
</div>

<script>
let pollTimer = null;

function loadConfig() {
  fetch('/api/config').then(r=>r.json()).then(d=>{
    document.getElementById('proxyInput').value = d.proxy || '';
    document.getElementById('passwordInput').value = d.password || 'abcABC123@@';
    document.getElementById('targetInput').value = d.target || '10';
    document.getElementById('workersInput').value = d.workers || '2';
  });
}

function start() {
  const data = {
    proxy: document.getElementById('proxyInput').value,
    password: document.getElementById('passwordInput').value,
    target: parseInt(document.getElementById('targetInput').value) || 10,
    workers: parseInt(document.getElementById('workersInput').value) || 2,
  };
  fetch('/api/save-config', {method:'POST',body:JSON.stringify(data)});
  fetch('/api/start', {method:'POST',body:JSON.stringify(data)}).then(r=>r.json()).then(d=>{
    if(d.ok) { pollTimer = setInterval(poll, 1000); updateButtons(true); }
    else alert(d.msg);
  });
}

function stop() {
  fetch('/api/stop',{method:'POST'}).then(()=>{updateButtons(false)});
}

function clearAll() {
  if(!confirm('Clear all accounts?')) return;
  fetch('/api/clear',{method:'POST'}).then(()=>{loadAccounts();loadLogs()});
}

function poll() {
  fetch('/api/status').then(r=>r.json()).then(d=>{
    document.getElementById('totalAccounts').textContent = d.count;
    if(!d.running) { clearInterval(pollTimer); pollTimer=null; updateButtons(false); }
  });
  loadLogs();
  loadAccounts();
}

function loadLogs() {
  fetch('/api/logs').then(r=>r.json()).then(logs=>{
    const box = document.getElementById('logBox');
    box.innerHTML = logs.join('\n');
    box.scrollTop = box.scrollHeight;
  });
}

function loadAccounts() {
  fetch('/api/accounts').then(r=>r.json()).then(rows=>{
    const tbody = document.getElementById('accountsBody');
    tbody.innerHTML = rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td style="font-size:11px">${r[3]||'direct'}</td><td>${r[4]||'created'}</td><td>${r[5]||''}</td></tr>`).join('');
    document.getElementById('totalAccounts').textContent = rows.length;
  });
}

function exportCSV() { window.location = '/export/csv'; }
function exportTXT() { window.location = '/export/txt'; }

function updateButtons(running) {
  document.getElementById('btnStart').disabled = running;
  document.getElementById('btnStop').disabled = !running;
  document.getElementById('workerStatus').textContent = running ? '▶ Running' : '⏹ Stopped';
  document.getElementById('statusIndicator').className = running ? 'stat running' : 'stat stopped';
}

loadConfig();
loadAccounts();
setInterval(loadLogs,3000);
setInterval(loadAccounts,5000);
</script>
</body>
</html>"""

# === Main ===
if __name__ == '__main__':
    init_db()
    print(f'🚀 DeepSeek Account Creator')
    print(f'📁 DB: {DB_FILE}')
    print(f'🌐 http://{HOST}:{PORT}')
    
    server = HTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n👋 Bye!')
        server.shutdown()
