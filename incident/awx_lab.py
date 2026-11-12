"""Provision and operate the scoped AWX workflow through its cluster-only API."""
import base64
import json
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


KUBECTL = ["k3s", "kubectl", "-n", "awx"]
PROJECT = "quotelab-incident"
ACTIONS = ("diagnose", "recover", "verify")


class AWX:
    def __init__(self):
        service = subprocess.check_output(
            KUBECTL + ["get", "service", "devops-awx-service", "-o", "jsonpath={.spec.clusterIP}"],
            text=True, timeout=28,
        ).strip()
        self.base = f"http://{service}"
        secret = subprocess.check_output(
            KUBECTL + ["get", "secret", "devops-awx-admin-password", "-o", "jsonpath={.data.password}"],
            timeout=28,
        )
        auth = base64.b64encode(b"admin:" + base64.b64decode(secret)).decode()
        self.headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    def request(self, path, payload=None, method=None):
        if not path.startswith("/api/"):
            path = "/api/v2/" + path
        data = None if payload is None else json.dumps(payload).encode()
        attempts = 3 if data is None and method is None else 1
        for attempt in range(attempts):
            try:
                with urlopen(Request(self.base + path, data, self.headers, method=method), timeout=18) as response:
                    body = response.read()
                    return json.loads(body) if body else None
            except HTTPError as error:
                detail = "credential request rejected" if "/credentials/" in path else error.read().decode()[:1200]
                raise RuntimeError(f"AWX {path}: HTTP {error.code}: {detail}") from None
            except (TimeoutError, URLError):
                if attempt + 1 == attempts:
                    raise

    def wait_ready(self):
        for _ in range(25):
            try:
                return self.request("ping/")["version"]
            except URLError:
                time.sleep(1)
        raise RuntimeError("AWX API did not become ready")

    def get_or_create(self, resource, name, **payload):
        items = self.request(f"{resource}/?" + urlencode({"name": name}))["results"]
        if items:
            return items[0]["id"]
        return self.request(f"{resource}/", {"name": name, **payload})["id"]

    def configure(self, directory, target):
        organization = self.request("organizations/?name=Default")["results"][0]["id"]
        target_vars = json.dumps({
            "incident_ssh_target": target,
            "incident_known_host": (directory / "known_hosts").read_text().strip(),
        })
        inventory = self.get_or_create("inventories", "QuoteLab incident inventory", organization=organization)
        if not self.request(f"inventories/{inventory}/hosts/")["count"]:
            self.request(f"inventories/{inventory}/hosts/", {"name": "localhost", "variables": target_vars})
        else:
            host = self.request(f"inventories/{inventory}/hosts/?name=localhost")["results"][0]
            if host["variables"] != target_vars:
                self.request(f"hosts/{host['id']}/", {"variables": target_vars}, method="PATCH")

        project_dir = f"/var/lib/awx/projects/{PROJECT}"
        playbook = base64.b64encode((directory / "workflow.yml").read_bytes()).decode()
        for role in ("web", "task"):
            container = f"devops-awx-{role}"
            execute = KUBECTL + ["exec", f"deploy/{container}", "-c", container, "--"]
            subprocess.run(
                execute + ["sh", "-c", f"mkdir -p {project_dir} && printf %s {playbook} | base64 -d > {project_dir}/workflow.yml"],
                timeout=20, check=True,
            )
        project = self.get_or_create("projects", "QuoteLab incident playbooks",
                                     organization=organization, scm_type="", local_path=PROJECT)
        kind = self.get_or_create(
            "credential_types", "QuoteLab restricted SSH key", kind="cloud",
            inputs={"fields": [{"id": "key", "label": "SSH private key", "type": "string",
                                "secret": True, "multiline": True}], "required": ["key"]},
            injectors={"file": {"template": "{{ key }}\n"},
                       "env": {"INCIDENT_SSH_KEY": "{{ tower.filename }}"}},
        )
        key_input = {"key": (directory / "awx").read_text()}
        credential = self.get_or_create(
            "credentials", "QuoteLab incident temporary credential", credential_type=kind,
            organization=organization, inputs=key_input,
        )
        self.request(f"credentials/{credential}/", {"inputs": key_input}, method="PATCH")

        execution = self.get_or_create("execution_environments", "QuoteLab AWX EE 24.6.1",
                                       image="quay.io/ansible/awx-ee:24.6.1", pull="missing")
        jobs = {}
        for action in ACTIONS:
            job = self.get_or_create("job_templates", f"QuoteLab | {action.title()}", inventory=inventory,
                                     project=project, playbook="workflow.yml", job_type="run", timeout=100,
                                     execution_environment=execution,
                                     extra_vars=json.dumps({"incident_action": action}))
            template = self.request(f"job_templates/{job}/")
            if template["execution_environment"] != execution or template["timeout"] != 100:
                self.request(f"job_templates/{job}/", {"execution_environment": execution, "timeout": 100}, method="PATCH")
            assigned = self.request(f"job_templates/{job}/credentials/")["results"]
            if not any(item["id"] == credential for item in assigned):
                self.request(f"job_templates/{job}/credentials/", {"id": credential})
            jobs[action] = job

        workflow = self.get_or_create("workflow_job_templates", "QuoteLab | Incident response",
                                      organization=organization)
        nodes_url = f"workflow_job_templates/{workflow}/workflow_nodes/"
        nodes = {node["identifier"]: node for node in self.request(nodes_url)["results"]}
        order = ("diagnose", "approval", "recover", "verify")
        for action in order:
            if action not in nodes:
                payload = {"identifier": action}
                if action != "approval":
                    payload["unified_job_template"] = jobs[action]
                nodes[action] = self.request(nodes_url, payload)
        approval = nodes["approval"]
        if approval.get("unified_job_template") is None:
            self.request(f"workflow_job_template_nodes/{approval['id']}/create_approval_template/",
                         {"name": "Approve stopping the lab CPU workers", "timeout": 120})
        for before, after in zip(order, order[1:]):
            url = f"workflow_job_template_nodes/{nodes[before]['id']}/success_nodes/"
            if not any(node["id"] == nodes[after]["id"] for node in self.request(url)["results"]):
                self.request(url, {"id": nodes[after]["id"]})
        return {"workflow": workflow, "jobs": jobs, "credential": credential}

    def launch(self, resource, object_id):
        return self.request(f"{resource}/{object_id}/launch/", {})["id"]

    def job_output(self, job):
        events = self.request(f"jobs/{job}/job_events/?event=runner_on_ok&page_size=100")["results"]
        for event in events:
            details = event["event_data"]
            lines = details.get("res", {}).get("incident_result.stdout_lines")
            if lines is not None:
                return lines
        raise RuntimeError(f"AWX job {job} has no successful action output")
