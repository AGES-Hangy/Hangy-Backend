#!/usr/bin/env bash
# Exercise the real EC2 deployment ordering and failure isolation without AWS.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
mkdir "$work_dir/bin"

# Redirect the production working directory to this test's temporary directory
# and omit only the root check so the suite can run on unprivileged CI runners.
sed -e "s|/opt/hangy|$work_dir/opt|g" \
  -e '/^\[\[ "\$EUID" -eq 0 \]\]/d' \
  "$repo_root/scripts/deploy-ec2.sh" > "$work_dir/deploy.sh"

cat > "$work_dir/bin/aws" <<'MOCK'
#!/usr/bin/env bash
case "$1 $2" in
  'secretsmanager get-secret-value')
    echo '{"DATABASE_URL":"postgresql://test","JWT_SECRET_KEY":"test-jwt","PRODUCTION_ADMIN_PASSWORD":"test-bootstrap-secret"}' ;;
  'ecr get-login-password') echo test-ecr-secret ;;
  *) exit 1 ;;
esac
MOCK

cat > "$work_dir/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
echo "docker $*" >> "$MOCK_LOG"
case "$1 ${2:-}" in
  'container inspect') [[ "$3" == hangy-api ]] ;;
  'login --username') cat >/dev/null ;;
  'inspect --format') echo healthy ;;
  'run --rm')
    case "${*: -3}" in
      'alembic upgrade head') [[ "$MOCK_CASE" != migration_failure ]] ;;
      'python -m app.seed_production') [[ "$MOCK_CASE" != seed_failure ]] ;;
      *) exit 1 ;;
    esac
    ;;
esac
MOCK

cat > "$work_dir/bin/curl" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK

cat > "$work_dir/bin/flock" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK

cat > "$work_dir/bin/timeout" <<'MOCK'
#!/usr/bin/env bash
[[ "$1 $2 $3" == '--signal=TERM --kill-after=30s 600s' ]] || exit 1
shift 3
exec "$@"
MOCK

chmod +x "$work_dir/bin/"*
export PATH="$work_dir/bin:$PATH"
export MOCK_LOG="$work_dir/operations"

for scenario in success migration_failure seed_failure; do
  export MOCK_CASE="$scenario"
  : > "$MOCK_LOG"
  result=0
  bash "$work_dir/deploy.sh" registry.test/hangy:commit us-east-2 test-secret \
    > "$work_dir/output" 2>&1 || result=$?

  grep -q 'alembic upgrade head' "$MOCK_LOG"
  if [[ "$scenario" == success ]]; then
    [[ "$result" == 0 ]]
    migration_line=$(grep -n 'alembic upgrade head' "$MOCK_LOG" | cut -d: -f1)
    seed_line=$(grep -n 'python -m app.seed_production' "$MOCK_LOG" | cut -d: -f1)
    rename_line=$(grep -n 'docker rename hangy-api hangy-api-previous' "$MOCK_LOG" | cut -d: -f1)
    [[ "$migration_line" -lt "$seed_line" && "$seed_line" -lt "$rename_line" ]]
    grep -q 'docker run -d --name hangy-api' "$MOCK_LOG"
    grep -q 'Deployment healthy' "$work_dir/output"
  else
    [[ "$result" != 0 ]]
    ! grep -Eq 'docker (stop|rename)|docker rm -f hangy-api' "$MOCK_LOG"
    ! grep -q 'docker run -d' "$MOCK_LOG"
    if [[ "$scenario" == migration_failure ]]; then
      ! grep -q 'python -m app.seed_production' "$MOCK_LOG"
    else
      grep -q 'python -m app.seed_production' "$MOCK_LOG"
    fi
  fi
  ! grep -Eq 'test-bootstrap-secret|test-ecr-secret' "$work_dir/output"
  ! grep -q 'python -m app.seed$' "$MOCK_LOG"
  [[ ! -d "$work_dir/opt" ]] || [[ "$(find "$work_dir/opt" -name app.env | wc -l)" == 0 ]]
  echo "PASS: EC2 deploy $scenario"
done
