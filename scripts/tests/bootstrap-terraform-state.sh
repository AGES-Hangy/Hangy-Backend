#!/usr/bin/env bash
# Exercises the bootstrap with a fake AWS CLI. No requests reach AWS.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
mkdir "$work_dir/bin"

cat > "$work_dir/bin/aws" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$AWS_MOCK_LOG"
case "$1 $2" in
  'sts get-caller-identity') echo 123456789012 ;;
  's3api head-bucket')
    case "$MOCK_CASE" in
      existing) exit 0 ;;
      forbidden) echo 'An error occurred (403) when calling HeadBucket: Forbidden' >&2; exit 1 ;;
      *) echo 'An error occurred (404) when calling HeadBucket: Not Found' >&2; exit 1 ;;
    esac
    ;;
  's3api put-bucket-policy')
    while [[ "$1" != --policy ]]; do shift; done
    jq -e '.Statement[0].Effect == "Deny" and
      .Statement[0].Condition.Bool["aws:SecureTransport"] == "false"' "${2#file://}" >/dev/null
    ;;
  's3api create-bucket'|'s3api wait'|'s3api put-public-access-block'|\
  's3api put-bucket-encryption'|'s3api put-bucket-versioning') ;;
  *) echo "Unexpected AWS operation: $*" >&2; exit 1 ;;
esac
MOCK
chmod +x "$work_dir/bin/aws"

run_case() {
  local scenario=$1 region=$2 result=0 state_key=${3:-}
  local expected_key=${state_key:-2026-2/2jk-4jk/hangy/hangy-backend/production.tfstate}
  : > "$work_dir/aws.log"
  : > "$work_dir/ci.env"
  PATH="$work_dir/bin:$PATH" AWS_MOCK_LOG="$work_dir/aws.log" MOCK_CASE="$scenario" \
    AWS_REGION="$region" CI_PROJECT_PATH=2026-2/2jk-4jk/hangy/hangy-backend \
    CI_ENV_FILE="$work_dir/ci.env" TF_STATE_KEY="$state_key" \
    bash "$repo_root/scripts/bootstrap-terraform-state.sh" \
    > "$work_dir/stdout" 2> "$work_dir/stderr" || result=$?

  if [[ "$scenario" == forbidden ]]; then
    [[ "$result" -ne 0 && ! -s "$work_dir/ci.env" ]]
    ! grep -q 's3api create-bucket\|s3api put-' "$work_dir/aws.log"
  else
    if [[ "$result" -ne 0 ]]; then
      cat "$work_dir/stderr" >&2
      return 1
    fi
    grep -Fxq "TF_STATE_BUCKET=hangy-tfstate-123456789012-$region" "$work_dir/ci.env"
    grep -Fxq "TF_STATE_KEY=$expected_key" "$work_dir/ci.env"
    grep -q 'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true' "$work_dir/aws.log"
    grep -q 'SSEAlgorithm.*AES256' "$work_dir/aws.log"
    grep -q 'versioning-configuration Status=Enabled' "$work_dir/aws.log"
    if [[ "$scenario" == existing ]]; then
      ! grep -q 's3api create-bucket' "$work_dir/aws.log"
    elif [[ "$region" == us-east-1 ]]; then
      grep -q 's3api create-bucket' "$work_dir/aws.log"
      ! grep -q LocationConstraint "$work_dir/aws.log"
    else
      grep -q "LocationConstraint=$region" "$work_dir/aws.log"
    fi
  fi
  echo "PASS: $scenario ($region)"
}

run_case create us-east-2
run_case existing us-east-2
run_case forbidden us-east-2
run_case create us-east-1
run_case existing us-east-2 previous-owner/Hangy-Backend/production.tfstate
