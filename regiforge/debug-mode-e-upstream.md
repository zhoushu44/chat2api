# Mode E upstream debugging

Status: [OPEN]
Session ID: mode-e-upstream

## Symptom

Mode E SOCKS ports 10080/10081 return server direct IP 192.6.121.16 instead of upstream SOCKS exit 97.118.25.178.

## Hypotheses

1. socks5_proxy3.py implements direct CONNECT instead of forwarding through upstream SOCKS.
2. Mode E launcher omits upstream host, credentials, or protocol arguments.
3. Container cannot reach host.docker.internal:7890.
4. Subscription refresh failure caused stale or empty upstream configuration.

## Pre-fix evidence

- Container is running, RestartCount=0.
- Host SOCKS 127.0.0.1:7890 exits as 97.118.25.178 and reaches Outlook.
- Mode E ports 10080/10081 exit as 192.6.121.16.
- Container logs repeatedly show subscription refresh timeout.

## Evidence analysis

1. Confirmed: `/tmp/socks5_proxy3.py` used `socket.create_connection((addr, port))`, which connected directly to targets.
2. Confirmed: `_ensure_test_proxies()` launched the script with only the local port and no upstream arguments.
3. Rejected: the container successfully reached `host.docker.internal:7890` through authenticated SOCKS and obtained an external exit.
4. Independent issue: subscription refresh still times out, but it did not prevent access to the existing upstream SOCKS endpoint.

## Minimal fix

Changed the two Mode E test SOCKS listeners to connect through authenticated upstream `host.docker.internal:7890`. Preserved `/tmp/socks5_proxy3.py.bak` on the host and restarted the container.

## Post-fix evidence

- Container restart succeeded; `RestartCount` remained healthy and both 10080/10081 workers restarted automatically.
- Python compilation passed.
- 10080 exit changed from `192.6.121.16` to `96.242.50.27`.
- 10081 exit changed from `192.6.121.16` to `96.242.50.27`.
- Both listeners reached Outlook and returned HTTP 301.
- Real Outlook task `700f58cec190` passed step01-step03 and reached step04. It failed only after two Arkose `Keep going` responses, proving the transport failure was fixed; the remaining issue is upstream exit reputation.

Status: [AWAITING_CONFIRMATION]
