# Wary proxy instability debug

- Session: `wary-proxy-instability`
- Status: `[OPTIMIZED — IPV6 LOAD PROBE PASSED; L2 NOT RE-RUN]`
- Target host: `192.6.121.16`
- Container: `079f08e63e2bc4003c8435d203acbee81c12b203852a906e743a47e12e323e79`

## Confirmed causes and repairs

1. RegiForge public IP was `39.182.146.244`, while Wary allowed old IP `39.182.146.199`. Updated the persistent Wary whitelist and all 20 sing-box instance configs.
2. Allocation trusted listener state and probed OpenAI only after returning the proxy. Added synchronous end-to-end OpenAI probing before allocation and quarantine on HTTP code `0`.
3. usque QUIC reported insufficient UDP buffers. Raised and persisted host `net.core.rmem_max` and `net.core.wmem_max` to `7500000`.
4. HTTP/2 and regular tunnel SOCKS could keep listeners alive while the data plane hung under Chromium traffic. Tested QUIC, HTTP/2, and usque `l4-socks`; `l4-socks` passed a five-run full authorize URL probe but still failed during sustained registration.
5. RegiForge Wary Provider never released sticky sessions and treated JSON `P0001` errors as proxy strings. Added JSON error handling and `/api/pool/release`; ChatGPT retry now releases the previous proxy before acquiring another.

## Backups and image

- `/root/warp/config.json.bak-20260819-094948`
- `/etc/sysctl.conf.bak-wary-20260819`
- `/root/warp/server.js.bak-preprobe-20260819`
- `/root/warp/server.js.bak-before-l4-socks-20260819`
- Runtime image: `wary-fixed:20260819-preprobe`
- Watchdog backup: `/app/server.js.bak-watchdog-20260819`
- Optimized source: `/root/warp/server.js.optimized-20260819`
- Optimized runtime image: `wary-fixed:20260819-ipv6-watchdog` (`bbb112de4018`)

## IPv6 watchdog optimization

- Confirmed the container already runs upstream latest `usque v4.2.1`, commit `6aa03fc97d12848dce34eedbd187fb1077b5d1ea`; no binary upgrade was needed.
- Retained `l4-socks`, which upstream documents as the lighter TCP-only path using direct HTTP/3 CONNECT streams without the full userspace network stack.
- Allocation now probes both `auth.openai.com/api/accounts/authorize` and `sentinel.openai.com/backend-api/sentinel/sdk.js` before returning an instance.
- Added a 60-second watchdog over idle instances. A failed data path is quarantined and its usque + sing-box processes are restarted.
- Transport restart preserves `usque.json`; therefore the WARP account and its assigned IPv6 are retained instead of registering a new identity.
- During verification, the watchdog detected failures on warp-7 and warp-12 and restored both. The post-restart log recorded the retained IPv6.

## Post-fix tests

- Wary API 401 resolved.
- External curl OpenAI test: `10/10`.
- Basic Playwright authorize page: `5/5`.
- Full authorize URL with `l4-socks`: `5/5` in isolated probes.
- Optimized IPv6 Chromium load probe: `10/10`; all ten allocations returned distinct IPv6 exits and completed the full authorize navigation with HTTP 403, proving TCP/TLS/HTTP path health.
- Watchdog recovery observed: warp-7 and warp-12 failed the ChatGPT data-path check, were restarted, and passed post-restart validation while preserving IPv6 identity.
- Web L1 task `b1e4e642c7ca`: `1/1`, accessToken saved.

## L2 evidence

### Wary

- Task `d7f3135ebd2d`: `0/5`.
- Task `c0fb16574553`: stopped after repeated `proxy_dead`; progress reached `2/5` with one failure and continued tunnel failures.
- Task `d4bcb744d7fd`: stopped at `2/5` after repeated `ERR_PROXY_CONNECTION_FAILED` despite `l4-socks`.
- Evidence examples:
  - `data/debug/chatgpt_register/d7f3135ebd2d/0001`
  - `data/debug/chatgpt_register/c0fb16574553/0002`
  - `data/debug/chatgpt_register/d4bcb744d7fd/0002`
- L2 threshold was not met.

### Existing alternative providers

- Relay Scout single-account smoke failed because the returned endpoint `103.28.33.115:1084` died while downloading Sentinel SDK.
- mihomo single-account smoke reached OpenAI but returned `unsupported_country_region_territory` from a Venezuela exit; Sentinel SDK fallback returned 403.

## Maturity conclusion

- L1: passed (`b1e4e642c7ca`, `1/1`, accessToken).
- L2: failed; no tested fixed provider configuration reached `>=80%` over five single-concurrency samples.
- L3: not executed because L2 did not pass.
- L4: not executed because L3 did not pass; no L4 certification is valid.
- Current certified maturity: **L1**.

## Blocker

The current proxy inventory does not provide a stable, supported-country OpenAI path under the complete Sentinel + Auth workload. Further code retries cannot legitimately satisfy the maturity gate. A stable US/EU residential or ISP proxy pool, or a repaired Wary transport implementation that survives sustained Chromium traffic, is required before restarting L2.
