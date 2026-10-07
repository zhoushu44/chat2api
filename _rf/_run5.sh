#!/bin/bash
docker cp /tmp/_login_probe5.py regiforge:/app/_login_probe5.py
echo "===== PROBE5: ti99a610 endpoint matrix ====="
docker exec regiforge python3 /app/_login_probe5.py 'ti99a610@outlook.com' '2o9Bu5MPVF!A1' '7IDAUI6PA7R46NTH3VOOCKEOUVRDWCDX' -
echo "===== DONE ====="
