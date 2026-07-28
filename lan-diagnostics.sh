#!/bin/bash
# LAN access diagnostics for the智慧大脑 Agent MVP
# Run this from a LAN computer (not the server itself)

SERVER="192.168.1.40"
echo "=== 1. Ping ==="
ping -c 3 $SERVER
echo
echo "=== 2. API health ==="
curl -sS --max-time 5 http://$SERVER:8000/health
echo
echo "=== 3. Dashboard home ==="
curl -sS --max-time 5 -o /dev/null -w "HTTP: %{http_code}\n" http://$SERVER:3001/signin
echo
echo "=== 4. Supabase Studio (should be BLOCKED) ==="
curl -sS --max-time 5 -o /dev/null -w "HTTP: %{http_code} (expect 000=blocked)\n" http://$SERVER:54321
echo
echo "=== 5. Login test ==="
curl -sS --max-time 5 -X POST http://$SERVER:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"testuser1@local.dev","password":"TestUser123!"}'
