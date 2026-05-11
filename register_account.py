#!/usr/bin/env python3
"""
Fast DeepSeek Account Registration - optimized for bulk creation.
"""
import json, re, time, random, string, html as hm, http.cookiejar, urllib.request, os, sys

PASSWORD = os.environ.get('DS_PASSWORD', 'abcABC123@@')
DOMAINS = 'newdelhi.io.vn,mailo.edu.pl,nik.edu.pl,gddp2018.edu.vn,itmo.edu.pl,mailer.edu.pl,newyork.io.vn,dulieu.io.vn,jakarta.io.vn'.split(',')
MAX_RETRIES = 2
WORKDIR = os.environ.get('WORKDIR', '/tmp')
OUTPUT_FILE = os.path.join(WORKDIR, 'accounts.txt')

def create_email(domain):
    ua = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
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
                
                safe = domain.replace('.', '_')
                mj = http.cookiejar.MozillaCookieJar(f'/tmp/cookies_{safe}_{uname}_{os.getpid()}.txt')
                for ck in cj: mj.set_cookie(ck)
                mj.save(ignore_discard=True, ignore_expires=True)
                
                with open(f'/tmp/lw_{safe}_{uname}_{os.getpid()}.txt', 'w') as f: f.write(lw_token)
                
                return created, cj, lw_token
    except Exception as e:
        print(f'  ❌ Email: {e}', file=sys.stderr)
    return None, None, None

def poll_otp(cj, lw_token):
    ua = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    start = time.time()
    while time.time() - start < 45:
        time.sleep(3)
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
                    rq = urllib.request.Request(
                        'https://imail.edu.vn/livewire/message/frontend.app',
                        data=json.dumps(pl).encode(),
                        headers={'Content-Type':'application/json','X-CSRF-TOKEN':lw_token,'X-Livewire':'true','Accept':'application/json','X-Requested-With':'XMLHttpRequest','User-Agent':ua},
                        method='POST'
                    )
                    d2 = json.loads(opener.open(rq, timeout=15).read().decode())
                    msgs = d2.get('serverMemo',{}).get('data',{}).get('messages',[])
                    if msgs:
                        for msg in msgs:
                            cr = msg.get('content', '')
                            m = re.search(r'code-text[^>]*>.*?font-size:\s*76px[^>]*>\s*(\d+)\s*<', cr, re.DOTALL)
                            if m:
                                print(f'  📧 {m.group(1)}')
                                return m.group(1)
                            m2 = re.search(r'(\d{5,8})', cr)
                            if m2:
                                print(f'  📧 {m2.group(1)}')
                                return m2.group(1)
                    break
        except: pass
    return None

def register_one(domain):
    from playwright.sync_api import sync_playwright
    
    for attempt in range(MAX_RETRIES):
        email, cj, lw_token = create_email(domain)
        if not email: continue
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                ctx = browser.new_context(
                    user_agent='Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 Chrome/131.0.6778.200 Mobile Safari/537.36',
                    viewport={'width': 390, 'height': 844}, locale='zh-CN',
                )
                ctx.add_init_script('Object.defineProperty(navigator, "webdriver", { get: () => undefined });')
                page = ctx.new_page()
                
                page.goto('https://chat.deepseek.com/sign_up', wait_until='domcontentloaded', timeout=30000)
                time.sleep(1)
                if 'sign_up' not in page.url:
                    page.locator('text=立即注册').first.click()
                    time.sleep(0.5)
                
                inp = page.locator('input')
                inp.nth(0).fill(email)
                inp.nth(1).fill(PASSWORD)
                inp.nth(2).fill(PASSWORD)
                page.locator('text=发送验证码').first.click()
                time.sleep(2)
                
                text = page.evaluate('document.body?.innerText')
                if '暂不支持' in text:
                    ctx.close(); browser.close(); break
                if '验证码已发送' not in text and '秒后可再次获取' not in text:
                    ctx.close(); browser.close(); continue
                
                otp = poll_otp(cj, lw_token)
                if otp:
                    page.locator('input').nth(3).fill(otp)
                    time.sleep(0.3)
                    
                    try:
                        btn = page.locator('button:has-text("注册")').first
                        btn.scroll_into_view_if_needed()
                        btn.click(force=True, timeout=10000)
                    except:
                        try:
                            page.evaluate("document.querySelector('button:not([disabled])').click()")
                        except: pass
                    
                    try:
                        page.wait_for_url('**/chat**', timeout=10000)
                        ctx.close(); browser.close()
                        with open(OUTPUT_FILE, 'a') as f:
                            f.write(f'{email}|{PASSWORD}\n')
                        print(f'  ✅ {email}|{PASSWORD}')
                        return 0
                    except:
                        pass
                
                ctx.close(); browser.close()
        except Exception as e:
            print(f'  ⚠️ {str(e)[:50]}')
            continue
    
    return 1

def main():
    domain = os.environ.get('DS_DOMAIN', '')
    if domain and domain in DOMAINS:
        domains = [domain]
    else:
        domains = DOMAINS[:]
        random.shuffle(domains)
    
    for d in domains:
        if register_one(d.strip()) == 0:
            return 0
    return 1

if __name__ == '__main__':
    sys.exit(main())
