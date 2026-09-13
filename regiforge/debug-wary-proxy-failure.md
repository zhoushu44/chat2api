# debug-wary-proxy-failure

Status: [OPEN]

## Symptom
Outlook registration tasks fail immediately at Wary proxy acquisition, with repeated "Wary 代理池不可用：无可用代理" and occasional "Wary 代理 API 请求失败".

## Reproduction
Run `project=outlook_register`, `proxy=wary`, `total=20`, `concurrency=1`.

## Hypotheses
1. Wary pool is temporarily exhausted when the tasks run.
2. Wary release is not happening on some task paths, leaving sessions occupied.
3. Wary API intermittently times out or is unreachable.
4. Session IDs are reused or malformed, causing pool allocation failure.

## Evidence collected

- Three independent read-only allocations to `http://192.6.121.16:4433/api/proxies` returned HTTP 200, `code=00000`, and `count=1`.
- All three test sessions were released through `/api/pool/release`; each returned `code=00000`.
- The earlier 20-account run failed before registration, at Wary acquisition, with one request timeout followed by repeated pool-unavailable responses.
- No evidence currently shows malformed or reused session IDs.

## Current assessment

Hypothesis 1: supported for the time window of the failed run; not currently reproducible.
Hypothesis 2: not proven from current evidence; Outlook's normal finalization path does call release after successful acquisition.
Hypothesis 3: supported for the first failed account, but not a persistent outage.
Hypothesis 4: rejected by current independent allocation results.

## Next verification

Run one real Outlook registration with `total=1`, `concurrency=1`, and `proxy=wary`. Capture the complete task log and failure evidence before making code changes.
