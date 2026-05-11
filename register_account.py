#!/usr/bin/env python3
"""
DeepSeek Account Registration Bot
Creates accounts using temp email + DeepSeek signup via Playwright.
Designed to run on GitHub Actions (each run = unique IP).
"""
import json, re, time, random, string, html as hm, http.cookiejar, urllib.request, os, sys

# === CONFIG ===
PASSWORD = os.environ.get('DS_PASSWORD', 'abcABC123@@')
DOMAINS = os.environ.get('DS_DOMAINS', 'newdelhi.io.vn,mailo.edu.pl,nik.edu.pl,gddp2018.edu.vn,itmo.edu.pl,mailer.edu.pl,newyork.io.vn,dulieu.io.vn,jakarta.io.vn').split(',')
MAX_RETRIES = 3
OUTPUT_FILE = 'accounts.txt'

def create_email(domain):
    """Create temp email via imail.edu.vn Livewire protocol."""
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
                
                # Save cookies for inbox polling
                safe = domain.replace('.', '_')
                mj = http.cookiejar.MozillaCookieJar(f'/tmp/cookies_{safe}_{uname}.txt')
                for ck in cj: mj.set_cookie(ck)
                mj.save(ignore_discard=True, ignore_expires=True)
                
                with open(f'/tmp/lw_{safe}_{uname}.txt', 'w') as f: f.write(lw_token)
                
                return created, cj, lw_token
    except Exception as e:
        print(f'  ❌ Email creation error: {e}', file=sys.stderr)
    return None, None, None

def poll_otp(cj, lw_token, timeout_secs=60):
    """Poll imail.edu.vn mailbox for OTP."""
    ua = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    polls = timeout_secs // 5
    
    for i in range(polls):
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
                            code = re.search(r'(\d{4,8})', cr)
                            if code:
                                print(f'  📧 OTP: {code.group(1)}')
                                return code.group(1)
                    break
        except: pass
        print(f'  Poll {i+1}/{polls}...', end=' ')
    
    return None

def click_register_button(page):
    """Click register button with multiple fallback strategies."""
    import time
    
    # Strategy 1: Playwright click with scroll + force
    try:
        btn = page.locator('button:has-text("注册")').first
        if btn.count() > 0:
            btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            btn.click(force=True, timeout=10000)
            return True
    except Exception as e:
        print(f'  ⚠️ Strategy 1 failed: {str(e)[:60]}')
    
    # Strategy 2: get_by_role
    try:
        btn = page.get_by_role("button", name="注册")
        if btn.count() > 0:
            btn.first.scroll_into_view_if_needed()
            time.sleep(0.5)
            btn.first.click(force=True, timeout=10000)
            return True
    except Exception as e:
        print(f'  ⚠️ Strategy 2 failed: {str(e)[:60]}')
    
    # Strategy 3: XPath
    try:
        btn = page.locator('//button[contains(text(), "注册")]')
        if btn.count() > 0:
            btn.first.scroll_into_view_if_needed()
            time.sleep(0.5)
            btn.first.click(force=True, timeout=10000)
            return True
    except Exception as e:
        print(f'  ⚠️ Strategy 3 failed: {str(e)[:60]}')
    
    # Strategy 4: JavaScript click
    try:
        page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.includes('注册') && b.offsetParent !== null) {
                    b.click();
                    return true;
                }
            }
            return false;
        }''')
        return True
    except Exception as e:
        print(f'  ⚠️ Strategy 4 failed: {str(e)[:60]}')
    
    return False

def register_account(domain):
    """Full registration flow for one account."""
    from playwright.sync_api import sync_playwright
    
    print(f'\n{"="*50}')
    print(f'Registering: {domain}')
    print(f'{"="*50}')
    
    for attempt in range(MAX_RETRIES):
        print(f'\nAttempt {attempt+1}/{MAX_RETRIES}...')
        
        # Step 1: Create email
        email, cj, lw_token = create_email(domain)
        if not email:
            print('  ❌ Email creation failed')
            continue
        print(f'  ✅ Email: {email}')
        
        # Step 2: Open DeepSeek browser signup
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                ctx = browser.new_context(
                    user_agent='Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 Chrome/131.0.6778.200 Mobile Safari/537.36',
                    viewport={'width': 390, 'height': 844}, locale='zh-CN',
                )
                ctx.add_init_script('Object.defineProperty(navigator, "webdriver", { get: () => undefined });')
                page = ctx.new_page()
                
                # Go directly to signup page
                page.goto('https://chat.deepseek.com/sign_up', wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)
                
                # If redirected to home page, click 立即注册
                if 'sign_up' not in page.url:
                    page.locator('text=立即注册').first.click()
                    time.sleep(2)
                
                inp = page.locator('input')
                inp.nth(0).fill(email)
                inp.nth(1).fill(PASSWORD)
                inp.nth(2).fill(PASSWORD)
                page.locator('text=发送验证码').first.click()
                time.sleep(3)
                
                text = page.evaluate('document.body?.innerText')
                
                if '暂不支持' in text:
                    print(f'  ❌ Domain {domain} BLOCKED')
                    ctx.close()
                    browser.close()
                    break  # Don't retry - domain won't work
                
                if '验证码已发送' not in text and '秒后可再次获取' not in text:
                    print(f'  ⚠️ Form may have failed: {text[:80]}')
                    ctx.close()
                    browser.close()
                    continue
                
                print(f'  ✅ Code sent, polling OTP...')
                
                # Step 3: Poll for OTP
                otp = poll_otp(cj, lw_token)
                
                if otp:
                    print(f'  ✅ OTP: {otp}')
                    inp2 = page.locator('input')
                    inp2.nth(3).fill(otp)
                    time.sleep(1)  # Wait before clicking
                    
                    # Click register with fallbacks
                    clicked = click_register_button(page)
                    if not clicked:
                        print('  ❌ Could not click register button')
                        ctx.close()
                        browser.close()
                        continue
                    
                    time.sleep(5)
                    
                    page.screenshot(path=f'/tmp/ds_result_{domain.replace(".","_")}.png')
                    
                    if 'chat' in page.url and 'sign' not in page.url.lower():
                        print(f'\n  ✅✅ REGISTRATION SUCCESS!')
                        print(f'  {email} | {PASSWORD}')
                        ctx.close()
                        browser.close()
                        return email, PASSWORD
                    else:
                        result_text = page.evaluate('document.body?.innerText?.substring(0, 200)')
                        print(f'  ⚠️ Registration issue: {result_text[:100]}')
                        ctx.close()
                        browser.close()
                        continue
                else:
                    print(f'  ❌ No OTP received')
                    ctx.close()
                    browser.close()
                    continue
                    
        except Exception as e:
            print(f'  ❌ Error: {str(e)[:80]}')
            continue
    
    return None, None

def main():
    # Read which domain to use from env or use random
    domain_str = os.environ.get('DS_DOMAIN', '')
    if domain_str and domain_str in DOMAINS:
        domains_to_use = [domain_str]
    else:
        domains_to_use = DOMAINS[:]
        random.shuffle(domains_to_use)
    
    print(f'Password: {PASSWORD}')
    print(f'Domains available: {DOMAINS}')
    
    for domain in domains_to_use:
        email, pw = register_account(domain.strip())
        if email:
            # Save to output
            with open(OUTPUT_FILE, 'a') as f:
                f.write(f'{email}|{pw}\n')
            print(f'\n✅ Account saved to {OUTPUT_FILE}')
            return 0
    
    print('\n❌ All domains failed')
    return 1

if __name__ == '__main__':
    sys.exit(main())
