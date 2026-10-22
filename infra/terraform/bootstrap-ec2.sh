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


# "Evento começando" job: every 5 minutes, inside the running API container.
# flock -n skips a run if the previous one is still going. If the container is
# being replaced by a deploy, docker exec fails and the next run recovers.
cat >/etc/systemd/system/hangy-starting-soon.service <<'UNIT'
[Unit]
Description=Hangy: notify participants of events starting soon
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
TimeoutStartSec=240
ExecStart=/usr/bin/flock -n /run/hangy-starting-soon.lock /usr/bin/docker exec hangy-api python -m app.jobs.notify_starting_soon
UNIT
cat >/etc/systemd/system/hangy-starting-soon.timer <<'UNIT'
[Unit]
Description=Run the Hangy starting-soon job every 5 minutes

[Timer]
OnCalendar=*:0/5
AccuracySec=10s

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now hangy-starting-soon.timer

for executable in aws docker jq flock curl timeout; do
  command -v "$executable" >/dev/null
done
docker info >/dev/null
echo 'Hangy ARM64 runtime is ready.'
