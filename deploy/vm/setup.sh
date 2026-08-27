#!/usr/bin/env bash
# One-time VM preparation. Run as root on a fresh Ubuntu 24.04 box.
#
#   ssh root@YOUR_VM_IP
#   curl -fsSL https://raw.githubusercontent.com/ayyappan04/badminton-coach/main/deploy/vm/setup.sh | bash
#
# Installs Docker, creates a non-root user to run the stack, sets up the
# firewall, and enables unattended security updates. Idempotent — safe to
# re-run.
set -euo pipefail

REPO="${REPO:-https://github.com/ayyappan04/badminton-coach.git}"
APP_USER="${APP_USER:-shuttlesense}"
APP_DIR="/opt/shuttlesense"

log() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

log "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ufw unattended-upgrades

log "Docker"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
docker --version

log "Application user"
# The stack runs as a normal user, not root. Containers already run as uid
# 1001 internally; this stops the compose process itself being root too.
id -u "$APP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$APP_USER"
usermod -aG docker "$APP_USER"

log "Repository"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

log "Firewall"
# Only SSH and HTTP(S). The API is never published directly — Caddy proxies it
# over the internal Docker network, so it cannot be reached without TLS.
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose

log "Automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades

log "Swap"
# CV work is memory-spiky. A little swap turns a rare spike into a slow job
# rather than an OOM kill. It is NOT a substitute for real RAM.
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
free -h | head -3

log "systemd unit"
cat > /etc/systemd/system/shuttlesense.service <<UNIT
[Unit]
Description=ShuttleSense API and analysis worker
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/docker compose -f deploy/vm/docker-compose.vm.yml --env-file deploy/vm/.env up -d --build
ExecStop=/usr/bin/docker compose -f deploy/vm/docker-compose.vm.yml --env-file deploy/vm/.env down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable shuttlesense.service >/dev/null

cat <<NEXT

$(printf '\033[1m')Prepared.$(printf '\033[0m') Two steps left:

  1. Create the environment file:

       cp $APP_DIR/deploy/vm/env.example $APP_DIR/deploy/vm/.env
       nano $APP_DIR/deploy/vm/.env

     API_DOMAIN needs an A record already pointing at this VM, or Caddy
     cannot complete the ACME challenge and will retry in a loop.

  2. Start it:

       systemctl start shuttlesense

     First build takes 5-10 minutes: it compiles OpenCV and MediaPipe.

  Then, from your laptop:

       ./deploy/verify-deployment.sh https://YOUR_API_DOMAIN https://YOUR_FRONTEND

  Logs:     docker compose -f $APP_DIR/deploy/vm/docker-compose.vm.yml logs -f
  Restart:  systemctl restart shuttlesense

NEXT
