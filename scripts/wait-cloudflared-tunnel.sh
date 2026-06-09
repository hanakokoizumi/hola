#!/bin/sh
set -eu

RUNTIME_ENV_FILE="${RUNTIME_ENV_FILE:-/etc/cloudflared/runtime.env}"

TUNNEL_TRANSPORT_PROTOCOL="${TUNNEL_TRANSPORT_PROTOCOL:-quic}"

while [ ! -s "$RUNTIME_ENV_FILE" ]; do
  echo "Waiting for Hola to create $RUNTIME_ENV_FILE ..."
  sleep 5
done

while true; do
  set -a
  . "$RUNTIME_ENV_FILE"
  set +a

  if [ -n "${TUNNEL_ID:-}" ] && [ -n "${TUNNEL_CRED_FILE:-}" ] && [ -s "$TUNNEL_CRED_FILE" ]; then
    break
  fi

  echo "Waiting for Cloudflare Tunnel ID and credentials file ..."
  sleep 5
done

TUNNEL_CONFIG_FILE="${TUNNEL_CONFIG_FILE:-/etc/cloudflared/config.yml}"

if [ -n "${ALL_PROXY:-}" ] || [ -n "${HTTPS_PROXY:-}" ] || [ -n "${HTTP_PROXY:-}" ]; then
  echo "Starting Cloudflare Tunnel through configured proxy with protocol ${TUNNEL_TRANSPORT_PROTOCOL}."
else
  echo "Starting Cloudflare Tunnel without proxy with protocol ${TUNNEL_TRANSPORT_PROTOCOL}."
fi

exec cloudflared tunnel --config "$TUNNEL_CONFIG_FILE" --no-autoupdate --protocol "$TUNNEL_TRANSPORT_PROTOCOL" run
