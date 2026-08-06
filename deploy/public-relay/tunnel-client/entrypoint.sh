#!/bin/sh
set -eu

install -m 0600 /run/relay-src/id_ed25519 /run/relay/id_ed25519
install -m 0600 /run/relay-src/known_hosts /run/relay/known_hosts

exec /usr/bin/ssh "$@"
