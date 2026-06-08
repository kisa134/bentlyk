#!/bin/bash
# =============================================================================
# Bentlyk — one-shot AWS bootstrap (paste into EC2 "User data").
#
# On first boot this turns a bare Ubuntu 24.04 instance into Bentlyk's permanent
# body: it installs Docker, pulls the repo, writes the .env, starts the worker as
# a self-restarting service, and sets up nightly auto-update. You never SSH in.
#
# HOW TO USE
#   1) Fill in the SECRETS block below (only the lines marked REQUIRED).
#   2) AWS Console -> EC2 -> Launch instance -> Ubuntu 24.04, t3.micro (free tier),
#      allow no inbound ports (it only makes outbound calls), create/download a key.
#   3) Expand "Advanced details" -> "User data" -> paste this whole file.
#   4) Launch. Give it ~3-4 minutes. Watch progress in EC2 -> Actions -> Monitor
#      and troubleshoot -> Get system log, or SSH and `tail -f /var/log/bentlyk-boot.log`.
#
# NOTE ON SECRETS: EC2 user-data is readable by anyone with console/API access to
# this instance. Keep the AWS account locked down and rotate these keys if exposed.
# =============================================================================
set -euo pipefail
exec > >(tee -a /var/log/bentlyk-boot.log) 2>&1
echo "[bentlyk-boot] starting $(date -u)"

# ----------------------------- SECRETS / CONFIG ------------------------------
# REQUIRED — the LLM brain (WaveSpeed key, starts with wsk_):
export BENTLYK_LLM_API_KEY="PASTE_WAVESPEED_KEY"
# REQUIRED — Telegram bot so it can talk to you:
export TELEGRAM_BOT_TOKEN="PASTE_TELEGRAM_BOT_TOKEN"
# Recommended — lock the bot to your Telegram user id (numeric). Leave blank to
# claim the first chatter as owner.
export TELEGRAM_ALLOWED_USER_ID=""

# Memory (Supabase REST). Defaults baked into the code work; override for your own
# project. REQUIRED if you use a private Supabase project.
export SUPABASE_URL=""
export SUPABASE_KEY=""

# Self-authoring: a GitHub token lets Bentlyk write/commit its own code, AND is
# used below to clone this repo if it's private. Fine-grained PAT with Contents
# read on the source repo + write on the self-repo.
export BENTLYK_GH_TOKEN="PASTE_GITHUB_TOKEN_OR_LEAVE_BLANK"
export BENTLYK_SELF_REPO="kisa134/bentlyk-self"

# Optional — stronger web search (else keyless DuckDuckGo):
export BENTLYK_TAVILY_KEY=""
# Optional — override models (defaults: deepseek chat, qwen coder on WaveSpeed):
export BENTLYK_MODEL=""
export BENTLYK_CODE_MODEL=""

# This is Bentlyk's OWN dedicated machine, so let it actually live its life:
# act on its own goals (safe_act) and run code in its sandbox.
export BENTLYK_MAX_AUTONOMY="escalated_act"
export BENTLYK_ALLOW_CODE="1"
export BENTLYK_TZ_OFFSET="3"

# Where to pull the code from. After you merge to main, set BRANCH=main.
SOURCE_REPO="kisa134/bentlyk"
BRANCH="claude/homeostatic-agent-design-KnNKT"
# -----------------------------------------------------------------------------

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git

# --- Docker (official convenience install) ---
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# --- Fetch the source ---
mkdir -p /opt
if [ -d /opt/bentlyk/.git ]; then
  git -C /opt/bentlyk fetch --all && git -C /opt/bentlyk checkout "$BRANCH" && git -C /opt/bentlyk pull
else
  if [ -n "${BENTLYK_GH_TOKEN}" ] && [ "${BENTLYK_GH_TOKEN}" != "PASTE_GITHUB_TOKEN_OR_LEAVE_BLANK" ]; then
    CLONE_URL="https://x-access-token:${BENTLYK_GH_TOKEN}@github.com/${SOURCE_REPO}.git"
  else
    CLONE_URL="https://github.com/${SOURCE_REPO}.git"
  fi
  git clone --branch "$BRANCH" "$CLONE_URL" /opt/bentlyk
fi

# --- Write the .env (chmod 600) from the exported config above ---
write_env() { local k="$1"; local v="${!1:-}"; [ -n "$v" ] && echo "${k}=${v}"; }
{
  for k in BENTLYK_LLM_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USER_ID \
           SUPABASE_URL SUPABASE_KEY BENTLYK_GH_TOKEN BENTLYK_SELF_REPO \
           BENTLYK_TAVILY_KEY BENTLYK_MODEL BENTLYK_CODE_MODEL \
           BENTLYK_MAX_AUTONOMY BENTLYK_ALLOW_CODE BENTLYK_TZ_OFFSET; do
    write_env "$k"
  done
} > /opt/bentlyk/.env
chmod 600 /opt/bentlyk/.env

# --- Bring the body up ---
cd /opt/bentlyk
docker compose up -d --build

# --- Nightly auto-update: pull latest code + rebuild, so deploys land by themselves ---
cat > /usr/local/bin/bentlyk-update <<'UPD'
#!/bin/bash
set -e
cd /opt/bentlyk
git pull --ff-only
docker compose up -d --build
docker image prune -f
UPD
chmod +x /usr/local/bin/bentlyk-update

cat > /etc/systemd/system/bentlyk-update.service <<'SVC'
[Unit]
Description=Bentlyk self-update (git pull + rebuild)
[Service]
Type=oneshot
ExecStart=/usr/local/bin/bentlyk-update
SVC

cat > /etc/systemd/system/bentlyk-update.timer <<'TMR'
[Unit]
Description=Run Bentlyk self-update nightly
[Timer]
OnCalendar=*-*-* 04:30:00
Persistent=true
[Install]
WantedBy=timers.target
TMR

systemctl daemon-reload
systemctl enable --now bentlyk-update.timer

echo "[bentlyk-boot] done $(date -u). Bentlyk is alive. Logs: docker compose -f /opt/bentlyk/docker-compose.yml logs -f"
