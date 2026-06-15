import subprocess
import json
import requests


def get_current_version():
    try:
        # FIX: --short was removed in Kubernetes 1.28+, use --output=json instead
        out = subprocess.run(
            ["kubectl", "version", "--output=json"],
            capture_output=True,
            text=True
        ).stdout

        data = json.loads(out)
        return data["serverVersion"]["gitVersion"]

    except Exception as e:
        print(f"  WARNING: could not get current k8s version: {e}")
        return None


def get_stable_version():
    try:
        # Kubernetes official stable channel
        url = "https://dl.k8s.io/release/stable.txt"
        return requests.get(url, timeout=5).text.strip()

    except Exception as e:
        print(f"  WARNING: could not fetch stable version: {e}")
        return None


def get_upgrade_information():

    current = get_current_version()
    stable = get_stable_version()

    return {
        "current_version": current,
        "stable_version": stable,
        "upgrade_available": current != stable if current and stable else False
    }

