#!/bin/bash
# DelugeVPN start wrapper (runs instead of the image's default command).
#  - If VPN credentials are already in vpn.env: load them and start binhex as usual.
#  - If not: serve a small setup form on port 8112, wait for it to be saved,
#    then start binhex. No manual file editing or restart needed.

ENV_FILE="${DXD7_ENV_FILE:-/config/vpn.env}"
SETUP_PY="${DXD7_SETUP_PY:-/setup/setup.py}"
INIT_SH="${DXD7_INIT_SH:-init.sh}"
WG_CONF="${DXD7_WG_CONF:-/config/wireguard/wg0.conf}"
DATA_DIR="${DXD7_DATA_DIR:-/data}"
CORE_CONF="${DXD7_CORE_CONF:-/config/core.conf}"

# Reads KEY=VALUE lines literally (no shell evaluation, no $ expansion).
# One pair of matching outer quotes around a value is removed.
load_env() {
  [ -f "$ENV_FILE" ] || return 0
  local line key val first last
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    key="${key//[[:space:]]/}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [ "${#val}" -ge 2 ]; then
      first="${val:0:1}"
      last="${val: -1}"
      if [ "$first" = "$last" ] && { [ "$first" = '"' ] || [ "$first" = "'" ]; }; then
        val="${val:1:${#val}-2}"
      fi
    fi
    export "$key=$val"
  done < "$ENV_FILE"
}

is_configured() {
  [ "$SETUP_COMPLETE" = "yes" ] && return 0
  [ -n "$VPN_USER" ] && [ "$VPN_USER" != "CHANGE_ME" ] \
    && [ -n "$VPN_PASS" ] && [ "$VPN_PASS" != "CHANGE_ME" ]
}

# binhex's init.sh overwrites VPN_REMOTE_SERVER with a fixed default (Amsterdam)
# on first run, ignoring the value we pass in (upstream issue binhex/arch-qbittorrentvpn#377).
# Make it respect the variable when one was chosen. This is a no-op if the line
# isn't there (for example once upstream fixes it) and is reverted if it breaks the script.
patch_binhex() {
  [ -n "$VPN_REMOTE_SERVER" ] || return 0
  local f="$INIT_SH"
  [ -f "$f" ] || f="$(command -v init.sh 2>/dev/null)"
  if [ -z "$f" ] || [ ! -f "$f" ] || [ ! -w "$f" ]; then
    echo "[dxd7] could not find a writable init.sh - your server choice may be ignored"
    return 0
  fi
  if grep -qF 'export VPN_REMOTE_SERVER="nl-amsterdam.privacy.network"' "$f"; then
    cp "$f" "$f.dxd7.bak"
    sed -i 's|export VPN_REMOTE_SERVER="nl-amsterdam\.privacy\.network"|export VPN_REMOTE_SERVER="${VPN_REMOTE_SERVER:-nl-amsterdam.privacy.network}"|g' "$f"
    if bash -n "$f" 2>/dev/null; then
      rm -f "$f.dxd7.bak"
      echo "[dxd7] patched binhex init.sh so your server choice is honored"
    else
      mv "$f.dxd7.bak" "$f"
      echo "[dxd7] patch failed the syntax check and was reverted"
    fi
  elif grep -qF '${VPN_REMOTE_SERVER:-nl-amsterdam.privacy.network}' "$f"; then
    echo "[dxd7] binhex init.sh already honors your server choice"
  else
    echo "[dxd7] binhex init.sh has no fixed default server - nothing to patch"
  fi
}

# After the first run binhex reuses the Endpoint line in wg0.conf and ignores
# VPN_REMOTE_SERVER, so a later change in vpn.env would have no effect.
# Keep the Endpoint hostname in sync (the port is left alone).
sync_endpoint() {
  [ -n "$VPN_REMOTE_SERVER" ] || return 0
  [ "$VPN_PROV" = "pia" ] && [ "$VPN_CLIENT" = "wireguard" ] || return 0
  [ -f "$WG_CONF" ] || return 0
  if ! [[ "$VPN_REMOTE_SERVER" =~ ^[a-z0-9]([a-z0-9.-]{0,98}[a-z0-9])?$ ]]; then
    echo "[dxd7] VPN_REMOTE_SERVER is not a valid hostname - leaving wg0.conf alone"
    return 0
  fi
  local current port
  current="$(sed -n 's/^Endpoint[[:space:]]*=[[:space:]]*\([^:[:space:]]*\).*/\1/p' "$WG_CONF" | head -n1)"
  [ -n "$current" ] || return 0
  if [ "$current" != "$VPN_REMOTE_SERVER" ]; then
    port="$(sed -n 's/^Endpoint[[:space:]]*=[[:space:]]*[^:[:space:]]*:\([0-9]*\).*/\1/p' "$WG_CONF" | head -n1)"
    sed -i "s|^Endpoint[[:space:]]*=.*|Endpoint = ${VPN_REMOTE_SERVER}:${port:-1337}|" "$WG_CONF"
    echo "[dxd7] changed wg0.conf endpoint from $current to $VPN_REMOTE_SERVER"
  fi
}

# Makes sure Deluge's download folders exist and are writable on every start.
# Docker creates a missing bind-mounted /data as root, and binhex only fixes
# ownership on its very first run, so on a fresh install Deluge could not use
# /data/incomplete or /data/completed (the status bar showed "Error" for free
# space). Only the folders themselves are changed, never files inside them.
# Also covers any custom folder under /data that Deluge's saved settings use.
ensure_data_dirs() {
  [ -d "$DATA_DIR" ] || return 0
  local uid="${PUID:-1000}" gid="${PGID:-1000}" d
  local dirs=("$DATA_DIR/incomplete" "$DATA_DIR/completed")
  if [ -f "$CORE_CONF" ]; then
    while IFS= read -r d; do
      dirs+=("$d")
    done < <(sed -n -E 's/^[[:space:]]*"(download_location|move_completed_path)"[[:space:]]*:[[:space:]]*"([^"]*)".*/\2/p' "$CORE_CONF")
  fi
  chown "$uid:$gid" "$DATA_DIR" 2>/dev/null || true
  for d in "${dirs[@]}"; do
    case "$d" in
      *..*) continue ;;
      "$DATA_DIR"/?*) ;;
      *) continue ;;
    esac
    if [ ! -d "$d" ]; then
      if mkdir -p "$d" 2>/dev/null; then
        chown "$uid:$gid" "$d" 2>/dev/null || true
        chmod 775 "$d" 2>/dev/null || true
        echo "[dxd7] created download folder $d"
      else
        echo "[dxd7] could not create download folder $d"
      fi
    fi
  done
}

while true; do
  unset VPN_USER VPN_PASS SETUP_COMPLETE VPN_REMOTE_SERVER
  load_env
  if is_configured; then
    break
  fi
  echo "[dxd7] VPN not configured yet - starting setup page on port 8112"
  python3 "$SETUP_PY" || sleep 2
done

# An empty server setting means "use binhex's default", so it must be unset.
[ -n "$VPN_REMOTE_SERVER" ] || unset VPN_REMOTE_SERVER

# The VPN (and its kill switch) can never be switched off from vpn.env.
export VPN_ENABLED=yes

patch_binhex
sync_endpoint
ensure_data_dirs
echo "[dxd7] provider=${VPN_PROV:-?} client=${VPN_CLIENT:-?} server=${VPN_REMOTE_SERVER:-default}"
echo "[dxd7] VPN settings found - starting binhex"
exec /bin/bash init.sh
