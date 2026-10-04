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
  'inspect --format') echo healthy ;;
  'buildx build') [[ "$MOCK_CASE" != build_failure ]] ;;
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
    unset CORS_ORIGINS API_ALLOWED_CIDRS TF_STATE_KEY
    bash scripts/deploy-gitlab.sh
  ) > "$work_dir/output" 2>&1 || result=$?
  if [[ "$expected" == success ]]; then
    if [[ "$result" -ne 0 ]]; then cat "$work_dir/output" >&2; return 1; fi
    grep -q 'docker buildx build --platform linux/arm64 --load' "$work_dir/operations"
    grep -q 'Deployed .*@sha256:testdigest to i-test' "$work_dir/output"
    if [[ "$architecture" == x86_64 ]]; then
      grep -q 'docker run --privileged --rm tonistiigi/binfmt --install arm64' "$work_dir/operations"
    else
      ! grep -q binfmt "$work_dir/operations"
    fi
    if [[ "$scenario" == managed ]]; then
      ! grep -q 'aws iam list-open-id-connect-providers' "$work_dir/operations"
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
      build_failure|oidc_failure) ! grep -q 'aws ssm send-command' "$work_dir/operations" ;;
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
run_case stale failure
run_case build_failure failure
run_case oidc_failure failure
run_case ssm_failure failure
