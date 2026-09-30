#!/bin/bash
set -e

# Server instructions mounted into the pod (ConfigMap); an explicitly set env var wins.
INSTRUCTIONS_FILE=/app/instructions/clickhouse_server_instructions.md
if [ -z "${CLICKHOUSE_SERVER_INSTRUCTIONS:-}" ] && [ -f "$INSTRUCTIONS_FILE" ]; then
    CLICKHOUSE_SERVER_INSTRUCTIONS="$(cat "$INSTRUCTIONS_FILE")"
    export CLICKHOUSE_SERVER_INSTRUCTIONS
fi

if [ "$LOAD_INITC_SECRET" == true ]; then
    # XXX: We force disable bash debug prints here to make sure we do not leak secrets to stdout/stderr.
    set +x;
    # shellcheck source=/dev/null
    source /secret/secret.env 2>/dev/null;
    if [ $? -ne 0 ]; then
        echo "Failed to load secret, check secret.env file format, there is probably something that cannot be source-ed"
    fi
    set -x;
fi

exec "$@"
