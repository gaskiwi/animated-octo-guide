#!/bin/bash
# One-shot: finish Ollama setup on the GPU worker (lerandediannao).
# Run from kamrui: bash scripts/setup_worker_ollama.sh [worker_addr]
# Idempotent — safe to re-run. Worker must be awake.
set -euo pipefail
W="${1:-100.104.250.80}"   # tailscale IP (stable); LAN IP changes with DHCP

ssh -o BatchMode=yes -o ConnectTimeout=10 "pacers4ever@$W" 'bash -s' <<'EOF'
set -e
cd ~/ollama
# 1. Finish/repair the binary install
if [ ! -x bin/ollama ]; then
  echo "downloading ollama..."
  curl -sL -o ollama.tar.zst https://github.com/ollama/ollama/releases/download/v0.30.7/ollama-linux-amd64.tar.zst
  tar --zstd -xf ollama.tar.zst && rm -f ollama.tar.zst
fi
bin/ollama --version

# 2. Serve on all interfaces, survive reboot via crontab
pgrep -f "ollama serve" >/dev/null || \
  (OLLAMA_HOST=0.0.0.0:11434 nohup ~/ollama/bin/ollama serve >> ~/ollama/serve.log 2>&1 &)
sleep 3
curl -sf localhost:11434/api/version

( crontab -l 2>/dev/null | grep -v "ollama-watchdog" ; \
  echo "@reboot sleep 20 && /home/pacers4ever/ollama/watchdog.sh # ollama-watchdog" ; \
  echo "*/5 * * * * /home/pacers4ever/ollama/watchdog.sh # ollama-watchdog" ) | crontab -

cat > ~/ollama/watchdog.sh <<'WD'
#!/bin/bash
curl -sf --max-time 5 localhost:11434/api/version >/dev/null && exit 0
pkill -f "ollama serve" 2>/dev/null; sleep 1
OLLAMA_HOST=0.0.0.0:11434 nohup /home/pacers4ever/ollama/bin/ollama serve >> /home/pacers4ever/ollama/serve.log 2>&1 &
echo "$(date -Is) restarted ollama" >> /home/pacers4ever/ollama/watchdog.log
WD
chmod +x ~/ollama/watchdog.sh

# 3. Disable automatic suspend (the worker must stay up 24/7)
export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing 2>/dev/null \
  && echo "auto-suspend disabled" || echo "WARN: could not disable auto-suspend (no GNOME session?)"

# 4. Pull the local model (4.7 GB — takes a while first time)
~/ollama/bin/ollama pull qwen2.5-coder:7b
~/ollama/bin/ollama list
echo "WORKER SETUP COMPLETE"
EOF
echo "Done. Verify from kamrui: curl -s http://$W:11434/api/version"
