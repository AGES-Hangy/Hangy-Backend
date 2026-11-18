#!/usr/bin/env bash
# Exercise the pipeline's orchestration without Docker, AWS or network access.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
mkdir "$work_dir/bin"

cat > "$work_dir/bin/git" <<'MOCK'
#!/usr/bin/env bash
[[ "$1 $2" == 'ls-remote origin' ]] || exit 1
if [[ "$MOCK_CASE" == stale ]]; then echo 'newer-commit'; else echo "$CI_COMMIT_SHA"; fi
MOCK

cat > "$work_dir/bin/sleep" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK

cat > "$work_dir/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
echo "docker $*" >> "$MOCK_LOG"
case "$1 ${2:-}" in
  'info --format') echo "${MOCK_ARCH:-x86_64}" ;;
  'inspect --format')
    if [[ "$MOCK_CASE" == smoke_timeout ]]; then
      echo starting
    elif [[ "$MOCK_CASE" == slow_start ]] && \
      [[ "$(grep -c '^docker inspect' "$MOCK_LOG")" -le 40 ]]; then
      echo starting
    else
      echo healthy
    fi
    ;;
  'buildx build') [[ "$MOCK_CASE" != build_failure ]] ;;
  'create aquasec/trivy:'*) echo trivy-container ;;
  'cp trivy-container:/usr/local/bin/trivy')
    # Stand-in scanner: records its arguments and writes a JSON report, with an
    # unfixed HIGH vulnerability for scan_failure.
    cat > "$3" <<'TRIVY'
#!/usr/bin/env bash
echo "trivy $*" >> "$MOCK_LOG"
# The real Trivy parses every TRIVY_* variable as a flag; only the cache dir is valid here.
if env | grep '^TRIVY_' | grep -qv '^TRIVY_CACHE_DIR='; then echo 'unexpected TRIVY_* variable' >&2; exit 2; fi
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --output ]]; then
    if [[ "$MOCK_CASE" == scan_failure ]]; then
      echo '{"Results":[{"Target":"debian","Vulnerabilities":[{"VulnerabilityID":"CVE-2026-0001","PkgName":"libtest","InstalledVersion":"1.0","Severity":"HIGH","Status":"affected"},{"VulnerabilityID":"CVE-2026-0002","PkgName":"libtest","InstalledVersion":"1.0","Severity":"MEDIUM"}]}]}' > "$2"
    else
      echo '{"Results":[{"Target":"debian","Vulnerabilities":[{"VulnerabilityID":"CVE-2026-0002","PkgName":"libtest","InstalledVersion":"1.0","Severity":"MEDIUM"}]}]}' > "$2"
    fi
  fi
  shift
done
TRIVY
    chmod +x "$3"
    ;;
  'login --username') cat >/dev/null ;;
esac
MOCK

cat > "$work_dir/bin/terraform" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
shift # -chdir=infra/terraform
echo "terraform $*" >> "$MOCK_LOG"
case "$1" in
  state)
    if [[ "$MOCK_CASE" == managed ]]; then
      echo 'aws_iam_openid_connect_provider.gitlab[0]'
    fi
    ;;
  plan)
    [[ "$TF_VAR_gitlab_project_path" == '2026-2/2jk-4jk/hangy/hangy-backend' ]]
    [[ "$TF_VAR_gitlab_url" == 'https://tools.ages.pucrs.br' ]]
    [[ "$TF_VAR_email_from" == 'reset@hangy.example' ]]
    if [[ "$MOCK_CASE" == ses_sandbox ]]; then
      [[ "$TF_VAR_ses_test_recipient" == tester@hangy.example ]]
    else
      [[ -z "${TF_VAR_ses_test_recipient:-}" ]]
    fi
    [[ "$TF_VAR_api_allowed_cidrs" == '["0.0.0.0/0"]' ]]
    if [[ "$MOCK_CASE" == shared* ]]; then
      [[ "$TF_VAR_gitlab_oidc_provider_arn" == 'arn:aws:iam::123456789012:oidc-provider/tools.ages.pucrs.br' ]]
    else
      [[ -z "${TF_VAR_gitlab_oidc_provider_arn:-}" ]]
    fi
    ;;
  output)
    if [[ "$3" == deployment_variables ]]; then
      echo '{"AWS_REGION":"us-east-2","AWS_ROLE_ARN":"arn:aws:iam::123456789012:role/hangy-gitlab-deploy","ECR_REPOSITORY":"hangy","EC2_INSTANCE_ID":"i-test","APP_SECRET_ARN":"arn:aws:secretsmanager:us-east-2:123456789012:secret:hangy"}'
    else
      echo 'http://203.0.113.1:8000'
    fi
    ;;
  init|apply) ;;
  *) exit 1 ;;
esac
MOCK

cat > "$work_dir/bin/aws" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
# Record operation names only: never log credential/token arguments.
echo "aws $1 $2" >> "$MOCK_LOG"
case "$1 $2" in
  'sts get-caller-identity')
    [[ "$AWS_ACCESS_KEY_ID" == provisioning-key ]]
    echo 123456789012
    ;;
  's3api head-bucket'|'s3api put-public-access-block'|'s3api put-bucket-encryption'|\
  's3api put-bucket-versioning'|'s3api put-bucket-policy') ;;
  'iam list-open-id-connect-providers')
    if [[ "$MOCK_CASE" == shared* ]]; then
      echo '{"OpenIDConnectProviderList":[{"Arn":"arn:aws:iam::123456789012:oidc-provider/tools.ages.pucrs.br"}]}'
    else
      echo '{"OpenIDConnectProviderList":[]}'
    fi
    ;;
  'iam get-open-id-connect-provider')
    [[ "$AWS_ACCESS_KEY_ID" == provisioning-key ]]
    if [[ "$MOCK_CASE" == shared_ready ]]; then
      echo '{"ClientIDList":["sts.amazonaws.com","https://tools.ages.pucrs.br"]}'
    else
      echo '{"ClientIDList":["sts.amazonaws.com"]}'
    fi
    ;;
  'iam add-client-id-to-open-id-connect-provider')
    [[ "$AWS_ACCESS_KEY_ID" == provisioning-key && "$MOCK_CASE" == shared ]]
    [[ "$3" == --open-id-connect-provider-arn && "$4" == 'arn:aws:iam::123456789012:oidc-provider/tools.ages.pucrs.br' ]]
    [[ "$5" == --client-id && "$6" == 'https://tools.ages.pucrs.br' ]]
    ;;
  'sesv2 get-email-identity')
    [[ "$AWS_ACCESS_KEY_ID" == provisioning-key && "$3 $4" == '--region us-east-2' ]]
    if [[ "$MOCK_CASE" == ses_unverified ]]; then
      echo '{"VerifiedForSendingStatus":false}'
    else
      echo '{"VerifiedForSendingStatus":true}'
    fi
    ;;
  'sesv2 get-account')
    [[ "$AWS_ACCESS_KEY_ID" == provisioning-key && "$3 $4" == '--region us-east-2' ]]
    if [[ "$MOCK_CASE" == ses_request_pending || "$MOCK_CASE" == ses_sandbox* ]]; then
      echo '{"SendingEnabled":true,"ProductionAccessEnabled":false}'
    else
      echo '{"SendingEnabled":true,"ProductionAccessEnabled":true}'
    fi
    ;;
  'sesv2 put-account-details')
    [[ "$AWS_ACCESS_KEY_ID" == provisioning-key && "$MOCK_CASE" == ses_request_pending ]]
    ;;
  'sts assume-role-with-web-identity')
    [[ -z "${AWS_ACCESS_KEY_ID:-}" && -z "${AWS_SECRET_ACCESS_KEY:-}" && -z "${AWS_SESSION_TOKEN:-}" ]]
    [[ "$3" == --role-arn && "$4" == 'arn:aws:iam::123456789012:role/hangy-gitlab-deploy' ]]
    [[ "$7" == --web-identity-token && "$8" == oidc-token ]]
    [[ "$MOCK_CASE" != oidc_failure ]] || exit 1
    echo '{"Credentials":{"AccessKeyId":"deploy-key","SecretAccessKey":"deploy-secret","SessionToken":"deploy-token"}}'
    ;;
  'ecr describe-repositories')
    [[ "$AWS_ACCESS_KEY_ID" == deploy-key && "$AWS_SESSION_TOKEN" == deploy-token ]]
    echo '123456789012.dkr.ecr.us-east-2.amazonaws.com/hangy'
    ;;
  'ecr get-login-password') echo test-password ;;
  'ecr describe-images') echo sha256:testdigest ;;
  'ssm send-command')
    [[ "$AWS_ACCESS_KEY_ID" == deploy-key ]]
    echo test-command
    ;;
  'ssm get-command-invocation')
    if [[ "$MOCK_CASE" == ssm_failure ]]; then echo '{"Status":"Failed"}'; else echo '{"Status":"Success"}'; fi
    ;;
  *) echo "Unexpected AWS operation: $1 $2" >&2; exit 1 ;;
esac
MOCK
chmod +x "$work_dir/bin/"*

run_case() {
  local scenario=$1 expected=$2 architecture=${3:-x86_64} result=0
  : > "$work_dir/operations"
  (
    cd "$repo_root"
    export PATH="$work_dir/bin:$PATH" MOCK_LOG="$work_dir/operations"
    export MOCK_CASE="$scenario" MOCK_ARCH="$architecture"
    export CI_PROJECT_PATH=2026-2/2jk-4jk/hangy/hangy-backend
    export CI_SERVER_URL=https://tools.ages.pucrs.br
    export CI_COMMIT_SHA=test-commit CI_PIPELINE_ID=1 CI_JOB_ID=2
    export AWS_ACCESS_KEY_ID=provisioning-key AWS_SECRET_ACCESS_KEY=provisioning-secret
    export AWS_SESSION_TOKEN=provisioning-token CI_JOB_JWT_V2=oidc-token
    if [[ "$scenario" == missing_token ]]; then unset CI_JOB_JWT_V2; fi
    export FRONTEND_BASE_URL=https://hangy.example AWS_REGION=us-east-2
    export EMAIL_FROM=reset@hangy.example
    export SES_REQUIRE_PRODUCTION_ACCESS=true SES_REQUEST_PRODUCTION_ACCESS=false
    unset SES_TEST_RECIPIENT SES_WEBSITE_URL SES_USE_CASE_DESCRIPTION TF_VAR_ses_test_recipient
    if [[ "$scenario" == ses_sandbox ]]; then
      export SES_REQUIRE_PRODUCTION_ACCESS=false SES_TEST_RECIPIENT=tester@hangy.example
    fi
    if [[ "$scenario" == ses_sandbox_default ]]; then unset SES_REQUIRE_PRODUCTION_ACCESS; fi
    if [[ "$scenario" == ses_request_pending ]]; then
      export SES_REQUEST_PRODUCTION_ACCESS=true SES_USE_CASE_DESCRIPTION='Test SES use case.'
    fi
    if [[ "$scenario" == missing_sender ]]; then unset EMAIL_FROM; fi
    export SCAN_REPORT="$work_dir/trivy-report.json"
    unset CORS_ORIGINS API_ALLOWED_CIDRS TF_STATE_KEY
    bash scripts/deploy-gitlab.sh
  ) > "$work_dir/output" 2>&1 || result=$?
  if [[ "$expected" == success ]]; then
    if [[ "$result" -ne 0 ]]; then cat "$work_dir/output" >&2; return 1; fi
    grep -q 'docker buildx build --platform linux/arm64 --load' "$work_dir/operations"
    grep -q 'Deployed .*@sha256:testdigest to i-test' "$work_dir/output"
    # The pushed image is the one scanned, and the scan precedes any AWS change.
    local_image='hangy-backend:test-commit-1-2'
    image='123456789012.dkr.ecr.us-east-2.amazonaws.com/hangy:test-commit-1-2'
    grep -q 'docker create aquasec/trivy:0.76.1@sha256:' "$work_dir/operations"
    grep -Fq -- "--format json --output $work_dir/trivy-report.json $local_image" "$work_dir/operations"
    [[ "$(grep -c -- '^trivy image .*--format json' "$work_dir/operations")" -eq 1 ]]
    ! grep -q -- '--ignore-unfixed' "$work_dir/operations"
    grep -Fxq "docker tag $local_image $image" "$work_dir/operations"
    ! grep -q '^docker buildx build .*hangy:' "$work_dir/operations"
    grep -q 'No HIGH/CRITICAL vulnerabilities.' "$work_dir/output"
    scan_line=$(grep -n -- '^trivy convert' "$work_dir/operations" | cut -d: -f1)
    [[ "$scan_line" -lt "$(grep -n '^aws ' "$work_dir/operations" | head -1 | cut -d: -f1)" ]]
    [[ "$scan_line" -lt "$(grep -n '^terraform ' "$work_dir/operations" | head -1 | cut -d: -f1)" ]]
    if [[ "$architecture" == x86_64 ]]; then
      grep -q 'docker run --privileged --rm tonistiigi/binfmt --install arm64' "$work_dir/operations"
    else
      ! grep -q binfmt "$work_dir/operations"
    fi
    if [[ "$scenario" == managed ]]; then
      ! grep -q 'aws iam list-open-id-connect-providers' "$work_dir/operations"
    fi
    if [[ "$scenario" == ses_sandbox* ]]; then
      grep -q 'WARNING: SES is still in the sandbox' "$work_dir/output"
    fi
    if [[ "$scenario" == shared ]]; then
      grep -q 'aws iam add-client-id-to-open-id-connect-provider' "$work_dir/operations"
    else
      ! grep -q 'aws iam add-client-id-to-open-id-connect-provider' "$work_dir/operations"
    fi
  else
    [[ "$result" -ne 0 ]]
    case "$scenario" in
      stale) [[ ! -s "$work_dir/operations" ]] ;;
      missing_token)
        [[ ! -s "$work_dir/operations" ]]
        grep -q 'Missing CI/CD variable: CI_JOB_JWT_V2' "$work_dir/output"
        ;;
      missing_sender)
        [[ ! -s "$work_dir/operations" ]]
        grep -q 'Missing CI/CD variable: EMAIL_FROM' "$work_dir/output"
        ;;
      ses_unverified|ses_request_pending)
        grep -q 'terraform apply' "$work_dir/operations"
        ! grep -q 'docker buildx build' "$work_dir/operations"
        ! grep -q 'aws ssm send-command' "$work_dir/operations"
        if [[ "$scenario" == ses_request_pending ]]; then
          grep -q 'aws sesv2 put-account-details' "$work_dir/operations"
          grep -q 'AWS approval is pending' "$work_dir/output"
        fi
        ;;
      build_failure|oidc_failure) ! grep -q 'aws ssm send-command' "$work_dir/operations" ;;
      scan_failure)
        grep -q 'Blocked: 1 HIGH/CRITICAL vulnerabilities' "$work_dir/output"
        grep -q 'HIGH CVE-2026-0001 libtest 1.0 fixed=none status=affected' "$work_dir/output"
        # Nothing reached AWS or Terraform: no state bucket, apply, credentials or push.
        ! grep -q '^aws ' "$work_dir/operations"
        ! grep -q '^terraform ' "$work_dir/operations"
        ! grep -q 'docker push' "$work_dir/operations"
        ;;
      smoke_timeout)
        grep -q 'Smoke test did not become healthy within 300 seconds.' "$work_dir/output"
        grep -q 'docker inspect --format {{json .State.Health}} hangy-smoke' "$work_dir/operations"
        grep -q 'docker logs hangy-smoke' "$work_dir/operations"
        ! grep -q 'docker push' "$work_dir/operations"
        ! grep -q 'aws ssm send-command' "$work_dir/operations"
        ;;
      ssm_failure) grep -q 'ended with status Failed' "$work_dir/output" ;;
    esac
  fi
  ! grep -Eq 'provisioning-secret|deploy-secret|deploy-token|oidc-token' "$work_dir/output"
  echo "PASS: deploy $scenario ($architecture)"
}

run_case fresh success
run_case managed success arm64
run_case shared success
run_case shared_ready success
run_case missing_token failure
run_case missing_sender failure
run_case stale failure
run_case build_failure failure
run_case scan_failure failure
run_case slow_start success
run_case smoke_timeout failure
run_case oidc_failure failure
run_case ssm_failure failure
run_case ses_sandbox success
run_case ses_sandbox_default success
run_case ses_unverified failure
run_case ses_request_pending failure
