#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -m)" != aarch64 ]]; then
  echo 'This bootstrap requires an ARM64 EC2 instance.' >&2
  exit 1
fi

# Finish the initial AMI boot before installing packages through State Manager.
cloud-init status --wait
dnf install -y docker jq util-linux coreutils awscli-2
systemctl enable --now docker amazon-ssm-agent
install -d -m 700 /opt/hangy

for executable in aws docker jq flock curl timeout; do
  command -v "$executable" >/dev/null
done
docker info >/dev/null
echo 'Hangy ARM64 runtime is ready.'
