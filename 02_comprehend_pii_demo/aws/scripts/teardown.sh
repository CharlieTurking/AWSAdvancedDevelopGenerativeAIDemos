#!/usr/bin/env bash
# Remove everything deploy.sh created (site, CloudFront, API, Lambda, logs).
#
#   scripts/teardown.sh          asks before deleting
#   scripts/teardown.sh --yes    no prompt
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

if [ "${1:-}" != "--yes" ]; then
    read -r -p "Delete the ComprehendDemoStack from account $CDK_DEFAULT_ACCOUNT ($CDK_DEFAULT_REGION)? [y/N] " answer
    [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "Cancelled."; exit 0; }
fi

cdk destroy --force
rm -f outputs.json
echo "Done. The CDK bootstrap stack (CDKToolkit) is shared and was left alone."
