"""Create a dedicated AWX inventory, templates and approval-gated workflow."""
import base64
import json
from pathlib import Path
import subprocess
import sys

from incident.awx_lab import AWX, KUBECTL


LABEL = "PatchLab"
PROJECT = "rolling-patch-lab"
TERMINAL = {"successful", "failed", "error", "canceled"}


def configure(awx, directory):
    config = json.loads((directory / "config.json").read_text())
    organization = awx.request("organizations/?name=Default")["results"][0]["id"]
    inventory = awx.get_or_create("inventories", f"{LABEL} | Disposable targets", organization=organization)
    group = awx.get_or_create("groups", "patch_targets", inventory=inventory)
    existing = {host["name"]: host["id"] for host in awx.request(f"inventories/{inventory}/hosts/")["results"]}
    if "localhost" not in existing:
        awx.request(f"inventories/{inventory}/hosts/", {
            "name": "localhost", "variables": json.dumps({"ansible_connection": "local"}),
        })
    for name, port in config["ssh_ports"].items():
        variables = json.dumps({"ansible_host": config["host"], "ansible_port": port,
                                "ansible_user": "labpatch", "ansible_python_interpreter": "/usr/bin/python3"})
        if name in existing:
            host_id = existing[name]
            awx.request(f"hosts/{host_id}/", {"variables": variables}, method="PATCH")
        else:
            host_id = awx.request(f"inventories/{inventory}/hosts/", {"name": name, "variables": variables})["id"]
        path = f"groups/{group}/hosts/"
        if not any(row["id"] == host_id for row in awx.request(path)["results"]):
            awx.request(path, {"id": host_id})

    destination = f"/var/lib/awx/projects/{PROJECT}"
    source = Path(__file__).resolve().parent
    for role in ("web", "task"):
        container = f"devops-awx-{role}"
        commands = [f"mkdir -p {destination}"]
        for filename in ("rollout.yml", "audit.yml"):
            encoded = base64.b64encode((source / filename).read_bytes()).decode()
            commands.append(f"printf %s {encoded} | base64 -d > {destination}/{filename}")
        subprocess.run(
            KUBECTL + ["exec", f"deploy/{container}", "-c", container, "--", "sh", "-c", " && ".join(commands)],
            check=True, timeout=45,
        )
    project = awx.get_or_create("projects", f"{LABEL} | Rolling maintenance playbooks",
                                organization=organization, scm_type="", local_path=PROJECT)
    credential_type = awx.get_or_create(
        "credential_types", f"{LABEL} | Lab SSH and pool control", kind="cloud",
        inputs={"fields": [
            {"id": "key", "label": "SSH private key", "type": "string", "secret": True, "multiline": True},
            {"id": "pinned", "label": "Pinned host keys", "type": "string", "multiline": True},
            {"id": "token", "label": "Pool control token", "type": "string", "secret": True},
        ], "required": ["key", "pinned", "token"]},
        injectors={"file": {"template.key": "{{ key }}", "template.hosts": "{{ pinned }}"},
                   "env": {"PATCH_SSH_KEY": "{{ tower.filename.key }}",
                           "PATCH_KNOWN_HOSTS": "{{ tower.filename.hosts }}",
                           "PATCH_POOL_TOKEN": "{{ token }}"}},
    )
    inputs = {"key": (directory / "awx").read_text(), "pinned": (directory / "known_hosts").read_text(),
              "token": config["token"]}
    credential = awx.get_or_create("credentials", f"{LABEL} | Temporary run credential", organization=organization,
                                  credential_type=credential_type, inputs=inputs)
    awx.request(f"credentials/{credential}/", {"inputs": inputs}, method="PATCH")

    execution = awx.get_or_create("execution_environments", f"{LABEL} | AWX EE 24.6.1",
                                  image="quay.io/ansible/awx-ee:24.6.1", pull="missing")
    jobs = {}
    for node, limit in (("preflight", ""), ("canary", "patch-canary"), ("peer", "patch-peer"),
                        ("containment", "localhost")):
        action = "apply" if node in {"canary", "peer"} else "preflight"
        playbook = "audit.yml" if node == "containment" else "rollout.yml"
        variables = {**config["package"], "patch_action": action, "pool_url": config["pool_url"]}
        job = awx.get_or_create("job_templates", f"{LABEL} | {node.title()}",
                                inventory=inventory, project=project, playbook=playbook, limit=limit,
                                execution_environment=execution, timeout=300, ask_variables_on_launch=True,
                                extra_vars=json.dumps(variables))
        awx.request(f"job_templates/{job}/", {"extra_vars": json.dumps(variables)}, method="PATCH")
        path = f"job_templates/{job}/credentials/"
        if not any(row["id"] == credential for row in awx.request(path)["results"]):
            awx.request(path, {"id": credential})
        jobs[node] = job

    workflow = awx.get_or_create("workflow_job_templates", f"{LABEL} | Rolling Linux patch",
                                 organization=organization, ask_variables_on_launch=True)
    path = f"workflow_job_templates/{workflow}/workflow_nodes/"
    nodes = {row["identifier"]: row for row in awx.request(path)["results"]}
    for name in ("preflight", "approval", "canary", "peer", "containment"):
        if name not in nodes:
            data = {"identifier": name}
            if name != "approval":
                data["unified_job_template"] = jobs[name]
            nodes[name] = awx.request(path, data)
    approval = nodes["approval"]
    if approval.get("unified_job_template") is None:
        awx.request(f"workflow_job_template_nodes/{approval['id']}/create_approval_template/",
                    {"name": "Approve scoped patch and rolling reboots", "timeout": 150})
    for before, after, outcome in (("preflight", "approval", "success"), ("approval", "canary", "success"),
                                   ("canary", "peer", "success"), ("canary", "containment", "failure")):
        path = f"workflow_job_template_nodes/{nodes[before]['id']}/{outcome}_nodes/"
        if not any(row["id"] == nodes[after]["id"] for row in awx.request(path)["results"]):
            awx.request(path, {"id": nodes[after]["id"]})
    return {"workflow": workflow, "credential": credential, "jobs": jobs, "awx_version": awx.wait_ready()}


def action_events(awx, job):
    events = awx.request(f"jobs/{job}/job_events/?event=runner_on_ok&page_size=200")["results"]
    clean = []
    for event in events:
        value = event["event_data"].get("res", {}).get("msg")
        if isinstance(value, dict) and "event" in value and "time" in value:
            clean.append({**value, "time": float(value["time"])})
    return clean


def main():
    directory = Path(sys.argv[1]).resolve()
    awx = AWX()
    objects = configure(awx, directory)
    (directory / "objects.json").write_text(json.dumps(objects))
    print(f"Workflow {objects['workflow']} configured and ready.", flush=True)


if __name__ == "__main__":
    main()
