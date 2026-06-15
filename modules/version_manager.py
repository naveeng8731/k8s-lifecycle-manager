import subprocess
import re
import requests


def get_current_version():
    try:
        out = subprocess.run(
            ["kubectl", "version", "--short"],
            capture_output=True,
            text=True
        ).stdout

        match = re.search(r"Server Version:\s*v(\d+\.\d+\.\d+)", out)
        return f"v{match.group(1)}" if match else None

    except:
        return None


def get_stable_version():
    try:
        # Kubernetes official stable channel
        url = "https://dl.k8s.io/release/stable.txt"
        return requests.get(url, timeout=5).text.strip()

    except:
        return None


def get_upgrade_information():

    current = get_current_version()
    stable = get_stable_version()

    return {
        "current_version": current,
        "stable_version": stable,
        "upgrade_available": current != stable if current and stable else False
    }
