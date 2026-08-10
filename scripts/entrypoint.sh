#!/bin/sh
set -eu
# Host-mounted ./data is often root-owned; fix before dropping privileges.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data
  chown -R app:app /data || true
  exec su -s /bin/sh app -c "exec python -m daemon.main"
fi
exec python -m daemon.main
