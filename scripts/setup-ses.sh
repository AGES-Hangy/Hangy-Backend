#!/usr/bin/env bash
# Read-only by default. The explicit request-production command submits to AWS.
set -Eeuo pipefail
export AWS_PAGER=""
action=${1:-check}
[[ "$action" == check || "$action" == request-production ]] || {
  echo 'Usage: setup-ses.sh [check|request-production]' >&2; exit 1;
}
: "${EMAIL_FROM:?Set EMAIL_FROM to the Terraform-managed sender}"
region=${SES_REGION:-${AWS_REGION:-us-east-2}}
require_production=${SES_REQUIRE_PRODUCTION_ACCESS:-false}
[[ "$require_production" == true || "$require_production" == false ]] || {
  echo 'SES_REQUIRE_PRODUCTION_ACCESS must be true or false.' >&2; exit 1;
}
if [[ "$action" == request-production ]]; then
  : "${SES_WEBSITE_URL:=${FRONTEND_BASE_URL:-}}"
  : "${SES_WEBSITE_URL:?Set SES_WEBSITE_URL or FRONTEND_BASE_URL}"
  : "${SES_USE_CASE_DESCRIPTION:?Describe the real SES use case, consent and bounce/complaint handling}"
  [[ "$SES_WEBSITE_URL" =~ ^https?://[^[:space:]]+$ && ${#SES_WEBSITE_URL} -le 1000 && ${#SES_USE_CASE_DESCRIPTION} -le 5000 ]] || {
    echo 'Use an HTTP(S) website URL (up to 1000 characters) and a use case up to 5000 characters.' >&2; exit 1;
  }
fi

verified() {
  local identity
  identity=$(aws sesv2 get-email-identity --region "$region" --email-identity "$1" --output json)
  if ! jq -e '.VerifiedForSendingStatus == true' <<< "$identity" >/dev/null; then
    echo "SES identity $1 is not verified in $region. Open the AWS verification email, then rerun this command/deploy." >&2
    return 1
  fi
}

verified "$EMAIL_FROM"
account=$(aws sesv2 get-account --region "$region" --output json)
if ! jq -e '.SendingEnabled == true' <<< "$account" >/dev/null; then
  echo "SES sending is disabled in $region; check the AWS account dashboard." >&2; exit 1
fi
if jq -e '.ProductionAccessEnabled == true' <<< "$account" >/dev/null; then
  echo "SES ready for production in $region; sender verified."
  exit 0
fi

review=$(jq -r '.Details.ReviewDetails.Status // "NONE"' <<< "$account")
if [[ "$action" == request-production ]]; then
  case "$review" in
    NONE|FAILED)
      aws sesv2 put-account-details --region "$region" --mail-type TRANSACTIONAL \
        --website-url "$SES_WEBSITE_URL" --use-case-description "$SES_USE_CASE_DESCRIPTION" \
        --contact-language EN --production-access-enabled
      echo "SES production access requested in $region. AWS approval is pending; rerun check after approval."
      review=PENDING
      ;;
    PENDING) echo "SES production access review is already pending in $region; no duplicate request sent." ;;
    DENIED) echo 'SES production access was denied; follow up on the existing AWS support case.' >&2; exit 1 ;;
    GRANTED) echo 'AWS reports GRANTED but production access is not enabled yet; rerun check later.' ;;
    *) echo 'Unknown SES review status; inspect the AWS account dashboard.' >&2; exit 1 ;;
  esac
fi

if [[ "$require_production" == true ]]; then
  echo "SES remains in sandbox in $region (review: $review). Production deployment requires AWS approval." >&2
  echo 'For a controlled sandbox test, set SES_REQUIRE_PRODUCTION_ACCESS=false and SES_TEST_RECIPIENT to a verified test mailbox.' >&2
  exit 1
fi
if [[ -n "${SES_TEST_RECIPIENT:-}" && "$SES_TEST_RECIPIENT" != "$EMAIL_FROM" ]]; then
  verified "$SES_TEST_RECIPIENT"
fi
echo "SES sandbox in $region: only verified recipients can receive email. No delivery test was performed."
