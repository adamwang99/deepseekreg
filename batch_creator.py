#!/usr/bin/env python3
"""
DeepSeek Batch Account Creator with Proxy Rotation.
Tạo nhiều tài khoản tự động, rotate IP mỗi 2 accounts.
"""
import json, re, time, random, string, html as hm, http.cookiejar, urllib.request, sys, os, threading
from playwright.sync_api import sync_playwright

# === CONFIG ===
PASSWORD = "abcABC123@@"
PROXY_AUTH = "http://lylienkiet19001015:04BGmwMnoqVif4R@ip.mproxy.vn:12313"
PROXY_USER = "lylienkiet19001015"
PROXY_PASS = "04BGmwMnoqVif4R"
PROXY_HOST = "ip.mproxy.vn"
PROXY_PORT = 12313
ROTATE_URL = "https://mproxy.vn/capi/4oBNzlb6InSq_-MoxbS5CJJubsq-iAM4qU0uW9-gDvA/key/04BGmwMnoqVif4R/resetIp"
ACCOUNTS_FILE = "deepseek_accounts.txt"
TARGET_COUNT = int(os.environ.get('TARGET', '50'))
BATCH_SIZE = 2  # Accounts per IP before rotate

DOMAINS = [
    "newdelhi.io.vn", "mailo.edu.pl", "nik.edu.pl", "gddp2018.edu.vn",
    "itmo.edu.pl", "mailer.edu.pl", "newyork.io.vn", "dulieu.io.vn", "jakarta.io.vn",
]

# Track used domains
used_domains = {}
domain_lock = threading.Lock()

def rotate_ip():
    """Rotate proxy IP. Returns True if successful."""
    try:
        resp = urllib.request.urlopen(urllib.request.Request(ROTATE_URL), timeout=15)
        data = json.loads(resp.read().decode())
        if data.get('status') == 1:
            time.sleep(1)  # Wait for IP change
            return True
    except: pass
    return False

def create_email(domain, opener):
    """Create temp email using existing opener (for cookie reuse)."""
    ua = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    try:
        resp = opener.open(urllib.request.Request('https://imail.edu.vn/', headers={'User-Agent': ua}), timeout=15)
        content = resp.read().decode('utf-8')
        lw_token = ''
        lwm = re.search(r"livewire_token\s*=\s*'([^']+)'", content)
        if lwm: lw_token = lwm.group(1)
        
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
                
                req2 = urllib.request.Request(
                    'https://imail.edu.vn/livewire/message/frontend.actions',
                    data=json.dumps(payload).encode(),
                    headers={'Content-Type':'application/json','X-CSRF-TOKEN':lw_token,'X-Livewire':'true','Accept':'application/json','X-Requested-With':'XMLHttpRequest','User-Agent':ua},
                    method='POST'
                )
                d2 = json.loads(opener.open(req2, timeout=15).read().decode())
                created = d2.get('serverMemo',{}).get('data',{}).get('email', email)
                
                if d2.get('effects',{}).get('redirect'):
                    opener.open(urllib.request.Request(d2['effects']['redirect'], headers={'User-Agent': ua}), timeout=15)
                
                return created, cj, lw_token
    except: pass
    return None, None, None

def poll_otp(cj, lw_token, timeout=60):
    """Poll imail mailbox for OTP."""
    ua = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    for i in range(timeout // 5):
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
                    pl = {'fingerprint': dx['fingerprint'], 'serverMemo': dx['serverMemo'],
                        'updates': [{'type':'fireEvent','payload':{'id':rd(),'event':'fetchMessages','params':[]}}]}
                    rq = urllib.request.Request('https://imail.edu.vn/livewire/message/frontend.app',
                        data=json.dumps(pl).encode(),
                        headers={'Content-Type':'application/json','X-CSRF-TOKEN':lw_token,'X-Livewire':'true','Accept':'application/json','X-Requested-With':'XMLHttpRequest','User-Agent':ua},
                        method='POST')
                    d2 = json.loads(opener.open(rq, timeout=15).read().decode())
                    msgs = d2.get('serverMemo',{}).get('data',{}).get('messages',[])
                    if msgs:
                        code = re.search(r'(\d{4,8})', msgs[0].get('content',''))
                        if code: return code.group(1)
                    break
        except: pass
    return None

def get_next_domain():
    """Get domain with least usage."""
    with domain_lock:
        if not used_domains:
            for d in DOMAINS: used_domains[d] = 0
        min_domain = min(used_domains, key=used_domains.get)
        used_domains[min_domain] += 1
        return min_domain

def create_one_account(browser, domain):
    """Create one DeepSeek account. Returns (email, password) or None."""
    ua_web = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    
    # Step 1: Create email
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    email, _, lw_token = create_email(domain, opener)
    if not email:
        print(f'  ❌ Email fail for {domain}')
        return None
    print(f'  📧 {email}')
    
    # Step 2: DeepSeek signup via proxy
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 Chrome/131.0.6778.200 Mobile Safari/537.36',
        viewport={'width': 390, 'height': 844}, locale='zh-CN',
        proxy={'server': f'http://{PROXY_HOST}:{PROXY_PORT}', 'username': PROXY_USER, 'password': PROXY_PASS},
    )
    ctx.add_init_script('Object.defineProperty(navigator, "webdriver", { get: () => undefined });')
    page = ctx.new_page()
    
    try:
        page.goto('https://chat.deepseek.com/', wait_until='commit', timeout=30000)
        time.sleep(8)  # CloudFront challenge resolve
        
        page.locator('text=立即注册').first.click()
        time.sleep(2)
        
        inp = page.locator('input')
        inp.nth(0).fill(email)
        inp.nth(1).fill(PASSWORD)
        inp.nth(2).fill(PASSWORD)
        page.locator('text=发送验证码').first.click()
        time.sleep(5)
        
        text = page.evaluate('document.body?.innerText')
        if '验证码已发送' not in text and '秒后可再次获取' not in text:
            print(f'  ⚠️ Code send failed')
            ctx.close()
            return None
        
        print(f'  ✅ Code sent')
        
        # Step 3: Poll OTP (direct, no proxy)
        otp = poll_otp(cj, lw_token)
        if not otp:
            print(f'  ❌ No OTP')
            ctx.close()
            return None
        
        print(f'  🔑 OTP: {otp}')
        
        # Step 4: Complete
        inp2 = page.locator('input')
        inp2.nth(3).fill(otp)
        page.locator('button:has-text("注册")').first.click()
        time.sleep(5)
        
        if 'chat' in page.url and 'sign' not in page.url.lower():
            print(f'  ✅✅ SUCCESS!')
            ctx.close()
            return (email, PASSWORD)
        else:
            print(f'  ⚠️ Register issue')
            ctx.close()
            return None
    except Exception as e:
        print(f'  ❌ Error: {str(e)[:60]}')
        ctx.close()
        return None

def main():
    print(f'{"="*50}')
    print(f'DeepSeek Account Creator')
    print(f'Target: {TARGET_COUNT} accounts')
    print(f'Proxy: {PROXY_HOST}:{PROXY_PORT}')
    print(f'Batch: {BATCH_SIZE} accounts/IP')
    print(f'{"="*50}')
    
    accounts_created = len(open(ACCOUNTS_FILE).read().splitlines()) if os.path.exists(ACCOUNTS_FILE) else 0
    completed = 0
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        
        while completed < TARGET_COUNT:
            # Rotate IP every BATCH_SIZE accounts
            if completed % BATCH_SIZE == 0 and completed > 0:
                print(f'\n🔄 Rotating IP...')
                rotate_ip()
                time.sleep(3)
            
            # Get domain
            domain = get_next_domain()
            
            print(f'\n[{completed+1}/{TARGET_COUNT}] {domain}')
            
            result = create_one_account(browser, domain)
            
            if result:
                email, pw = result
                with open(ACCOUNTS_FILE, 'a') as f:
                    f.write(f'{email}|{pw}\n')
                completed += 1
                print(f'  💾 Saved ({completed} total)')
            else:
                print(f'  ⏭️ Retry with new IP...')
                rotate_ip()
                time.sleep(3)
                # Try again with different domain
                domain2 = get_next_domain()
                result2 = create_one_account(browser, domain2)
                if result2:
                    email2, pw2 = result2
                    with open(ACCOUNTS_FILE, 'a') as f:
                        f.write(f'{email2}|{pw2}\n')
                    completed += 1
                    print(f'  💾 Saved ({completed} total)')
        
        browser.close()
    
    print(f'\n{"="*50}')
    print(f'✅ Hoàn thành: {completed} accounts')
    print(f'📁 {ACCOUNTS_FILE}')
    print(f'{"="*50}')

if __name__ == '__main__':
    main()
