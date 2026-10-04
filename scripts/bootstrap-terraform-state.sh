#!/usr/bin/env bash
# Only prepares a dedicated state bucket; application resources belong to Terraform.
set -euo pipefail
: "${AWS_REGION:?AWS_REGION is required}"
: "${CI_PROJECT_PATH:?CI_PROJECT_PATH is required}"
: "${CI_ENV_FILE:?CI_ENV_FILE is required}"
export AWS_PAGER=""

account=$(aws sts get-caller-identity --query Account --output text)
bucket="hangy-tfstate-${account}-${AWS_REGION}"
state_key="${TF_STATE_KEY:-${CI_PROJECT_PATH}/production.tfstate}"
[[ "$state_key" != *$'\n'* && "$state_key" != *$'\r'* ]] || exit 1
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

if ! aws s3api head-bucket --bucket "$bucket" --expected-bucket-owner "$account" \
  2> "$work_dir/bucket-error"; then
  if ! grep -Eq '\(404\)|\(NoSuchBucket\)|\(NotFound\)' "$work_dir/bucket-error"; then
    cat "$work_dir/bucket-error" >&2
    exit 1
  fi
  if [[ "$AWS_REGION" == us-east-1 ]]; then
    aws s3api create-bucket --bucket "$bucket" --region "$AWS_REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$bucket" --region "$AWS_REGION" \
      --create-bucket-configuration "LocationConstraint=$AWS_REGION" >/dev/null
  fi
  aws s3api wait bucket-exists --bucket "$bucket" --expected-bucket-owner "$account"
fi

aws s3api put-public-access-block --bucket "$bucket" --expected-bucket-owner "$account" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$bucket" --expected-bucket-owner "$account" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-versioning --bucket "$bucket" --expected-bucket-owner "$account" \
  --versioning-configuration Status=Enabled

jq -n --arg bucket "$bucket" '{
  Version: "2012-10-17",
  Statement: [{
    Sid: "RequireTLS", Effect: "Deny", Principal: "*", Action: "s3:*",
    Resource: ["arn:aws:s3:::" + $bucket, "arn:aws:s3:::" + $bucket + "/*"],
    Condition: {Bool: {"aws:SecureTransport": "false"}}
  }]
}' > "$work_dir/bucket-policy.json"
aws s3api put-bucket-policy --bucket "$bucket" --expected-bucket-owner "$account" \
  --policy "file://$work_dir/bucket-policy.json"

printf 'TF_STATE_BUCKET=%s\nTF_STATE_KEY=%s\n' "$bucket" "$state_key" >> "$CI_ENV_FILE"
