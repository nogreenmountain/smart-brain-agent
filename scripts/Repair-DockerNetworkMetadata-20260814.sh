#!/bin/sh
set -eu

mode="${1:-check}"
container_root="/mnt/docker-desktop-disk/data/docker/containers"
backup_suffix=".network-recovery-backup-20260814"

mappings='2d285ad64f0b646e80551549ad305a3bcc297e0da160662d9f8e6b81f1cc6663:3fd85752a501e9d4b587c1777cb251ca3af0b0db16425a8fb6c98cec7623883d
c827aa35d29f3f38e1487ca72d6b53abe1b1851a7880e3f65de0ccf3984f89c1:bfa3a80f760025aab78b2f65835f68e20b45836da50f6f404faf42275a1da0be
6e0ca31939bfab8849ed8784ad2f0fdef8cf87419ccc486a77c77ceb892471e0:fe6d98da52eb38b03ca694838fc6515c8613834c859f2ac329e26d49c739353e
45f965e6e73d7271cd4a74ba8d292da83a7f636b88a247c202bc3376a055846a:d7dcc79478129daa989662275f0bf09bfbc132c57522307b149f768f435f66d7
f27a9a129cc6392100d832dd1e1aa46d6e56a1e2581f6297f15972586086c0ee:3cb06dc7dfe46a684eef8ca31b1bf885f9d4d882f953df1b21502657edc65193'

if [ ! -d "$container_root" ]; then
  echo "container_root_missing=$container_root" >&2
  exit 1
fi

matches=0
for file in "$container_root"/*/config.v2.json "$container_root"/*/hostconfig.json; do
  [ -f "$file" ] || continue
  found=0
  while IFS=: read -r old_id new_id; do
    if grep -q "$old_id" "$file"; then
      found=1
      break
    fi
  done <<EOF
$mappings
EOF
  if [ "$found" -eq 1 ]; then
    matches=$((matches + 1))
    if [ -e "$file$backup_suffix" ]; then
      echo "backup_conflict=$file$backup_suffix" >&2
      exit 1
    fi
  fi
done

echo "matching_config_files=$matches"
if [ "$mode" = "check" ]; then
  exit 0
fi
if [ "$mode" != "repair" ]; then
  echo "usage: $0 [check|repair]" >&2
  exit 2
fi
if [ "$matches" -eq 0 ]; then
  echo "nothing_to_repair=true"
  exit 0
fi

dockerd_pid="$(pidof dockerd | awk '{print $1}')"
if [ -z "$dockerd_pid" ]; then
  echo "dockerd_not_running=true" >&2
  exit 1
fi

paused=0
resume_on_error() {
  if [ "$paused" -eq 1 ]; then
    kill -CONT "$dockerd_pid" 2>/dev/null || true
  fi
}
trap resume_on_error EXIT INT TERM

kill -STOP "$dockerd_pid"
paused=1

changed=0
for file in "$container_root"/*/config.v2.json "$container_root"/*/hostconfig.json; do
  [ -f "$file" ] || continue
  found=0
  while IFS=: read -r old_id new_id; do
    if grep -q "$old_id" "$file"; then
      found=1
      break
    fi
  done <<EOF
$mappings
EOF
  [ "$found" -eq 1 ] || continue

  cp -p "$file" "$file$backup_suffix"
  while IFS=: read -r old_id new_id; do
    sed -i "s/$old_id/$new_id/g" "$file"
  done <<EOF
$mappings
EOF
  changed=$((changed + 1))
done

sync
kill -KILL "$dockerd_pid"
paused=0
trap - EXIT INT TERM

echo "changed_config_files=$changed"
echo "backups_created=$changed"
