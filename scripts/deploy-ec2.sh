#!/usr/bin/env bash
# Executed as root by AWS-RunShellScript on the application's EC2 instance.
set -Eeuo pipefail
umask 077

image="${1:?Image URI is required}"
export AWS_DEFAULT_REGION="${2:?AWS region is required}"
secret_arn="${3:?Secrets Manager ARN is required}"
export AWS_PAGER=""

[[ "$EUID" -eq 0 ]] || { echo 'Run this script as root.' >&2; exit 1; }
for executable in aws docker jq flock curl timeout; do
  command -v "$executable" >/dev/null || { echo "Missing dependency: $executable" >&2; exit 1; }
done

install -d -m 700 /opt/hangy
# Also serializes remote commands if a GitLab run is cancelled while SSM keeps running.
exec 9>/opt/hangy/deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }

docker info >/dev/null
if docker container inspect hangy-api-previous >/dev/null 2>&1; then
  echo 'An interrupted deployment left hangy-api-previous. Recover it before deploying.' >&2
  exit 1
fi

work_dir=$(mktemp -d /opt/hangy/deploy.XXXXXX)
export DOCKER_CONFIG="$work_dir/docker"
mkdir -m 700 "$DOCKER_CONFIG"
env_file="$work_dir/app.env"
replacing=false
previous=false

cleanup() {
  result=$?
  trap - EXIT
  if [[ "$result" -ne 0 && "$replacing" == true ]]; then
    echo 'Deployment failed; restoring the previous container.' >&2
    docker rm -f hangy-api >/dev/null 2>&1 || true
    if [[ "$previous" == true ]]; then
      docker rename hangy-api-previous hangy-api && docker start hangy-api || \
        echo 'Automatic container recovery failed; inspect EC2 through SSM.' >&2
    fi
  fi
  docker rm -f hangy-migrate >/dev/null 2>&1 || true
  rm -rf -- "$work_dir"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 1' INT TERM

# The secret never passes through GitLab, SSM command parameters or command output.
aws secretsmanager get-secret-value --secret-id "$secret_arn" \
  --query SecretString --output text > "$work_dir/secret.json"
jq -er '
  if type != "object" then error("Expected a JSON object") else . end
  | if ((.DATABASE_URL | type) != "string" or (.JWT_SECRET_KEY | type) != "string")
    then error("DATABASE_URL and JWT_SECRET_KEY must be strings") else . end
  | if (.DATABASE_URL == "" or .JWT_SECRET_KEY == "")
    then error("DATABASE_URL and JWT_SECRET_KEY cannot be empty") else . end
  | to_entries
  | map(
      if (.key | test("^[A-Z_][A-Z0-9_]*$")) and (.value | type == "string")
      then . else error("Invalid environment entry") end
      | if (.value | test("[\r\n\u0000]"))
        then error("Environment values must be single-line strings") else . end
      | "\(.key)=\(.value)"
    )
  | .[]
' "$work_dir/secret.json" > "$env_file"

registry="${image%%/*}"
aws ecr get-login-password | docker login --username AWS --password-stdin "$registry"
docker pull "$image"

# Keep the serving container alive if migrations fail. Do not seed production data.
# Remove a migration container left behind by a killed SSM process.
docker rm -f hangy-migrate >/dev/null 2>&1 || true
timeout --signal=TERM --kill-after=30s 600s docker run --rm --name hangy-migrate \
  --env-file "$env_file" "$image" alembic upgrade head

if docker container inspect hangy-api >/dev/null 2>&1; then
  docker rename hangy-api hangy-api-previous
  previous=true
fi
replacing=true
if [[ "$previous" == true ]]; then
  docker stop --time 30 hangy-api-previous
fi

docker run -d --name hangy-api --restart unless-stopped \
  --env-file "$env_file" --publish 8000:8000 \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 "$image"

for attempt in {1..60}; do
  if [[ "$(docker inspect --format '{{.State.Health.Status}}' hangy-api)" == healthy ]] && \
    curl --fail --silent --output /dev/null --max-time 3 http://127.0.0.1:8000/health; then
    # Deployment is committed only after the application and published port respond.
    replacing=false
    if [[ "$previous" == true ]]; then
      docker rm hangy-api-previous >/dev/null
    fi
    echo "Deployment healthy: $image"
    exit 0
  fi
  sleep 2
done

echo 'New container did not pass its health check.' >&2
exit 1
