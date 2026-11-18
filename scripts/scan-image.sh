#!/usr/bin/env bash
# Scan a local Docker image with the pinned Trivy and fail on any HIGH/CRITICAL
# vulnerability, fixed upstream or not (the task's acceptance criterion).
# Accepted risks go in .trivyignore.yaml with a statement and expired_at.
# Usage: scan-image.sh IMAGE   (TRIVY_REPORT sets the JSON report path)
# Needs docker and jq.
set -Eeuo pipefail
image=${1:?Usage: scan-image.sh IMAGE}
report=${TRIVY_REPORT:-trivy-report.json}
# Pinned by digest because Trivy itself suffered a supply chain attack. This is
# the multi-arch index that Docker Hub served for aquasec/trivy:0.76.1 on
# 2026-11-18. To bump, check the new one before copying it:
#   docker buildx imagetools inspect aquasec/trivy:<version>
trivy_image='aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c'
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

bin_dir=$(mktemp -d)
trap 'rm -rf -- "$bin_dir"' EXIT
# Run the pinned binary in the calling job; it reaches Docker through DOCKER_HOST.
container=$(docker create "$trivy_image")
docker cp "$container:/usr/local/bin/trivy" "$bin_dir/trivy"
docker rm "$container" >/dev/null
trivy=$bin_dir/trivy

"$trivy" --version
"$trivy" image --download-db-only --no-progress
# Analyze the image once; the table and the gate both come from this report.
"$trivy" image --no-progress --image-src docker --skip-db-update \
  --ignorefile "$repo_root/.trivyignore.yaml" \
  --format json --output "$report" "$image"
"$trivy" convert --format table "$report"

blocking='[.Results[]?.Vulnerabilities[]? | select(.Severity == "HIGH" or .Severity == "CRITICAL")]'
count=$(jq "$blocking | length" "$report")
if (( count > 0 )); then
  echo "Blocked: $count HIGH/CRITICAL vulnerabilities (fixed upstream or not)." >&2
  jq -r "$blocking[] | \"\(.Severity) \(.VulnerabilityID) \(.PkgName) \(.InstalledVersion) fixed=\(.FixedVersion // \"none\") status=\(.Status // \"unknown\")\"" \
    "$report" >&2
  echo 'Upgrade the package or base image, or accept it in .trivyignore.yaml with a statement and expired_at.' >&2
  exit 1
fi
echo 'No HIGH/CRITICAL vulnerabilities.'
