#!/bin/sh
set -eu
unit=quotelab-incident-load.service

case "${SSH_ORIGINAL_COMMAND:-}" in
    diagnose)
        date -u +%FT%TZ
        uptime | sed 's/.*load average: /Load average: /'
        systemctl show "$unit" -p ActiveState -p MainPID -p TasksCurrent -p CPUQuotaPerSecUSec
        root=$(systemctl show "$unit" -p MainPID --value)
        if [ "$root" -gt 0 ]; then
            ps -p "$root" -o comm,pcpu,time
            ps --ppid "$root" -o comm,pcpu,time
        fi
        printf 'QuoteLab '
        systemctl show quotelab.service -p ActiveState
        ;;
    recover)
        test "$(systemctl show "$unit" -p ActiveState --value)" = active
        sudo -n /usr/bin/systemctl stop "$unit"
        printf 'Stopped %s at ' "$unit"
        date -u +%FT%TZ
        ;;
    verify)
        test "$(systemctl show "$unit" -p ActiveState --value)" = inactive
        test "$(systemctl show quotelab.service -p ActiveState --value)" = active
        printf 'Load inactive. QuoteLab health: '
        curl --fail --silent --show-error --max-time 4 http://127.0.0.1:8087/health
        printf '\n'
        ;;
    *)
        printf 'Lab key only allows diagnose, recover, or verify.\n' >&2
        exit 64
        ;;
esac
