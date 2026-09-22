#!/usr/bin/env bash
#
# OCI Health Check - Ubuntu 24.04 installer
#
# Installs the app as a systemd service behind nginx with SSL offloading
# (Let's Encrypt via certbot) and opens the firewall for HTTPS.
#
#   1. Copy install.conf.example to install.conf and edit DOMAIN/EMAIL.
#   2. Run:  sudo ./install.sh
#
# To pull the latest code from git, sync it to the install directory and
# restart the app service without re-running the full installer:
#
#   sudo ./install.sh -update
#
# Health checks (healthcheck/*.json) are live data: editors change them
# through the site. On every run the installer adds new health checks and
# updates the ones that were never edited on the server (their content still
# matches a version from the repository's git history). A health check that
# was edited on the server AND changed in the repository is left alone; the
# repository version is placed next to it as <name>.json.repo for a manual
# merge. To overwrite such files anyway (a <name>.json.bak copy is kept):
#
#   sudo ./install.sh -update -replace-healthchecks
#
# The script is idempotent: re-running it updates the app files and
# configuration in place.

set -euo pipefail

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

UPDATE_MODE="no"
REPLACE_HEALTHCHECKS="no"

for arg in "$@"; do
    case "$arg" in
        -update) UPDATE_MODE="yes" ;;
        -replace-healthchecks) REPLACE_HEALTHCHECKS="yes" ;;
        *) echo "ERROR: unknown option: $arg" >&2
           echo "Usage: sudo ./install.sh [-update] [-replace-healthchecks]" >&2; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CONF_FILE="$SCRIPT_DIR/install.conf"

# Defaults (can be overridden in install.conf)
APP_PORT="8080"
INSTALL_DIR="/opt/oci-healthcheck"
SERVICE_USER="oci-health"
SERVICE_NAME="oci-healthcheck"
SKIP_CERTBOT="no"
DOMAIN=""
LETSENCRYPT_EMAIL=""

if [[ -f "$CONF_FILE" ]]; then
    # shellcheck source=install.conf.example
    source "$CONF_FILE"
else
    echo "ERROR: $CONF_FILE not found." >&2
    echo "Copy install.conf.example to install.conf and set DOMAIN and LETSENCRYPT_EMAIL." >&2
    exit 1
fi

fail() { echo "ERROR: $*" >&2; exit 1; }
info() { echo -e "\n==> $*"; }

[[ $EUID -eq 0 ]] || fail "run as root (sudo ./install.sh)"

# git, tolerating a checkout owned by another user (we run as root).
repo_git() { git -c "safe.directory=$REPO_DIR" -C "$REPO_DIR" "$@"; }

file_hash() { sha256sum "$1" | cut -d' ' -f1; }

# True if the content hash $2 equals any committed version of repo file $1.
# Used to recognise a deployed health check that was never edited on the
# server: its content is still exactly what some commit of the repo shipped.
in_repo_history() {
    local path="$1" hash="$2" rev
    [[ -d "$REPO_DIR/.git" ]] || return 1
    while read -r rev; do
        [[ -n "$rev" ]] || continue
        if [[ "$(repo_git show "$rev:$path" 2>/dev/null | sha256sum | cut -d' ' -f1)" == "$hash" ]]; then
            return 0
        fi
    done < <(repo_git log --format=%H -- "$path" 2>/dev/null)
    return 1
}

sync_healthchecks() {
    local src name dest
    for src in "$REPO_DIR"/healthcheck/*.json; do
        [[ -f "$src" ]] || continue
        name="$(basename "$src")"
        dest="$INSTALL_DIR/healthcheck/$name"

        if [[ ! -f "$dest" ]]; then
            echo "Adding health check $name"
            cp "$src" "$dest"
            continue
        fi

        cmp -s "$src" "$dest" && continue   # already current

        if [[ "$REPLACE_HEALTHCHECKS" == "yes" ]]; then
            echo "Replacing health check $name (server version kept as $name.bak)"
            cp -p "$dest" "$dest.bak"
            cp "$src" "$dest"
            continue
        fi

        if in_repo_history "healthcheck/$name" "$(file_hash "$dest")"; then
            echo "Updating health check $name"
            cp "$src" "$dest"
        else
            cp "$src" "$dest.repo"
            echo "WARNING: health check $name was edited on this server and has also changed in the repository."
            echo "         Kept the server version. The repository version is at $dest.repo for a manual merge"
            echo "         (or re-run with -replace-healthchecks to overwrite it; a .bak copy is kept)."
        fi
    done
    # Stale .repo copies from an earlier run are refreshed above; drop the
    # ones whose conflict has been resolved (live file now matches the repo).
    for src in "$INSTALL_DIR"/healthcheck/*.json.repo; do
        [[ -f "$src" ]] || continue
        dest="${src%.repo}"
        if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
            rm -f "$src"
        fi
    done
}

sync_app_files() {
    info "Installing application to $INSTALL_DIR"
    if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
        useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    fi

    mkdir -p "$INSTALL_DIR"
    # healthcheck/ holds the checklist definitions, which editors modify
    # through the site, so it is live data: synced by sync_healthchecks
    # instead of being overwritten by rsync.
    rsync -a --delete \
        --exclude 'deploy/' \
        --exclude '.git/' \
        --exclude '__pycache__/' \
        --exclude 'img/' \
        --exclude 'config.json' \
        --exclude 'data/' \
        --exclude 'healthcheck/' \
        "$REPO_DIR/" "$INSTALL_DIR/"

    # Seed local files on first install only - they hold live data afterwards.
    mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/healthcheck"
    [[ -f "$INSTALL_DIR/config.json" ]] || cp "$REPO_DIR/config.json.example" "$INSTALL_DIR/config.json"
    [[ -f "$INSTALL_DIR/data/feedback.json" ]] || echo '{}' > "$INSTALL_DIR/data/feedback.json"

    sync_healthchecks

    # Code read-only, data/ and healthcheck/ writable by the service user.
    chown -R root:root "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/data" "$INSTALL_DIR/healthcheck"
    chmod 750 "$INSTALL_DIR/data" "$INSTALL_DIR/healthcheck"
}

write_service_unit() {
    info "Writing systemd service $SERVICE_NAME"
    cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=OCI Health Check web app
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/server.py $APP_PORT 127.0.0.1
Restart=always
RestartSec=3

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$INSTALL_DIR/data $INSTALL_DIR/healthcheck
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
}

if [[ "$UPDATE_MODE" == "yes" ]]; then
    info "Update mode: git pull, sync application files and restart $SERVICE_NAME"
    command -v git >/dev/null 2>&1 || fail "git is not installed (install it or re-run ./install.sh to add git)"
    [[ -d "$REPO_DIR/.git" ]] || fail "$REPO_DIR is not a git repository"
    repo_git pull --ff-only
    systemctl list-unit-files "$SERVICE_NAME.service" --no-legend 2>/dev/null | grep -q . \
        || fail "$SERVICE_NAME is not installed; run ./install.sh without -update first"
    sync_app_files
    write_service_unit   # picks up changes such as new ReadWritePaths
    systemctl restart "$SERVICE_NAME"
    info "Update complete."
    systemctl --no-pager --lines 0 status "$SERVICE_NAME" || true
    exit 0
fi

[[ -n "$DOMAIN" && "$DOMAIN" != *"example.com"* ]] \
    || fail "set DOMAIN in install.conf to your real domain name"
if [[ "$SKIP_CERTBOT" != "yes" ]]; then
    [[ -n "$LETSENCRYPT_EMAIL" && "$LETSENCRYPT_EMAIL" != *"example.com"* ]] \
        || fail "set LETSENCRYPT_EMAIL in install.conf (or SKIP_CERTBOT=\"yes\")"
fi

# --------------------------------------------------------------------------
# Packages
# --------------------------------------------------------------------------

info "Installing packages (nginx, certbot, python3, ufw, rsync, git)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx python3 ufw rsync git

# --------------------------------------------------------------------------
# Application files and service user
# --------------------------------------------------------------------------

sync_app_files

# --------------------------------------------------------------------------
# systemd service (app listens on loopback only; nginx does SSL offloading)
# --------------------------------------------------------------------------

write_service_unit
systemctl enable --now "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

# --------------------------------------------------------------------------
# nginx reverse proxy
# --------------------------------------------------------------------------

info "Configuring nginx for $DOMAIN"
cat > "/etc/nginx/sites-available/$SERVICE_NAME" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf "/etc/nginx/sites-available/$SERVICE_NAME" "/etc/nginx/sites-enabled/$SERVICE_NAME"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# --------------------------------------------------------------------------
# Firewall: allow HTTPS (and HTTP for the ACME challenge / redirect)
# --------------------------------------------------------------------------

info "Configuring ufw (allow 443 and 80)"
ufw allow 'Nginx Full' >/dev/null      # 80/tcp + 443/tcp
if ufw status | grep -q "Status: active"; then
    echo "ufw is active; Nginx Full (80,443) allowed."
else
    # Enable the firewall, but never lock out SSH.
    ufw allow OpenSSH >/dev/null
    ufw --force enable
    echo "ufw enabled with OpenSSH and Nginx Full (80,443) allowed."
fi

# --------------------------------------------------------------------------
# Let's Encrypt certificate (SSL offloading in nginx)
# --------------------------------------------------------------------------

if [[ "$SKIP_CERTBOT" == "yes" ]]; then
    info "SKIP_CERTBOT=yes - skipping Let's Encrypt; site is HTTP only."
else
    info "Requesting Let's Encrypt certificate for $DOMAIN"
    certbot --nginx --non-interactive --agree-tos --redirect \
        -m "$LETSENCRYPT_EMAIL" -d "$DOMAIN"
    # certbot installs a systemd timer for automatic renewal; verify it.
    systemctl list-timers certbot.timer --no-pager | head -n 3 || true
fi

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

info "Done."
systemctl --no-pager --lines 0 status "$SERVICE_NAME" || true
echo
if [[ "$SKIP_CERTBOT" == "yes" ]]; then
    echo "Site:            http://$DOMAIN/"
else
    echo "Site:            https://$DOMAIN/  (HTTP redirects to HTTPS)"
fi
echo "App service:     systemctl status $SERVICE_NAME"
echo "App logs:        journalctl -u $SERVICE_NAME -f"
echo "Live data:       $INSTALL_DIR/data and $INSTALL_DIR/healthcheck (survive re-runs of this installer)"
