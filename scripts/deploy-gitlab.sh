#!/usr/bin/env bash
# One resource_group covers provisioning, publishing and the remote deployment.
set -Eeuo pipefail
umask 077
for name in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY FRONTEND_BASE_URL CI_JOB_JWT_V2 CI_PROJECT_PATH CI_SERVER_URL CI_COMMIT_SHA CI_PIPELINE_ID CI_JOB_ID; do
  [[ -n "${!name:-}" ]] || { echo "Missing CI/CD variable: $name" >&2; exit 1; }
done
export AWS_REGION="${AWS_REGION:-us-east-2}"
export AWS_DEFAULT_REGION="$AWS_REGION" AWS_PAGER=""

# Reject an older queued pipeline after a newer commit has reached main.
latest=$(git ls-remote origin refs/heads/main | cut -f1)
[[ "$latest" == "$CI_COMMIT_SHA" ]] || {
  echo 'This pipeline is no longer the head of main; use the latest pipeline.' >&2
  exit 1
}

work_dir=$(mktemp -d)
cleanup() {
  result=$?
  trap - EXIT
  docker rm -f hangy-smoke >/dev/null 2>&1 || true
  docker buildx rm hangy-builder >/dev/null 2>&1 || true
  rm -rf -- "$work_dir"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 1' INT TERM
export DOCKER_CONFIG="$work_dir/docker"
mkdir -m 700 "$DOCKER_CONFIG"

# Verify Docker/ARM support before creating any billable resources.
docker info >/dev/null
case "$(docker info --format '{{.Architecture}}')" in
  aarch64|arm64) ;;
  x86_64|amd64) docker run --privileged --rm tonistiigi/binfmt --install arm64 ;;
  *) echo 'The Docker runner must be Linux AMD64 or ARM64.' >&2; exit 1 ;;
esac

export CI_ENV_FILE="$work_dir/state.env"
bash scripts/bootstrap-terraform-state.sh
while IFS='=' read -r name value; do
  export "$name=$value"
done < "$CI_ENV_FILE"
terraform -chdir=infra/terraform init -reconfigure -input=false -lockfile=readonly \
  -backend-config="bucket=$TF_STATE_BUCKET" \
  -backend-config="key=$TF_STATE_KEY" \
  -backend-config="region=$AWS_REGION"

export TF_VAR_aws_region="$AWS_REGION"
export TF_VAR_gitlab_project_path="$CI_PROJECT_PATH"
export TF_VAR_gitlab_url="$CI_SERVER_URL"
export TF_VAR_frontend_base_url="$FRONTEND_BASE_URL"
export TF_VAR_cors_origins="${CORS_ORIGINS:-[]}"
export TF_VAR_api_allowed_cidrs="${API_ALLOWED_CIDRS:-[\"0.0.0.0/0\"]}"
unset TF_VAR_gitlab_oidc_provider_arn
if ! state=$(terraform -chdir=infra/terraform state list 2> "$work_dir/state-error"); then
  if ! grep -q 'No state file' "$work_dir/state-error"; then
    cat "$work_dir/state-error" >&2
    exit 1
  fi
fi
# Reuse a shared provider, but keep a provider owned by this state managed.
if ! grep -Fxq 'aws_iam_openid_connect_provider.gitlab[0]' <<< "$state"; then
  providers=$(aws iam list-open-id-connect-providers --output json)
  oidc_arn=$(jq -r --arg suffix "oidc-provider/${CI_SERVER_URL#https://}" \
    '.OpenIDConnectProviderList[].Arn | select(endswith($suffix))' <<< "$providers")
  if [[ -n "$oidc_arn" ]]; then
    export TF_VAR_gitlab_oidc_provider_arn="$oidc_arn"
    # The legacy token's audience is the GitLab URL. Preserve other clients
    # when reusing a provider managed outside this Terraform state.
    provider=$(aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$oidc_arn" --output json)
    if ! jq -e --arg audience "$CI_SERVER_URL" '.ClientIDList | index($audience) != null' <<< "$provider" >/dev/null; then
      aws iam add-client-id-to-open-id-connect-provider \
        --open-id-connect-provider-arn "$oidc_arn" --client-id "$CI_SERVER_URL"
    fi
  fi
fi
terraform -chdir=infra/terraform plan -input=false -lock-timeout=5m -out="$work_dir/hangy.tfplan"
terraform -chdir=infra/terraform apply -input=false -lock-timeout=5m "$work_dir/hangy.tfplan"
rm -f -- "$work_dir/hangy.tfplan"
terraform -chdir=infra/terraform output -json deployment_variables \
  | jq -r 'to_entries[] | "\(.key)=\(.value)"' > "$work_dir/deploy.env"
while IFS='=' read -r name value; do
  export "$name=$value"
done < "$work_dir/deploy.env"
api_url=$(terraform -chdir=infra/terraform output -raw api_url)
echo "API endpoint after deployment: $api_url"

# Provisioning credentials are no longer used after this point.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE
export AWS_SHARED_CREDENTIALS_FILE="$work_dir/no-credentials"
export AWS_CONFIG_FILE="$work_dir/no-config" AWS_EC2_METADATA_DISABLED=true
assumed=false
for attempt in {1..6}; do
  if aws sts assume-role-with-web-identity --role-arn "$AWS_ROLE_ARN" \
    --role-session-name "hangy-${CI_PIPELINE_ID}-${CI_JOB_ID}" \
    --web-identity-token "$CI_JOB_JWT_V2" --duration-seconds 3600 \
    --output json > "$work_dir/credentials.json" 2> "$work_dir/oidc-error"; then
    assumed=true
    break
  fi
  sleep 10
done
if [[ "$assumed" != true ]]; then
  echo 'Could not assume the GitLab deployment role. Check OIDC issuer/audience/subject and IAM propagation.' >&2
  exit 1
fi
AWS_ACCESS_KEY_ID=$(jq -er '.Credentials.AccessKeyId' "$work_dir/credentials.json")
AWS_SECRET_ACCESS_KEY=$(jq -er '.Credentials.SecretAccessKey' "$work_dir/credentials.json")
AWS_SESSION_TOKEN=$(jq -er '.Credentials.SessionToken' "$work_dir/credentials.json")
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
rm -f -- "$work_dir/credentials.json"
unset CI_JOB_JWT_V2

repository_uri=$(aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" \
  --query 'repositories[0].repositoryUri' --output text)
registry="${repository_uri%%/*}"
tag="${CI_COMMIT_SHA}-${CI_PIPELINE_ID}-${CI_JOB_ID}"
image="$repository_uri:$tag"
aws ecr get-login-password | docker login --username AWS --password-stdin "$registry"
docker buildx create --use --name hangy-builder --driver docker-container
docker buildx build --platform linux/arm64 --load --tag "$image" .

# Exercise the production entrypoint before publishing the image.
docker run --platform linux/arm64 -d --name hangy-smoke \
  -e DATABASE_URL=sqlite:// -e JWT_SECRET_KEY=smoke-test-only "$image"
healthy=false
for attempt in {1..30}; do
  if [[ "$(docker inspect --format '{{.State.Health.Status}}' hangy-smoke)" == healthy ]]; then
    healthy=true
    break
  fi
  sleep 2
done
if [[ "$healthy" != true ]]; then
  docker logs hangy-smoke
  exit 1
fi

docker push "$image"
digest=$(aws ecr describe-images --repository-name "$ECR_REPOSITORY" \
  --image-ids "imageTag=$tag" --query 'imageDetails[0].imageDigest' --output text)
IMAGE_URI="$repository_uri@$digest"

# Quote arguments as shell literals; never interpolate repository variables as code.
arguments=$(jq -nr --arg image "$IMAGE_URI" --arg region "$AWS_REGION" \
  --arg secret "$APP_SECRET_ARN" '[$image, $region, $secret] | @sh')
payload=$(base64 -w 0 scripts/deploy-ec2.sh)
command="printf '%s' '$payload' | base64 --decode | bash -s -- $arguments"
jq -n --arg command "$command" \
  '{commands: [$command], executionTimeout: ["1200"]}' > "$work_dir/ssm-parameters.json"
command_id=$(aws ssm send-command \
  --instance-ids "$EC2_INSTANCE_ID" --document-name AWS-RunShellScript \
  --comment "Hangy deploy $CI_COMMIT_SHA" --timeout-seconds 120 \
  --parameters "file://$work_dir/ssm-parameters.json" \
  --query 'Command.CommandId' --output text)
echo "SSM command: $command_id"

# Run Command is eventually consistent and can take longer than the CLI waiter allows.
for attempt in {1..150}; do
  if result=$(aws ssm get-command-invocation --command-id "$command_id" \
    --instance-id "$EC2_INSTANCE_ID" --output json 2> "$work_dir/ssm-error"); then
    status=$(jq -r '.Status' <<< "$result")
    case "$status" in
      Success)
        echo "Deployed $IMAGE_URI to $EC2_INSTANCE_ID"
        exit 0
        ;;
      Pending|InProgress|Delayed) ;;
      *)
        echo "SSM deployment ended with status $status. Command: $command_id"
        # Remote logs stay in SSM; they can contain application/database details.
        exit 1
        ;;
    esac
  elif ! grep -q InvocationDoesNotExist "$work_dir/ssm-error"; then
    cat "$work_dir/ssm-error" >&2
    exit 1
  fi
  sleep 10
done
echo "Timed out waiting for SSM command $command_id. Inspect it before retrying."
exit 1
