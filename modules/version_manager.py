import subprocess
import json
import requests


# ─────────────────────────────────────────────────────────
# VERSION MANAGER
#
# Gets two versions:
#   1. Current version — from the cluster (via SSH in remote mode)
#   2. Stable version  — from internet (dl.k8s.io/release/stable.txt)
#
# FIX: In remote mode, kubectl runs ON THE SERVER via SSH.
#      Do NOT run kubectl locally — it is not installed on Windows.
# ─────────────────────────────────────────────────────────

# Global remote config — set by run.py after connection wizard
_remote_config = None


def set_remote_config(config):
    """Called from run.py to pass remote connection details"""
    global _remote_config
    _remote_config = config


def get_current_version():
    """
    Get current Kubernetes version from the cluster.
    Remote mode → runs kubectl on server via SSH
    Local mode  → runs kubectl locally
    """
    global _remote_config

    if _remote_config and _remote_config.get("host"):
        # ── REMOTE MODE — run kubectl on server via SSH ──
        return _get_version_remote(_remote_config)
    else:
        # ── LOCAL MODE — run kubectl locally ─────────────
        return _get_version_local()


def _get_version_local():
    """Run kubectl version locally"""
    try:
        result = subprocess.run(
            ["kubectl", "version", "--output=json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return data["serverVersion"]["gitVersion"]
    except Exception as e:
        print(f"  WARNING: could not get current k8s version: {e}")
        return None


def _get_version_remote(config):
    """Run kubectl version on remote server via SSH"""
    try:
        from modules.remote_connection import ssh_run

        host     = config.get("host")
        user     = config.get("user")
        port     = config.get("port", 22)
        ssh_key  = config.get("ssh_key")
        password = config.get("_session_password")

        result = ssh_run(
            host, user,
            "kubectl version --output=json 2>/dev/null",
            port=port, ssh_key=ssh_key, password=password,
            timeout=15
        )

        if result.returncode != 0 or not result.stdout.strip():
            # Fallback — try plain kubectl version
            result = ssh_run(
                host, user,
                "kubectl version --short 2>/dev/null || kubectl version 2>/dev/null",
                port=port, ssh_key=ssh_key, password=password,
                timeout=15
            )
            # Parse plain text fallback
            for line in result.stdout.splitlines():
                if "Server Version:" in line:
                    return line.split(":")[-1].strip()
            return None

        data = json.loads(result.stdout)
        return data["serverVersion"]["gitVersion"]

    except Exception as e:
        print(f"  WARNING: could not get remote k8s version: {e}")
        return None


def get_stable_version():
    """
    Fetch latest stable Kubernetes version from internet.
    Runs on LOCAL machine — just an HTTP request.
    """
    try:
        url = "https://dl.k8s.io/release/stable.txt"
        resp = requests.get(url, timeout=5)
        return resp.text.strip()
    except Exception as e:
        print(f"  WARNING: could not fetch stable version: {e}")
        return None


def get_upgrade_information():
    current = get_current_version()
    stable  = get_stable_version()

    if current:
        print(f"  Current Version : {current}")
    else:
        print(f"  Current Version : Could not determine")

    if stable:
        print(f"  Stable Version  : {stable}")
    else:
        print(f"  Stable Version  : Could not fetch")

    return {
        "current_version":  current,
        "stable_version":   stable,
        "upgrade_available": current != stable if current and stable else False
    }
