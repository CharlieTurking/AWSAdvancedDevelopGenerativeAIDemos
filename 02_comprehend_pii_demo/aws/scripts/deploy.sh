#!/usr/bin/env bash
# Deploy the Comprehend demo: private S3 site behind CloudFront, API Gateway, one Lambda.
#
#   scripts/deploy.sh                       public site and API (API is throttled)
#   scripts/deploy.sh --allow-my-ip         API only answers to this machine's public IP
#   scripts/deploy.sh --allow-ip 203.0.113.0/24 --allow-ip 198.51.100.7/32
#   scripts/deploy.sh --synth-only          build and validate the template, create nothing
#   scripts/deploy.sh --bootstrap           first time in this account/region only
#
# Run again with different IP flags to change the allow-list. Remove everything with teardown.sh.
set -euo pipefail
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then sed -n '2,10p' "$0"; exit 0; fi
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

IPS=()
SYNTH_ONLY=0
BOOTSTRAP=0
while [ $# -gt 0 ]; do
    case "$1" in
        --allow-my-ip)
            MY_IP="$(curl -fsS --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]')" \
                || fail "Could not work out your public IP. Use --allow-ip <cidr> instead."
            IPS+=("$MY_IP/32"); echo "Allowing your IP: $MY_IP/32" ;;
        --allow-ip)
            [ $# -ge 2 ] || fail "--allow-ip needs a CIDR, e.g. 203.0.113.0/24"
            IPS+=("$2"); shift ;;
        --synth-only) SYNTH_ONLY=1 ;;
        --bootstrap)  BOOTSTRAP=1 ;;
        *) fail "Unknown option: $1 (see --help)" ;;
    esac
    shift
done

CONTEXT=()
if [ ${#IPS[@]} -gt 0 ]; then
    CONTEXT=(-c "allowed_ips=$(IFS=,; echo "${IPS[*]}")")
fi

if [ "$SYNTH_ONLY" = 1 ]; then
    echo "Synthesising only (nothing is created in AWS)..."
    cdk synth --quiet "${CONTEXT[@]}" >/dev/null
    echo "Template OK: cdk.out/ComprehendDemoStack.template.json"
    exit 0
fi

if [ "$BOOTSTRAP" = 1 ]; then
    cdk bootstrap "aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION"
elif ! aws cloudformation describe-stacks --stack-name CDKToolkit --region "$CDK_DEFAULT_REGION" >/dev/null 2>&1; then
    fail "This account/region has not been CDK-bootstrapped. Run: scripts/deploy.sh --bootstrap"
fi

cdk deploy --require-approval never --outputs-file outputs.json "${CONTEXT[@]}"

echo
python3 - <<'EOF'
import json
out = json.load(open("outputs.json"))["ComprehendDemoStack"]
print("Website :", out["SiteUrl"])
print("API     :", out["ApiUrl"])
print("Access  :", out["RestrictedToIps"])
EOF
echo "CloudFront can take a few minutes to serve a new distribution everywhere."
