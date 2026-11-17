#!/usr/bin/env bash
# Scan a local Docker image with the pinned Trivy and fail on any HIGH/CRITICAL
# vulnerability, fixed upstream or not. Accepted risks go in .trivyignore.yaml
# with a statement and expired_at.
# Usage: scan-image.sh IMAGE   (TRIVY_REPORT sets the JSON report path)
set -Eeuo pipefail
image=${1:?Usage: scan-image.sh IMAGE}
report=${TRIVY_REPORT:-trivy-report.json}
# Pinned by digest because Trivy itself suffered a supply chain attack: bump the
# version and digest together after reviewing the release notes.
trivy_image='aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c'
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

bin_dir=$(mktemp -d)
trap 'rm -rf -- "$bin_dir"' EXIT
# Run the pinned binary in the calling job; it reaches Docker through DOCKER_HOST.
container=$(docker create "$trivy_image")
docker cp "$container:/usr/local/bin/trivy" "$bin_dir/trivy"
docker rm "$container" >/dev/null
trivy=("$bin_dir/trivy" image --no-progress --image-src docker --skip-db-update
  --ignorefile "$repo_root/.trivyignore.yaml")

"$bin_dir/trivy" --version
"$bin_dir/trivy" image --download-db-only --no-progress
"${trivy[@]}" --format json --output "$report" "$image"
"${trivy[@]}" --severity LOW,MEDIUM,HIGH,CRITICAL "$image"
"${trivy[@]}" --severity HIGH,CRITICAL --exit-code 1 "$image"
