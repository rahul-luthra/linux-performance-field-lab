"""Build a NoCloud seed for one disposable Ubuntu patch target."""
import argparse
import io
import json
from pathlib import Path

import pycdlib


def write_seed(name, keys, output):
    authorized = "\n".join(f"      - {json.dumps(key)}" for key in keys)
    config = f"""#cloud-config
hostname: {name}
manage_etc_hosts: true
disable_root: true
ssh_pwauth: false
ssh_deletekeys: true
ssh_genkeytypes: [ed25519, rsa, ecdsa]
users:
  - name: labpatch
    shell: /bin/bash
    lock_passwd: true
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
{authorized}
package_update: false
package_upgrade: false
runcmd:
  - [sh, -c, "printf 'PATCH_HOST_KEY '; cat /etc/ssh/ssh_host_ed25519_key.pub" ]
  - [sh, -c, "printf 'PATCH_HOST_KEY ' >/dev/ttyS0; cat /etc/ssh/ssh_host_ed25519_key.pub >/dev/ttyS0"]
"""
    metadata = f"instance-id: rolling-lab-{name}\nlocal-hostname: {name}\n"
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, vol_ident="CIDATA", rock_ridge="1.09", joliet=3)
    for filename, contents in (("meta-data", metadata), ("user-data", config)):
        data = contents.encode()
        iso.add_fp(io.BytesIO(data), len(data), iso_path="/" + filename.replace("-", "_").upper() + ".;1",
                   rr_name=filename, joliet_path="/" + filename)
    iso.write(str(output))
    iso.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", choices=("patch-canary", "patch-peer"))
    parser.add_argument("output", type=Path)
    parser.add_argument("public_keys", type=Path, nargs="+")
    args = parser.parse_args()
    keys = [path.read_text().strip() for path in args.public_keys]
    if not all(key.startswith("ssh-ed25519 ") and "\n" not in key for key in keys):
        parser.error("Each file must contain one Ed25519 public key")
    write_seed(args.name, keys, args.output)


if __name__ == "__main__":
    main()
