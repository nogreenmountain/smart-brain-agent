#!/bin/sh
set -eu

/usr/sbin/nginx -t >/dev/null 2>&1
/usr/bin/systemctl reload nginx
