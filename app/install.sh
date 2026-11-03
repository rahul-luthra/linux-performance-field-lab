#!/bin/sh
set -eu
# Install only the inspected lab source and unit. Run from this app directory.
sudo -n install -d -m 0755 /opt/linux-performance-field-lab/quotelab
javac --release 17 --add-modules jdk.httpserver -d build QuoteLab.java
sudo -n install -m 0644 build/QuoteLab.class /opt/linux-performance-field-lab/quotelab/QuoteLab.class
sudo -n install -m 0644 QuoteLab.java /opt/linux-performance-field-lab/quotelab/QuoteLab.java
sudo -n install -m 0644 quotelab.service /etc/systemd/system/quotelab.service
sudo -n systemctl daemon-reload
sudo -n systemctl start quotelab.service
attempt=0
until curl --silent --fail --max-time 2 http://127.0.0.1:8087/health; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 10 ]; then
        sudo -n journalctl -u quotelab -n 15 --no-pager
        exit 1
    fi
    sleep 1
done
sudo -n systemctl --no-pager --full status quotelab.service
