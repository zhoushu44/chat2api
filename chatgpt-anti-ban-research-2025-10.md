# ChatGPT/OpenAI Account Anti-Ban & Survival Rate Research — October 2025

## Research Method
- `web_search` was unavailable (DeepSeek API auth error), so all data was gathered via GitHub API + raw file fetching.
- Forum sites (linux.do, v2ex, nodeseek) were not directly accessible.
- Focus shifted to GitHub repos with active commit histories.

## Repo Status Checks

| Repo | Status | Last Activity |
|------|--------|---------------|
| 432539/gpt2api | **NOT FOUND (404)** | — |
| lzA6/GPT-Codex-image-2api | **VERY ACTIVE (v2.37.0)** | 2026-09-14 |
| LanQian528/chat2api | Dormant | 2025-05-17 |
| zhoushu44/chat2api | No issues/PRs since Oct | — |
| AuuCoder/gptGrok2api | Active (v1.2.1, 288★) | 2026-07-27 |

## Key New Repos Found

- **lzA6/GPT-Codex-image-2api** (chatgpt2api) — Most advanced image API reverse proxy with account pool, v2.37.0. Has revive workflow, cf_solver for Turnstile, health-tier scheduler, account aging, WARP stack.
- **AuuCoder/gptGrok2api** — GPT+Grok account creator, OAuth PKCE flow, captcha-solver service, iCloud Privacy Mail, WARP stack.
- **aurora-develop/aurora** — Free ChatGPT API, 2588★, Go-based, last push 2026-09-20.
- **abostack/google-account-registration-guide** — 2026 Google account anti-ban guide, covers fingerprint and AIGC identity verification.

## NEW Techniques (Prioritized)

### [HIGH] 1. Per-Account Fingerprint Persistence
`fomimage_fingerprint.random_fingerprint()` — pick random curl_cffi impersonate + UA + platform, persist per account. No per-request JA3 rotation (rotation itself is a fingerprint).
Source: lzA6 commit `852483b`

### [HIGH] 2. Health-Tier Scheduler (healthy/warm/risky)
Tiered scheduling score + weighted random + dual mode (round_robin/remaining_quota) + active health probing.
Source: lzA6 README

### [HIGH] 3. Account Aging/Nurturing (养号)
7-day nurturing with behaviors: manual_login, low_frequency_first_days, no_api_first_days. Auto-apply to new accounts.
Source: lzA6 config.example.json `account_aging`

### [HIGH] 4. Multi-Worker Shared Circuit Breaker (Redis)
Atomic `incr_failure` so threshold 5 actually works. `SharedBreakerStateStore` with Local/Redis auto + degrade.
Source: lzA6 commit `663e28a`

### [HIGH] 5. WARP + Privoxy + FlareSolverr Stack
Only upstream OpenAI through stable proxy. CF clearance refresh every 3600s. Account-level proxy takes priority.
Source: Both repos `docker-compose.warp.yml`

### [HIGH] 6. Async Account Revival Workflow
`start_revive()` queue + ReviveLedger (atomic write + prune) + revive.finished event. Endpoints: POST /api/revive/run, GET /api/revive/status/{task_id}.
Source: lzA6 commit `663e28a`, file `services/revive_workflow.py`

### [HIGH] 7. Sticky Proxy Per Account + Auto-Isolation
`free_proxy.sticky_by_account=true` + precheck + health check + isolation + recovery.
Source: lzA6 config

### [HIGH] 8. Separate Captcha Solver Service (camoufox)
HTTP API solver: GET /turnstile?url=&sitekey= → 202 task_id → GET /result?id= poll. Camoufox (Firefox-based) backend, YesCaptcha fallback.
Source: lzA6 `services/fomimage_turnstile.py`, gptGrok2api `captcha-solver/`

### [HIGH] 9. Microsoft Graph Direct-Connect OTP Revival
Direct Graph API for email retrieval (priority) → 98faka fallback. Works in China without proxy.
Source: lzA6 README

### [MEDIUM] 10. Continuous Pool Refill Script
`fomimage_replenish.py` loops registration until pool reaches target count.
Source: lzA6 commit `b0c0723`

### [MEDIUM] 11. 22.do Free Temp Email
REST chain: create→login→applyToken(JWT)→message(Bearer). Multi-domain.
Source: lzA6 commit `adf83c9`

### [MEDIUM] 12. Grok Device Code + PKCE OAuth Flow
Device Code flow + PKCE for Grok registration. Turnstile token from Fast callback, no Console needed.
Source: gptGrok2api commits `3d94fdf`, `4daab45`

### [MEDIUM] 13. iCloud Privacy Mail Sidecar
Apple Hide My Email + 2FA + Catch-all email via Docker Compose sidecar.
Source: gptGrok2api README

### [MEDIUM] 14. Outlook Token Persistence (SQLite)
`outlook_token_used.db` to prevent overuse. Reuse collected login protocol.
Source: gptGrok2api README

### [MEDIUM] 15. Multi-Channel Alert System
Telegram/WeCom/DingTalk/Email. Events: circuit_breaker_open, account_invalid, quota_exhausted.
Source: lzA6 commit `663e28a`

## account_deactivated Error — Workarounds

No "unban" technique exists. Community consensus:
1. **OTP email revival** for abnormal (not fully deleted) accounts
2. **Password re-login** for accounts with passwords
3. **Auto-remove invalid accounts** + pool replenishment
4. Prevention: per-account IP/fingerprint/nurturing
5. Readme warns: "存在账号受限、临时封禁或永久封禁的风险"