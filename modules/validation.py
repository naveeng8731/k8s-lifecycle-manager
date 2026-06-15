import subprocess
import json

def check_cluster_health():

    try:
        nodes = subprocess.check_output(
            "kubectl get nodes -o json",
            shell=True
        )

        nodes = json.loads(nodes)

        for node in nodes.get("items", []):
            for condition in node["status"]["conditions"]:
                if condition["type"] == "Ready":
                    if condition["status"] != "True":
                        return "DEGRADED"

        return "HEALTHY"

    except Exception:
        return "UNKNOWN"
