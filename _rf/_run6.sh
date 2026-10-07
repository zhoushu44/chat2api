#!/bin/bash
docker cp /tmp/_login_probe6.py regiforge:/app/_login_probe6.py
echo "===== PROBE6: conversation/init quota ====="
docker exec regiforge python3 /app/_login_probe6.py 'ti99a610@outlook.com' '2o9Bu5MPVF!A1' '7IDAUI6PA7R46NTH3VOOCKEOUVRDWCDX' -
echo "===== DONE ====="
