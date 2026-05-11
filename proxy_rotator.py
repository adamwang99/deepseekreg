#!/usr/bin/env python3
"""
Free Proxy Rotator for DeepSeek Registration.
Crawls free proxy lists, validates them with DeepSeek, provides working proxies.
"""
import json, re, time, random, threading, urllib.request, urllib.error, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

PROXY_SOURCES = [
    {
        'name': 'free-proxy-list',
        'url': 'https://free-proxy-list.net/',
        'parser': 'html_table'
    },
    {
        'name': 'proxyscrape',
        'url': 'https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all',
        'parser': 'raw_list'
    },
    {
        'name': 'proxylist',
        'url': 'https://www.proxy-list.download/api/v1/get?type=http',
        'parser': 'raw_list'
    },
    {
        'name': 'geonode',
        'url': 'https://proxylist.geonode.com/api/proxy-list?limit=50&page=1&sort_by=lastChecked&sort_type=desc',
        'parser': 'json'
    },
]

class ProxyRotator:
    def __init__(self, min_working=5):
        self.working_proxies = []
        self.lock = threading.Lock()
        self.min_working = min_working
        self.ua = 'Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36'
    
    def crawl_free_proxies(self):
        """Crawl free proxy lists."""
        all_proxies = set()
        print('[*] Crawling free proxy lists...')
        
        for source in PROXY_SOURCES:
            try:
                req = urllib.request.Request(source['url'], headers={'User-Agent': self.ua})
                resp = urllib.request.urlopen(req, timeout=10)
                data = resp.read().decode('utf-8', errors='ignore')
                
                if source['parser'] == 'raw_list':
                    for line in data.split('\n'):
                        line = line.strip()
                        if ':' in line and len(line) < 30:
                            all_proxies.add(line)
                
                elif source['parser'] == 'html_table':
                    # Simple IP:port extraction from HTML
                    ips = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5})', data)
                    all_proxies.update(ips)
                
                elif source['parser'] == 'json':
                    try:
                        jd = json.loads(data)
                        for item in jd.get('data', []):
                            p = f"{item.get('ip','')}:{item.get('port','')}"
                            if ':' in p:
                                all_proxies.add(p)
                    except: pass
                
                print(f'  ✓ {source["name"]}: found {len([p for p in all_proxies])} total')
            except Exception as e:
                print(f'  ✗ {source["name"]}: {str(e)[:40]}')
        
        print(f'\n[*] Total unique proxies: {len(all_proxies)}')
        return list(all_proxies)
    
    def validate_proxy(self, proxy_str):
        """Test if a proxy works with DeepSeek."""
        try:
            proxy_handler = urllib.request.ProxyHandler({'http': f'http://{proxy_str}', 'https': f'http://{proxy_str}'})
            opener = urllib.request.build_opener(proxy_handler, urllib.request.ProxyBasicAuthHandler())
            
            # First check if proxy is alive
            start = time.time()
            resp = opener.open(urllib.request.Request('http://httpbin.org/ip', headers={'User-Agent': self.ua}), timeout=10)
            resp.read()
            latency = time.time() - start
            
            # Then test with DeepSeek
            ds_resp = opener.open(urllib.request.Request(
                'https://chat.deepseek.com/api/v0/users/login',
                headers={
                    'User-Agent': 'DeepSeek/2.0.4 Android/35',
                    'Content-Type': 'application/json',
                    'x-client-platform': 'android',
                    'x-client-version': '2.0.4',
                    'Accept': 'application/json',
                },
                data=json.dumps({"email":"test@test.com","password":"test","device_id":"test","os":"android"}).encode()
            ), timeout=10)
            result = json.loads(ds_resp.read().decode())
            
            # Login endpoint should return biz_code, not error
            if 'biz_code' in str(result):
                return {'proxy': proxy_str, 'latency': round(latency, 2), 'works': True}
                
        except: pass
        return None
    
    def get_working_proxies(self, count=5):
        """Get N working proxies, crawling + validating as needed."""
        with self.lock:
            if len(self.working_proxies) >= count:
                return random.sample(self.working_proxies, count)
        
        # Crawl fresh proxies
        all_proxies = self.crawl_free_proxies()
        if not all_proxies:
            print('[!] No proxies found from any source')
            return []
        
        # Validate in parallel
        print(f'\n[*] Validating proxies (testing with DeepSeek)...')
        working = []
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(self.validate_proxy, p): p for p in all_proxies[:100]}
            for i, future in enumerate(as_completed(futures)):
                result = future.result()
                if result and result['works']:
                    working.append(result)
                    print(f'  ✓ {result["proxy"]} (latency: {result["latency"]}s)')
                
                if (i+1) % 20 == 0:
                    print(f'  Progress: {i+1}/{min(100, len(all_proxies))} tested, {len(working)} working')
        
        with self.lock:
            self.working_proxies = working
        
        print(f'\n[*] Working proxies: {len(working)}')
        if working:
            return random.sample(working, min(count, len(working)))
        return []

    def get_next_proxy(self):
        """Get next working proxy (round-robin)."""
        with self.lock:
            if not self.working_proxies:
                return None
            proxy = random.choice(self.working_proxies)
        return f'http://{proxy["proxy"]}'


def main():
    rotator = ProxyRotator()
    proxies = rotator.get_working_proxies(count=5)
    
    if proxies:
        print(f'\n✅ {len(proxies)} working proxies found:')
        for p in proxies:
            print(f'  http://{p["proxy"]} (latency: {p["latency"]}s)')
    else:
        print('\n❌ No working proxies found')
        print('  -> Try running again later or use GitHub Actions')

if __name__ == '__main__':
    main()
