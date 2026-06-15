import subprocess
import os
import sys
import platform
import shutil
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
#   3. Fetches kubeconfig from remote server to local machine
#   4. Sets KUBECONFIG env var so kubectl works locally
#   5. Tests kubectl connectivity to the remote cluster
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
    Windows: C:/Users/name/.ssh/id_rsa  or  ~/.ssh/id_rsa
    Linux/Mac: ~/.ssh/id_rsa
    """
    path = os.path.expanduser(path)
    path = os.path.expandvars(path)
    # Normalize separators on Windows
    path = os.path.normpath(path)
    return path


def get_ssh_cmd(config):
    """
    Build base SSH command for current platform.
    Uses 'ssh' on Linux/Mac, tries 'ssh' first on Windows
    (works with Git Bash, WSL, OpenSSH).
    """
    host     = config.get("host")
    user     = config.get("user")
    ssh_key  = expand_path(config.get("ssh_key", "~/.ssh/id_rsa"))
    port     = config.get("port", 22)

    cmd = [
        "ssh",
        "-i", ssh_key,
        "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{user}@{host}"
    ]
    return cmd


def test_ssh_connection(config):
    """Test SSH connection to remote server"""

    host = config.get("host")
    user = config.get("user")
    port = config.get("port", 22)
    ssh_key = expand_path(config.get("ssh_key", "~/.ssh/id_rsa"))

    print(f"\n[INFO] Testing SSH connection...")
    print(f"  Host     : {host}")
    print(f"  User     : {user}")
    print(f"  Port     : {port}")
    print(f"  SSH Key  : {ssh_key}")
    print(f"  Platform : {get_platform()}\n")

    # Check SSH key exists
    if not os.path.exists(ssh_key):
        raise Exception(
            f"SSH key not found: {ssh_key}\n"
            f"  Generate one with: ssh-keygen -t rsa -b 4096\n"
            f"  Then copy to server: ssh-copy-id -i {ssh_key} {user}@{host}"
        )

    ssh_cmd = get_ssh_cmd(config) + ["echo 'SSH_OK'"]

    result = subprocess.run(
        ssh_cmd,
        capture_output=True,
        text=True,
        timeout=15
    )

    if result.returncode != 0 or "SSH_OK" not in result.stdout:
        raise Exception(
            f"SSH connection failed to {user}@{host}:{port}\n"
            f"  Error: {result.stderr.strip()}\n"
            f"  Check:\n"
            f"    1. Server is reachable: ping {host}\n"
            f"    2. SSH key is authorized on server\n"
            f"    3. Run manually: ssh -i {ssh_key} {user}@{host}"
        )

    print(f"  ✔ SSH connection successful to {user}@{host}")


def fetch_kubeconfig(config):
    """
    Fetch kubeconfig from remote server to local machine.
    Uses SCP (works on Linux/Mac/Windows with OpenSSH).
    """

    host              = config.get("host")
    user              = config.get("user")
    port              = config.get("port", 22)
    ssh_key           = expand_path(config.get("ssh_key", "~/.ssh/id_rsa"))
    remote_kubeconfig = config.get("remote_kubeconfig", "/home/ubuntu/.kube/config")
    local_kubeconfig  = expand_path(config.get("local_kubeconfig", "~/.kube/remote-config"))

    # Create local .kube dir if not exists
    local_kube_dir = os.path.dirname(local_kubeconfig)
    os.makedirs(local_kube_dir, exist_ok=True)

    print(f"\n[INFO] Fetching kubeconfig from remote server...")
    print(f"  Remote : {user}@{host}:{remote_kubeconfig}")
    print(f"  Local  : {local_kubeconfig}\n")

    scp_cmd = [
        "scp",
        "-i", ssh_key,
        "-P", str(port),
        "-o", "StrictHostKeyChecking=no",
        f"{user}@{host}:{remote_kubeconfig}",
        local_kubeconfig
    ]

    result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        raise Exception(
            f"Failed to fetch kubeconfig from {host}:{remote_kubeconfig}\n"
            f"  Error: {result.stderr.strip()}\n"
            f"  Make sure kubeconfig exists on server at: {remote_kubeconfig}"
        )

    # Fix server address in kubeconfig if it points to localhost/127.0.0.1
    # Replace it with the actual remote host IP
    fix_kubeconfig_server(local_kubeconfig, host)

    print(f"  ✔ kubeconfig saved to: {local_kubeconfig}")
    return local_kubeconfig


def fix_kubeconfig_server(kubeconfig_path, remote_host):
    """
    Replace 127.0.0.1 or localhost in kubeconfig server URL
    with the actual remote host IP so kubectl works from local machine.
    """
    with open(kubeconfig_path, "r") as f:
        content = f.read()

    original = content
    content = content.replace("https://127.0.0.1:", f"https://{remote_host}:")
    content = content.replace("https://localhost:", f"https://{remote_host}:")

    if content != original:
        with open(kubeconfig_path, "w") as f:
            f.write(content)
        print(f"  [INFO] Updated kubeconfig server address → {remote_host}")


def set_kubeconfig_env(local_kubeconfig):
    """
    Set KUBECONFIG environment variable so kubectl
    uses the remote cluster config.
    """
    os.environ["KUBECONFIG"] = local_kubeconfig
    print(f"\n  [INFO] KUBECONFIG set to: {local_kubeconfig}")


def test_kubectl_remote(config):
    """Test that kubectl can reach the remote cluster"""

    host = config.get("host")
    port = config.get("port", 22)

    print(f"\n[INFO] Testing kubectl connectivity to remote cluster ({host})...")

    # Check port 6443 is open first
    result = subprocess.run(
        f"kubectl cluster-info --request-timeout=10s",
        shell=True,
        capture_output=True,
        text=True,
        timeout=15
    )

    if result.returncode != 0:
        raise Exception(
            f"kubectl cannot reach cluster at {host}:6443\n"
            f"  Error: {result.stderr.strip()}\n"
            f"  Check:\n"
            f"    1. Port 6443 is open on {host}\n"
            f"    2. kubeconfig server address is correct\n"
            f"    3. Try: kubectl --kubeconfig={os.environ.get('KUBECONFIG')} get nodes"
        )

    print(f"  ✔ kubectl connected to remote cluster at {host}")

    # Show nodes
    subprocess.run("kubectl get nodes -o wide", shell=True)


def setup_remote_connection():
    """
    Full setup flow:
    1. Load config
    2. Test SSH
    3. Fetch kubeconfig
    4. Set env var
    5. Test kubectl
    Returns the local kubeconfig path
    """

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

    # Step 2: Fetch kubeconfig
    local_kubeconfig = fetch_kubeconfig(config)

    # Step 3: Set env var
    set_kubeconfig_env(local_kubeconfig)

    # Step 4: Test kubectl
    test_kubectl_remote(config)

    print("\n  ✔ Remote connection fully established\n")
    return local_kubeconfig


def print_local_setup_instructions():
    """
    Print setup instructions for local machine based on OS.
    Shown when --mode remote is used for the first time.
    """

    os_type = get_platform()

    print("\n======================================")
    print(" Local Machine Setup Requirements")
    print("======================================\n")

    print("  The following tools must be installed on YOUR local machine:\n")

    if os_type == "windows":
        print("  WINDOWS:")
        print("  ─────────────────────────────────────")
        print("  1. Python 3.8+")
        print("     https://www.python.org/downloads/")
        print()
        print("  2. kubectl")
        print("     winget install -e --id Kubernetes.kubectl")
        print("     OR: https://kubernetes.io/docs/tasks/tools/install-kubectl-windows/")
        print()
        print("  3. Ansible (via WSL or Git Bash recommended)")
        print("     WSL: sudo apt install ansible")
        print("     pip: pip install ansible")
        print()
        print("  4. OpenSSH Client (usually pre-installed on Windows 10/11)")
        print("     Settings → Apps → Optional Features → OpenSSH Client")
        print()
        print("  5. pip packages:")
        print("     pip install requests pyyaml")

    elif os_type == "mac":
        print("  macOS:")
        print("  ─────────────────────────────────────")
        print("  1. Python 3.8+  (usually pre-installed)")
        print("     brew install python3")
        print()
        print("  2. kubectl")
        print("     brew install kubectl")
        print()
        print("  3. Ansible")
        print("     brew install ansible")
        print("     OR: pip3 install ansible")
        print()
        print("  4. pip packages:")
        print("     pip3 install requests pyyaml")

    else:
        print("  LINUX:")
        print("  ─────────────────────────────────────")
        print("  1. Python 3.8+")
        print("     sudo apt install python3 python3-pip   # Ubuntu/Debian")
        print("     sudo yum install python3               # RHEL/CentOS")
        print()
        print("  2. kubectl")
        print("     curl -LO https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl")
        print("     sudo install kubectl /usr/local/bin/")
        print()
        print("  3. Ansible")
        print("     sudo apt install ansible")
        print("     OR: pip3 install ansible")
        print()
        print("  4. pip packages:")
        print("     pip3 install requests pyyaml")

    print()
    print("  AFTER INSTALLING:")
    print("  ─────────────────────────────────────")
    print("  1. Edit config/settings.yaml → set remote.host, remote.user, remote.ssh_key")
    print("  2. Edit inventory/hosts.ini  → set your server IP and SSH details")
    print("  3. Run: python3 run.py --mode remote")
    print()
