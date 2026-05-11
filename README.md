# DeepSeek Account Registration Bot

Automatically creates DeepSeek accounts using temporary emails + Playwright browser automation.

## How it works

1. **Create temp email** via imail.edu.vn Livewire protocol (free, no captcha)
2. **Open DeepSeek signup** in Playwright (mobile UA bypasses CloudFront WAF)
3. **Request verification code** → DeepSeek sends OTP to temp email
4. **Poll imail inbox** for OTP code
5. **Submit OTP** → account created!

## Usage

### Option 1: GitHub Actions (recommended, free)

Push to GitHub, then run:

```
gh workflow run create_accounts.yml -f count=10
```

Each job runs on a separate GitHub runner (unique IP), creating 1 account each.
Artifacts contain all credentials.

### Option 2: Local with proxy rotation

```bash
pip install -r requirements.txt
python proxy_rotator.py   # finds working proxies
python register_account.py  # creates accounts
```

### Option 3: Local directly

```bash
pip install playwright
playwright install chromium
python register_account.py
```

## Domains that work with DeepSeek

| Domain | Status |
|--------|--------|
| newdelhi.io.vn | ✅ Working |
| mailo.edu.pl | ✅ Working |
| nik.edu.pl | ✅ Working |
| gddp2018.edu.vn | ✅ Working |
| itmo.edu.pl | ✅ Working |
| mailer.edu.pl | ✅ Working |
| newyork.io.vn | ✅ Working |
| dulieu.io.vn | ✅ Working |
| jakarta.io.vn | ✅ Working |
| imail.edu.vn | ❌ Blocked |
| apple.edu.pl | ❌ Blocked |
| mailer.io.vn | ⚠️ Unknown |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| DS_PASSWORD | abcABC123@@ | Password for all accounts |
| DS_DOMAIN | random | Specific domain to use |
| DS_DOMAINS | all working | Comma-separated domain list |
