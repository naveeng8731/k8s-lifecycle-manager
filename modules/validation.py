import subprocess
import json

# ─────────────────────────────────────────────────────────
# VALIDATION
# Checks if all cluster nodes are Ready.
# Remote mode → runs kubectl on server via SSH
# Local mode  → runs kubectl locally
# ─────────────────────────────────────────────────────────

_remote_config = None

def set_remote_config(config):
    global _remote_config
    _remote_config = config

def check_cluster_health():
    global _remote_config

    if _remote_config and _remote_config.get("host"):
        return _check_health_remote(_remote_config)
    else:
        return _check_health_local()

def _check_health_local():
    try:
        result = subprocess.run(
            "kubectl get nodes -o json",
            shell=True, capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return "UNKNOWN"
        data   = json.loads(result.stdout)
        return _parse_health(data)
    except Exception:
        return "UNKNOWN"

def _check_health_remote(config):
    try:
        from modules.remote_connection import ssh_run
        result = ssh_run(
            config["host"], config["user"],
            "kubectl get nodes -o json 2>/dev/null",
            port=config.get("port", 22),
            ssh_key=config.get("ssh_key"),
            password=config.get("_session_password"),
            timeout=15
        )
        if result.returncode != 0 or not result.stdout.strip():
            return "UNKNOWN"
        data = json.loads(result.stdout)
        return _parse_health(data)
    except Exception:
        return "UNKNOWN"

def _parse_health(data):
    nodes    = data.get("items", [])
    ready    = 0
    not_ready= 0
    for node in nodes:
        for cond in node.get("status", {}).get("conditions", []):
            if cond.get("type") == "Ready":
                if cond.get("status") == "True":
                    ready += 1
                else:
                    not_ready += 1
    if not_ready > 0:
        return "DEGRADED"
    elif ready > 0:
        return "HEALTHY"
    return "UNKNOWN"
