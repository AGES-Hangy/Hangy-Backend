#!/usr/bin/env bash
# Real SES setup script with fake AWS responses; never sends email or calls AWS.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
mkdir "$work_dir/bin"
cat > "$work_dir/bin/aws" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
echo "$1 $2" >> "$MOCK_LOG"
[[ "$1" == sesv2 && "$3 $4" == '--region us-east-2' ]]
case "$2" in
  get-email-identity)
    [[ "$5" == --email-identity && "$7 $8" == '--output json' ]]
    [[ "$6" == reset@hangy.example || "$6" == tester@hangy.example ]]
    if [[ "$MOCK_CASE" == api_error ]]; then exit 17; fi
    if [[ "$MOCK_CASE" == sender_pending && "$6" == reset@hangy.example ]] || \
       [[ "$MOCK_CASE" == recipient_pending && "$6" == tester@hangy.example ]]; then
      echo '{"VerifiedForSendingStatus":false}'
    else
      echo '{"VerifiedForSendingStatus":true}'
    fi
    ;;
  get-account)
    [[ "$5 $6" == '--output json' ]]
    sending=true; production=false; review=NONE
    case "$MOCK_CASE" in
      production) production=true ;;
      disabled) sending=false ;;
      pending|request_twice) review=PENDING ;;
      denied) review=DENIED ;;
      failed) review=FAILED ;;
      granted) review=GRANTED ;;
      unknown) review=UNEXPECTED ;;
    esac
    [[ ! -f "$MOCK_REQUESTED" ]] || review=PENDING
    printf '{"SendingEnabled":%s,"ProductionAccessEnabled":%s,"Details":{"ReviewDetails":{"Status":"%s"}}}\n' "$sending" "$production" "$review"
    ;;
  put-account-details)
    [[ "$5 $6" == '--mail-type TRANSACTIONAL' && "$7 $8" == '--website-url https://hangy.example' ]]
    [[ "$9" == --use-case-description && "${10}" == 'Test use case with consent and bounce handling.' ]]
    [[ "${11} ${12} ${13}" == '--contact-language EN --production-access-enabled' ]]
    [[ "$MOCK_CASE" != request_error ]] || exit 18
    touch "$MOCK_REQUESTED"
    ;;
  *) exit 1 ;;
esac
MOCK
chmod +x "$work_dir/bin/aws"

run_case() {
  local scenario=$1 expected=$2 action=${3:-check} require_production=${4:-false} result=0
  : > "$work_dir/operations"
  rm -f -- "$work_dir/requested"
  (
    export PATH="$work_dir/bin:$PATH" MOCK_LOG="$work_dir/operations" MOCK_REQUESTED="$work_dir/requested"
    export MOCK_CASE="$scenario" EMAIL_FROM=reset@hangy.example AWS_REGION=us-west-1 SES_REGION=us-east-2
    export SES_TEST_RECIPIENT=tester@hangy.example SES_REQUIRE_PRODUCTION_ACCESS="$require_production"
    export FRONTEND_BASE_URL=https://hangy.example
    export SES_USE_CASE_DESCRIPTION='Test use case with consent and bounce handling.'
    unset SES_WEBSITE_URL
    case "$scenario" in
      missing_description) unset SES_USE_CASE_DESCRIPTION ;;
      invalid_url) export SES_WEBSITE_URL='https://bad website.example' ;;
      invalid_boolean) export SES_REQUIRE_PRODUCTION_ACCESS=yes ;;
      same_sender) export SES_TEST_RECIPIENT="$EMAIL_FROM" ;;
      no_recipient) unset SES_TEST_RECIPIENT ;;
    esac
    bash "$repo_root/scripts/setup-ses.sh" "$action" || exit $?
    if [[ "$scenario" == request_new ]]; then
      bash "$repo_root/scripts/setup-ses.sh" "$action" || exit $?
    fi
  ) > "$work_dir/output" 2>&1 || result=$?
  if [[ "$expected" == success ]]; then
    if [[ "$result" -ne 0 ]]; then cat "$work_dir/output" >&2; return 1; fi
  else
    [[ "$result" -ne 0 ]]
  fi
  case "$scenario" in
    request_new|failed|require_request)
      [[ "$(grep -c '^sesv2 put-account-details$' "$work_dir/operations")" == 1 ]]
      ;;
    *) ! grep -q '^sesv2 put-account-details$' "$work_dir/operations" || [[ "$scenario" == request_error ]] ;;
  esac
  case "$scenario" in
    missing_description|invalid_url|invalid_boolean) [[ ! -s "$work_dir/operations" ]] ;;
    same_sender|no_recipient|production) [[ "$(grep -c '^sesv2 get-email-identity$' "$work_dir/operations")" == 1 ]] ;;
    sender_pending) grep -q 'Open the AWS verification email' "$work_dir/output" ;;
    recipient_pending) grep -q 'tester@hangy.example is not verified' "$work_dir/output" ;;
    pending) grep -q 'already pending' "$work_dir/output" ;;
    denied) grep -q 'existing AWS support case' "$work_dir/output" ;;
    require_production|require_request) grep -q 'Production deployment requires AWS approval' "$work_dir/output" ;;
  esac
  echo "PASS: SES $scenario"
}

run_case production success
run_case sandbox success
run_case no_recipient success
run_case same_sender success
run_case sender_pending failure
run_case recipient_pending failure
run_case disabled failure
run_case api_error failure
run_case require_production failure check true
run_case request_new success request-production
run_case pending success request-production
run_case denied failure request-production
run_case failed success request-production
run_case granted success request-production
run_case unknown failure request-production
run_case require_request failure request-production true
run_case request_error failure request-production
run_case missing_description failure request-production
run_case invalid_url failure request-production
run_case invalid_boolean failure
