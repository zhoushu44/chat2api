#!/bin/bash
docker cp /tmp/_login_probe7.py regiforge:/app/_login_probe7.py
echo "===== PROBE7: lmba1609 verbose ====="
docker exec regiforge python3 /app/_login_probe7.py 'lmba1609@outlook.com' 'NLSZS07f8Z!A1' 'IALNTULD77J5ZPONM5EEUQ3SZ2LHEDCK' -
echo "===== PROBE7: ti99a610 verbose (control) ====="
docker exec regiforge python3 /app/_login_probe7.py 'ti99a610@outlook.com' '2o9Bu5MPVF!A1' '7IDAUI6PA7R46NTH3VOOCKEOUVRDWCDX' -
echo "===== DONE ====="
