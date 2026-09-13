# NVIDIA Pure HTTP Debug

Status: [OPEN]
Session: `nvidia-pure-http`

## Goal

Capture the successful NVIDIA stage-3 authentication flow and replace browser OTP/consent/cloud-account/API-key handling with verified `curl_cffi` requests.

## Baseline

- Stopped task `31d3ce1ecfd7`: done=24, ok=22, failed=2.
- Current `http` mode is hybrid: browser bootstrap + HTTP registration + browser stage 3.
- Existing evidence does not contain a complete successful stage-3 request/response chain.

## Falsifiable hypotheses

1. Password login is submitted to a JSON endpoint under `accounts.nvgs.nvidia.com`.
2. Email verification link only verifies ownership; a second login is required to establish NVGS session.
3. Consent is an HTML form submission rather than a JSON API.
4. Cloud Account creation uses a separate XHR/fetch endpoint and returns OAuth callback state.
5. NGC authentication is established by `Set-Cookie` in the redirect chain and can be replayed by `curl_cffi`.

## Evidence plan

- Instrument one existing successful hybrid run.
- Capture only NVIDIA authentication/API domains.
- Record request method/URL, redacted request body/header names, response status/Location/Set-Cookie names.
- Never persist passwords, OTP values, bearer tokens, cookies, OAuth codes, or API keys.
- Analyze evidence before changing business logic.

## Progress

- [x] Stop 100-account hybrid batch.
- [ ] Add redacted stage-3 network instrumentation.
- [ ] Reproduce one successful hybrid account.
- [ ] Classify hypotheses from captured evidence.
- [ ] Implement minimal pure HTTP stage 3.
- [ ] Verify pure HTTP L1.
