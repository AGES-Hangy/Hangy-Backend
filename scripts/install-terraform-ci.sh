#!/usr/bin/env bash
set -euo pipefail
version="${TF_VERSION:?TF_VERSION is required}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
case "$(uname -m)" in
  x86_64) architecture=amd64 ;;
  aarch64|arm64) architecture=arm64 ;;
  *) echo 'Unsupported runner architecture.' >&2; exit 1 ;;
esac
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
archive="terraform_${version}_linux_${architecture}.zip"
base="https://releases.hashicorp.com/terraform/$version"
curl --fail --silent --show-error --location "$base/$archive" -o "$work_dir/$archive"
curl --fail --silent --show-error --location "$base/terraform_${version}_SHA256SUMS" \
  -o "$work_dir/checksums"
(
  cd "$work_dir"
  awk -v archive="$archive" '$2 == archive' checksums > selected-checksum
  [[ -s selected-checksum ]]
  sha256sum -c selected-checksum
  unzip -q "$archive" terraform
)
install -m 755 "$work_dir/terraform" /usr/local/bin/terraform
