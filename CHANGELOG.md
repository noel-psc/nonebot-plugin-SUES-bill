## v1.1.3 (2026-07-22)

### Fix

- refresh the current electricity balance before estimating today's usage
- comply with NoneBot configuration and localstore APIs
- settle all recorded rooms together at 00:00 without staggering

## v1.1.1 (2026-07-21)

### Fix

- query the current electricity balance by default and persist room readings

## v1.1.0 (2026-07-21)

### Feat

- add SQLite-backed electricity usage history and daily settlement
- add electricity record settings, payment-account binding, and period statistics

## v1.0.6 (2026-07-07)

### Fix

- add require() for nonebot_plugin_localstore before import

## v1.0.5 (2026-07-07)

### Fix

- ignore extra env vars in Config to prevent validation error

### Refactor

- code review fixes

## v1.0.4 (2026-07-07)

### Fix

- add # prefix to campus card commands in help messages, remove unused constant
- use per-user campus card account storage

### Refactor

- migrate requests to httpx, add Config class, rewrite README

## v1.0.2 (2026-07-07)

## v1.0.3 (2026-07-07)

### Fix

- share session between login and query

## v1.0.1 (2026-07-07)

### Fix

- address medium priority issues

## v1.0.0 (2026-07-07)

### Feat

- implement campus card balance query

### Fix

- address critical issues
- return hex instead of base64 for DES encrypted password
- use DES encryption instead of RSA
- extract RSA parameters from JavaScript code
- add pycryptodome dependency for RSA encryption
- add RSA password encryption for login
- login via H5 mobile page instead of desktop
- match login form by name and captcha with single quotes
- match old working login code
- match captcha image URL with single quotes
- match login form by id instead of content
- match login form specifically, not QR code form
- extract all hidden form fields for login

### Refactor

- centralize config and fix divider lines
- clean up campus card module
- switch from pytesseract to ddddocr for captcha
- split into modules for multi-feature support

## v0.2.1 (2026-07-07)

### Feat

- simplify query to human-friendly format
- simplify query to human-friendly format
- add clear global account command
- use global account instead of per-user credentials

### Fix

- hide room number in response for privacy
- check login page content, not just URL
- correct localstore API usage
- use global cookies instead of per-user cookies
- handle SUPERUSERS config attribute case
- improve login validation check
- require params when no saved query params exist
- require params when no saved query params exist

### Refactor

- remove login logic, simplify to direct query
- use nonebot-plugin-localstore for file storage
- rewrite storage layer and add query param memory
- rewrite storage layer and add query param memory

## v0.1.1 (2026-03-22)

### Feat

- Basic query function

### Fix

- add explicit type conversion at func recognize_captcha
- Fix capitalization in plugin name and commands
