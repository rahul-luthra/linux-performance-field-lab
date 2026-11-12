#!/bin/sh
set -eu
here=$(dirname "$0")

case "${SSH_ORIGINAL_COMMAND:-}" in
    start)
        systemctl is-active --quiet quotelab.service
        systemctl is-active --quiet quotelab-incident-probe.service
        sudo -n systemd-run --quiet --collect --unit=quotelab-incident-load \
            --uid="$(id -u)" --property=CPUQuota=140% --property=RuntimeMaxSec=300s --property=TasksMax=12 \
            --property=MemoryMax=80M --property=TimeoutStopSec=5s \
            /usr/bin/python3 "$here/load.py"
        systemctl show quotelab-incident-load.service -p ActiveEnterTimestampMonotonic --value
        date -u +%s.%N
        ;;
    capture)
        cat "$here/requests.jsonl"
        ;;
    stop)
        if systemctl is-active --quiet quotelab-incident-load.service; then
            sudo -n /usr/bin/systemctl stop quotelab-incident-load.service
        fi
        ;;
    *)
        exit 64
        ;;
esac
