import paramiko, json, time

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('195.72.185.32', username='root', password='6Qz6ao0T1zvL', timeout=30)
cmd = """docker rm -f chatgpt2api-13 && docker run -d --name chatgpt2api-13 \
  --restart unless-stopped -p 3077:3077 -p 6061:6060 \
  -v /root/chat2api/deploy/gray/data:/data \
  -v /root/chat2api/deploy/single/regiforge-data:/opt/regiforge/data \
  -e REGIFORGE_BASE_URL=http://127.0.0.1:8787 \
  -e REGIFORGE_PROJECT_ID=chatgpt_register -e REGIFORGE_PROXY_ID=wary -e REGIFORGE_EMAIL_ID=mailnest \
  -e REGIFORGE_EXPORT_BASE_URL=http://127.0.0.1:3077 -e REGIFORGE_EXPORT_ADMIN_PASSWORD=zs1236547 \
  -e CHATGPT2API_AUTH_KEY=zs1236547 -e CHATGPT_SENTINEL_MODE=auto -e STORAGE_BACKEND=json \
  -e SUPERRES_ENABLED=1 \
  -e SUPERRES_SECRET_ID=AKIDEQQIyAAxb5So3Lh083kIvQiJl02u8E8r \
  -e SUPERRES_SECRET_KEY=hBTfniQvHTWTHwQhmvRozxiJl1GIk050 \
  -e SUPERRES_BUCKET=chaofengz-1318449123 -e SUPERRES_REGION=ap-guangzhou \
  -e SUPERRES_PUBLIC_BASE_URL=https://chaofengz-1318449123.cos.ap-guangzhou.myqcloud.com \
  -e SUPERRES_UPLOAD_ENDPOINT=cos.accelerate.myqcloud.com \
  zhoushu1/chat2api:17.0"""
_,o,e = c.exec_command(cmd, timeout=180)
print(o.read().decode()[:60])
c.close()
