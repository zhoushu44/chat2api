#!/bin/bash
cd /tmp
echo "===== REAL SENTINEL ====="
timeout 150 python3 _login_probe3.py ti99a610@outlook.com '2o9Bu5MPVF!A1' 7IDAUI6PA7R46NTH3VOOCKEOUVRDWCDX - 0
echo
echo "===== FORGED SENTINEL GoStyle ====="
timeout 150 python3 _login_probe3.py ti99a610@outlook.com '2o9Bu5MPVF!A1' 7IDAUI6PA7R46NTH3VOOCKEOUVRDWCDX - 1
