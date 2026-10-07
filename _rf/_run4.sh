#!/bin/bash
docker cp /tmp/_login_probe4.py regiforge:/app/_login_probe4.py

echo "===== TEST A: ti99a610 (real sentinel, full) ====="
docker exec regiforge python3 /app/_login_probe4.py 'ti99a610@outlook.com' '2o9Bu5MPVF!A1' '7IDAUI6PA7R46NTH3VOOCKEOUVRDWCDX' - real

echo "===== TEST B: ti99a610 (real sentinel but DROP so-token) ====="
docker exec regiforge python3 /app/_login_probe4.py 'ti99a610@outlook.com' '2o9Bu5MPVF!A1' '7IDAUI6PA7R46NTH3VOOCKEOUVRDWCDX' - noso

echo "===== TEST C: lmba1609 (disabled acct, real sentinel) ====="
docker exec regiforge python3 /app/_login_probe4.py 'lmba1609@outlook.com' 'NLSZS07f8Z!A1' 'IALNTULD77J5ZPONM5EEUQ3SZ2LHEDCK' - real

echo "===== DONE ====="
