#!/usr/bin/env bash
# Decide the always-runs CI gate from its dependencies' results (GH-1298).
#
# Reads CI_GATE_RESULTS — a space-separated list of `needs.*.result`
# values — and exits 0 only when the gate may legitimately go green.
set -euo pipefail

results="${CI_GATE_RESULTS:-}"

if [ -z "${results// /}" ]; then
    echo "::error::no dependency results were reported to the CI gate"
    exit 1
fi

status=0
succeeded=0

for result in ${results}; do
    case "${result}" in
        success)
            succeeded=1
            ;;
        skipped) ;;
        *)
            echo "::error::dependency reported '${result}'"
            status=1
            ;;
    esac
done

if [ "${succeeded}" -eq 0 ]; then
    echo "::error::every dependency was skipped; the gate has nothing to attest"
    status=1
fi

echo "dependency results: ${results}"
exit "${status}"
