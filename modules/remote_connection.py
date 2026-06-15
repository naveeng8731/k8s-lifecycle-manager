import subprocess
import os
import sys
import platform
import yaml


# ─────────────────────────────────────────────────────────
# REMOTE CONNECTION MANAGER
#
# Handles connecting from local machine to remote k8s cluster
# Supports: Windows, Linux, Mac
#
# What it does:
#   1. Reads connection config from config/settings.yaml
#   2. Tests SSH connectivity to the remote server
#   3. Runs all kubectl/kubeadm commands ON THE REMOTE SERVER
#      via Ansible SSH — no kubectl needed on local machine
# ─────────────────────────────────────────────────────────


def load_remote_config():
    """Load remote settings from config/settings.yaml"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config", "settings.yaml"
    )
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("remote", {})


def get_platform():
    """Detect local OS"""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "mac"
    else:
        return "linux"


def expand_path(path):
    """
    Expand ~ and env vars cross-platform.
    Windows : C:/Users/name/.ssh/id_rsa  OR  ~/.ssh/id_rsa
    Linux   : ~/.ssh/id_rsa
    Mac     : ~/.ssh/id_rsa
    """
    path = os.path.expanduser(path)
    path = os.path.expandvars(path)
    path = os.path.normpath(path)
    return path


# ─────────────────────────────────────────────────────────
# TEST SSH CONNECTION
# Simple check — can we reach the remote server?
# ─────────────────────────────────────────────────────────
def test_ssh_connection(config):

    host    = config.get("host")
    user    = config.get("user")
    port    = config.get("port", 22)
    ssh_key = expand_path(config.get("ssh_key", "~/.ssh/id_rsa"))

    print(f"\n[INFO] Testing SSH connection to remote server...")
    print(f"  Host     : {host}")
    print(f"  User     : {user}")
    print(f"  Port     : {port}")
    print(f"  SSH Key  : {ssh_key}")
    print(f"  Platform : {get_platform()}\n")

    # Check SSH key file exists on local machine
    if not os.path.exists(ssh_key):
        raise Exception(
            f"SSH key not found on your local machine: {ssh_key}\n"
            f"\n  Generate one with:"
            f"\n    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa"
            f"\n\n  Copy it to the server:"
            f"\n    ssh-copy-id -i ~/.ssh/id_rsa.pub {user}@{host}"
        )

    ssh_cmd = [
        "ssh",
        "-i", ssh_key,
        "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{user}@{host}",
        "echo SSH_OK"
    ]

    result = subprocess.run(
        ssh_cmd,
        capture_output=True,
        text=True,
        timeout=15
    )

    if result.returncode != 0 or "SSH_OK" not in result.stdout:
        raise Exception(
            f"SSH connection failed to {user}@{host}:{port}\n"
            f"  Error : {result.stderr.strip()}\n"
            f"\n  Check:"
            f"\n    1. Server is reachable   : ping {host}"
            f"\n    2. SSH key is on server  : ssh-copy-id -i {ssh_key}.pub {user}@{host}"
            f"\n    3. Test manually         : ssh -i {ssh_key} {user}@{host}"
        )

    print(f"  ✔ SSH connection successful → {user}@{host}")


# ─────────────────────────────────────────────────────────
# GET CLUSTER VERSION FROM REMOTE SERVER
# Runs kubectl on the REMOTE server via SSH
# No kubectl needed on local machine
# ─────────────────────────────────────────────────────────
def get_remote_cluster_version(config):

    host    = config.get("host")
    user    = config.get("user")
    port    = config.get("port", 22)
    ssh_key = expand_path(config.get("ssh_key", "~/.ssh/id_rsa"))

    print(f"\n[INFO] Fetching cluster version from remote server...")

    ssh_cmd = [
        "ssh",
        "-i", ssh_key,
        "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        f"{user}@{host}",
        "kubectl version --output=json 2>/dev/null || echo KUBECTL_ERROR"
    ]

    result = subprocess.run(
        ssh_cmd,
        capture_output=True,
        text=True,
        timeout=15
    )

    if "KUBECTL_ERROR" in result.stdout or result.returncode != 0:
        return None

    try:
        import json
        data = json.loads(result.stdout)
        version = data.get("serverVersion", {}).get("gitVersion")
        if version:
            print(f"  ✔ Remote cluster version: {version}")
        return version
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# GET NODE LIST FROM REMOTE SERVER
# Runs kubectl on the REMOTE server via SSH
# ─────────────────────────────────────────────────────────
def get_remote_nodes(config):

    host    = config.get("host")
    user    = config.get("user")
    port    = config.get("port", 22)
    ssh_key = expand_path(config.get("ssh_key", "~/.ssh/id_rsa"))

    print(f"\n[INFO] Fetching node list from remote server...\n")

    ssh_cmd = [
        "ssh",
        "-i", ssh_key,
        "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        f"{user}@{host}",
        "kubectl get nodes -o wide"
    ]

    subprocess.run(ssh_cmd)


# ─────────────────────────────────────────────────────────
# CHECK REMOTE CLUSTER STATE
# Runs detection ON THE SERVER via SSH
# ─────────────────────────────────────────────────────────
def check_remote_cluster_state(config):

    host    = config.get("host")
    user    = config.get("user")
    port    = config.get("port", 22)
    ssh_key = expand_path(config.get("ssh_key", "~/.ssh/id_rsa"))

    print(f"\n[INFO] Checking cluster state on remote server ({host})...\n")

    # Check kubectl exists on remote
    ssh_cmd = [
        "ssh", "-i", ssh_key, "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        f"{user}@{host}",
        "which kubectl && kubectl cluster-info --request-timeout=5s && kubectl get nodes --no-headers | wc -l"
    ]

    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=20)

    if result.returncode != 0:
        return "NOT_REACHABLE"

    try:
        lines = result.stdout.strip().split("\n")
        node_count = int(lines[-1].strip())
        if node_count > 0:
            return "HEALTHY"
        return "NO_NODES"
    except Exception:
        return "UNKNOWN"


# ─────────────────────────────────────────────────────────
# FULL REMOTE SETUP
# 1. Load config
# 2. Test SSH
# 3. Check remote cluster state
# 4. Show remote node list
# ─────────────────────────────────────────────────────────
def setup_remote_connection():

    print("\n======================================")
    print(" Remote Connection Setup")
    print("======================================")

    try:
        config = load_remote_config()
    except Exception as e:
        raise Exception(
            f"Could not load remote config: {e}\n"
            f"  Make sure config/settings.yaml has a [remote] section"
        )

    if not config.get("host"):
        raise Exception(
            "Remote host not configured.\n"
            "  Edit config/settings.yaml and set remote.host to your server IP"
        )

    # Step 1: Test SSH
    test_ssh_connection(config)

    # Step 2: Check cluster state on remote server
    state = check_remote_cluster_state(config)

    print(f"\n  Remote Cluster State : {state}")

    if state == "NOT_REACHABLE":
        raise Exception(
            "Cluster is not reachable on the remote server.\n"
            "  Check kubectl is installed and cluster is running on the server."
        )

    # Step 3: Show nodes
    get_remote_nodes(config)

    print("\n  ✔ Remote connection established\n")
    return config


# ─────────────────────────────────────────────────────────
# PRINT LOCAL MACHINE SETUP INSTRUCTIONS
# Shown when --setup flag is used
# ─────────────────────────────────────────────────────────
def print_local_setup_instructions():

    os_type = get_platform()

    print("\n======================================")
    print(" Local Machine Setup — Remote Mode")
    print("======================================\n")

    print("  You only need these 3 things on your local machine:\n")
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  1. Python 3.8+                                  │")
    print("  │  2. Ansible                                      │")
    print("  │  3. pip packages: requests, pyyaml               │")
    print("  └─────────────────────────────────────────────────┘\n")
    print("  ✔ kubectl  → NOT needed (runs on remote server)")
    print("  ✔ kubeadm  → NOT needed (runs on remote server)")
    print("  ✔ kubelet  → NOT needed (runs on remote server)\n")

    if os_type == "windows":
        print("  ── WINDOWS INSTALL STEPS ──────────────────────────\n")
        print("  Step 1: Install Python 3.8+")
        print("    https://www.python.org/downloads/")
        print("    ✔ Check 'Add Python to PATH' during install\n")
        print("  Step 2: Install Ansible + pip packages")
        print("    Open Command Prompt or PowerShell:")
        print("    pip install ansible requests pyyaml\n")
        print("  Step 3: SSH Client (already installed on Windows 10/11)")
        print("    If not: Settings → Apps → Optional Features → OpenSSH Client\n")
        print("  Step 4: Generate SSH key and copy to server")
        print("    ssh-keygen -t rsa -b 4096")
        print("    ssh-copy-id ubuntu@<server-ip>\n")

    elif os_type == "mac":
        print("  ── MAC INSTALL STEPS ───────────────────────────────\n")
        print("  Step 1: Install Python + Ansible")
        print("    brew install python3 ansible\n")
        print("  Step 2: Install pip packages")
        print("    pip3 install requests pyyaml\n")
        print("  Step 3: SSH key")
        print("    ssh-keygen -t rsa -b 4096")
        print("    ssh-copy-id ubuntu@<server-ip>\n")

    else:
        print("  ── LINUX INSTALL STEPS ─────────────────────────────\n")
        print("  Step 1: Install Python + Ansible")
        print("    sudo apt install python3 python3-pip ansible -y\n")
        print("  Step 2: Install pip packages")
        print("    pip3 install requests pyyaml\n")
        print("  Step 3: SSH key")
        print("    ssh-keygen -t rsa -b 4096")
        print("    ssh-copy-id ubuntu@<server-ip>\n")

    print("  ── THEN RUN ────────────────────────────────────────\n")
    print("  Edit config/settings.yaml  → set host, user, ssh_key")
    print("  Edit inventory/hosts.ini   → set server IP")
    print("  python3 run.py --mode remote\n")
