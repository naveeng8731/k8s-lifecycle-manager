#!/usr/bin/env python3

# ─────────────────────────────────────────────────────────
# Kubernetes Lifecycle Manager
# Just run:  python3 run.py
# Works on Windows, Linux, Mac.
# Connects to remote server automatically.
# ─────────────────────────────────────────────────────────

import os
import sys
import subprocess
import platform
import shutil
import argparse


# ─────────────────────────────────────────────────────────
# STEP 1 — CHECK DEPENDENCIES
# Runs before anything else.
# Tells user exactly what to install if something is missing.
# ─────────────────────────────────────────────────────────
def check_dependencies():
    """
    Check required dependencies based on OS.

    Windows:
      - Does NOT need Ansible (uses SSH kubectl calls instead)
      - Does NOT need ssh binary (uses paramiko Python library)
      - Needs: Python, requests, pyyaml, paramiko

    Linux / Mac:
      - Needs Ansible (runs playbooks locally, SSHes to remote server)
      - Needs ssh client
      - Needs: Python, requests, pyyaml, ansible
    """
    os_type = platform.system().lower()
    errors  = []

    # ── Python packages — needed on ALL platforms ─────────
    for pkg, import_name in [("requests", "requests"), ("pyyaml", "yaml")]:
        try:
            __import__(import_name)
        except ImportError:
            errors.append(
                f"Missing Python package: {pkg}\n"
                f"    Fix: pip install {pkg}"
            )

    if os_type == "windows":
        # ── Windows — Ansible NOT needed ──────────────────
        # Discovery runs via SSH kubectl calls (paramiko)
        # paramiko is auto-installed when needed
        print("  [INFO] Windows: Ansible not required")
        print("         Discovery runs via SSH directly\n")

    else:
        # ── Linux / Mac — Ansible IS needed ───────────────
        # Ansible runs on THIS machine and SSHes to remote server
        if not shutil.which("ansible-playbook"):
            if os_type == "darwin":
                errors.append(
                    "Ansible not installed.\n"
                    "    Fix: brew install ansible\n"
                    "         OR: pip3 install ansible"
                )
            else:
                errors.append(
                    "Ansible not installed.\n"
                    "    Fix: sudo apt install ansible -y\n"
                    "         OR: pip3 install ansible"
                )

        # SSH client needed on Linux/Mac
        if not shutil.which("ssh"):
            errors.append(
                "SSH client not found.\n"
                "    Fix: sudo apt install openssh-client"
            )

    if errors:
        print("\n" + "="*55)
        print("  MISSING DEPENDENCIES")
        print("="*55 + "\n")
        for e in errors:
            print(f"  ❌ {e}\n")
        print("  After installing, run:  python3 run.py\n")
        sys.exit(1)


# ─────────────────────────────────────────────────────────
# STEP 2 — DETECT MODE
# Windows          → always REMOTE (can't run k8s locally)
# Linux/Mac with kubectl connected to cluster → LOCAL
# Linux/Mac without cluster                  → REMOTE
# ─────────────────────────────────────────────────────────
def detect_mode(forced_mode=None):

    if forced_mode:
        return forced_mode

    os_type = platform.system().lower()

    if os_type == "windows":
        print("  [INFO] Windows detected → REMOTE mode")
        print("         All commands run on the remote Linux server via SSH\n")
        return "remote"

    # Linux / Mac: check if kubectl can reach a local cluster
    if shutil.which("kubectl"):
        result = subprocess.run(
            "kubectl cluster-info --request-timeout=3s",
            shell=True, capture_output=True
        )
        if result.returncode == 0:
            print("  [INFO] Local cluster found → LOCAL mode\n")
            return "local"

    print("  [INFO] No local cluster → REMOTE mode\n")
    return "remote"


# ─────────────────────────────────────────────────────────
# ARGUMENT PARSER
# ─────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="Kubernetes Lifecycle Manager — just run: python3 run.py",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=["local", "remote"],
        default=None,
        help=(
            "local  : run directly on the k8s cluster server\n"
            "remote : run from your laptop (Windows/Linux/Mac)\n"
            "         auto-detected if not specified"
        )
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Show setup instructions for your OS"
    )
    return parser.parse_args()


# ─────────────────────────────────────────────────────────
# RUN PLAYBOOK
#
# Ansible does NOT work on Windows natively.
# In remote mode on Windows: run kubectl commands directly
# via SSH instead of using ansible-playbook.
# In local mode or Linux/Mac: use ansible-playbook normally.
# ─────────────────────────────────────────────────────────

# Global remote config reference for run_playbook to use
_remote_config_ref = None

def run_playbook(playbook, mode="local"):

    print(f"\nRunning {playbook}...\n")

    os_type = platform.system().lower()

    # Windows cannot run Ansible — use SSH-based discovery instead
    if os_type == "windows" and mode == "remote":
        _run_playbook_via_ssh(playbook)
        return

    # Linux / Mac — use ansible-playbook normally
    if mode == "remote":
        cmd = [
            "ansible-playbook", "-i", "inventory/hosts.ini",
            "--limit", "k8s_cluster", playbook
        ]
    else:
        cmd = [
            "ansible-playbook", "-i", "inventory/hosts.ini",
            "--limit", "local", playbook
        ]

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\nERROR: {playbook} failed")
        sys.exit(1)


def _run_playbook_via_ssh(playbook):
    """
    Windows replacement for ansible-playbook.
    Runs kubectl commands directly on the remote server via SSH
    and saves the output to the output/ directory locally.
    Supports: discovery.yaml and precheck.yaml
    """
    import json

    global _remote_config_ref
    if not _remote_config_ref:
        print(f"  ⚠ No remote config — skipping {playbook}")
        return

    from modules.remote_connection import ssh_run

    config   = _remote_config_ref
    host     = config.get("host")
    user     = config.get("user")
    port     = config.get("port", 22)
    ssh_key  = config.get("ssh_key")
    password = config.get("_session_password")

    os.makedirs("output", exist_ok=True)

    if "discovery" in playbook:
        print(f"  [SSH] Running discovery on {host}...")

        # Run all kubectl discovery commands
        cmds = {
            "version":      "kubectl version -o json 2>/dev/null || echo '{}'",
            "nodes":        "kubectl get nodes -o json 2>/dev/null || echo '{}'",
            "pods":         "kubectl get pods -A -o json 2>/dev/null || echo '{}'",
            "namespaces":   "kubectl get ns -o json 2>/dev/null || echo '{}'",
            "crds":         "kubectl get crd -o json 2>/dev/null || echo '{}'",
            "storageclasses":"kubectl get storageclass -o json 2>/dev/null || echo '{}'",
            "ingress":      "kubectl get ingress -A -o json 2>/dev/null || echo '{}'",
            "deployments":  "kubectl get deployment -A -o json 2>/dev/null || echo '{}'",
            "daemonsets":   "kubectl get daemonset -A -o json 2>/dev/null || echo '{}'",
            "statefulsets": "kubectl get statefulset -A -o json 2>/dev/null || echo '{}'"
        }

        data = {}
        for key, cmd in cmds.items():
            result = ssh_run(host, user, cmd,
                             port=port, ssh_key=ssh_key, password=password)
            try:
                data[key] = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
            except json.JSONDecodeError:
                data[key] = {}
            print(f"    ✔ {key}")

        with open("output/discovery_raw.json", "w") as f:
            json.dump(data, f, indent=2)

        print(f"  ✔ Discovery complete → output/discovery_raw.json")

    elif "precheck" in playbook:
        print(f"  [SSH] Running precheck on {host}...")

        cmds = {
            "nodes":        "kubectl get nodes -o json 2>/dev/null || echo '{}'",
            "pods":         "kubectl get pods -A -o json 2>/dev/null || echo '{}'",
            "events":       "kubectl get events -A -o json 2>/dev/null || echo '{}'",
            "upgrade_plan": "sudo kubeadm upgrade plan 2>/dev/null || echo 'No upgrade plan'"
        }

        data = {}
        for key, cmd in cmds.items():
            result = ssh_run(host, user, cmd,
                             port=port, ssh_key=ssh_key, password=password)
            if key == "upgrade_plan":
                data[key] = result.stdout.strip()
            else:
                try:
                    data[key] = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
                except json.JSONDecodeError:
                    data[key] = {}
            print(f"    ✔ {key}")

        with open("output/precheck_raw.json", "w") as f:
            json.dump(data, f, indent=2)

        print(f"  ✔ Precheck complete → output/precheck_raw.json")

    else:
        print(f"  [INFO] Skipping {playbook} on Windows (not needed)")


# ─────────────────────────────────────────────────────────
# AUTO-UPDATE INVENTORY
# After wizard collects connection info, write
# inventory/hosts.ini so Ansible knows where to connect
# ─────────────────────────────────────────────────────────
def update_inventory(remote_config):

    host    = remote_config.get("host")
    user    = remote_config.get("user")
    ssh_key = remote_config.get("ssh_key")
    port    = remote_config.get("port", 22)

    if ssh_key:
        host_line = (
            f"remote_server "
            f"ansible_host={host} "
            f"ansible_user={user} "
            f"ansible_ssh_private_key_file={ssh_key} "
            f"ansible_port={port}"
        )
    else:
        # password auth — ansible will use ANSIBLE_SSH_PASS env var
        host_line = (
            f"remote_server "
            f"ansible_host={host} "
            f"ansible_user={user} "
            f"ansible_port={port}"
        )

    content = f"""# Auto-generated by k8s-lifecycle-manager
# Run: python3 run.py  to regenerate

[k8s_cluster]
{host_line}

[k8s_cluster:vars]
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
ansible_python_interpreter=/usr/bin/python3

[local]
localhost ansible_connection=local
"""
    os.makedirs("inventory", exist_ok=True)
    with open("inventory/hosts.ini", "w") as f:
        f.write(content)

    print(f"  [INFO] Ansible inventory updated → inventory/hosts.ini")

    # For password auth, set env var for ansible
    password = remote_config.get("_session_password")
    if password:
        os.environ["ANSIBLE_SSH_PASS"] = password
        os.environ["ANSIBLE_HOST_KEY_CHECKING"] = "False"


# ─────────────────────────────────────────────────────────
# REMOTE INSTALL
# Runs cluster_installer logic ON THE REMOTE SERVER via SSH
# ─────────────────────────────────────────────────────────
def remote_install_cluster(remote_config):
    """
    For remote mode: instead of running install locally,
    copy the installer script to the remote server and run it there.
    The installer on the server handles single/multi-node questions.
    """
    from modules.remote_connection import ssh_run

    host     = remote_config.get("host")
    user     = remote_config.get("user")
    port     = remote_config.get("port", 22)
    ssh_key  = remote_config.get("ssh_key")
    password = remote_config.get("_session_password")

    print("\n======================================")
    print(" REMOTE CLUSTER INSTALLATION")
    print("======================================\n")
    print(f"  Target server : {user}@{host}")
    print(f"  The installation will run ON THE SERVER\n")

    # Ask cluster type HERE on local machine
    # then pass the answer to the remote script
    print("  What type of cluster do you want to install on the server?\n")
    print("  1) Single-node  — 1 server (control plane + worker)")
    print("                    Good for: testing, development")
    print()
    print("  2) Multi-node   — 1 control plane + worker nodes")
    print("                    Good for: production")
    print()

    while True:
        choice = input("  Choose [1/2]: ").strip()
        if choice in ["1", "2"]:
            break
        print("  Please enter 1 or 2")

    cluster_type = "single" if choice == "1" else "multi"

    worker_ips = []
    if cluster_type == "multi":
        print("\n  Worker node IPs (servers that will join the cluster)")
        print("  These must be reachable FROM the control plane server\n")
        while True:
            w = input(f"  Worker {len(worker_ips)+1} IP (or press Enter to finish): ").strip()
            if not w:
                break
            worker_ips.append(w)
            print(f"  ✔ Worker {w} added")

        if not worker_ips:
            print("\n  No workers added — switching to single-node")
            cluster_type = "single"
        else:
            print(f"\n  ✔ {len(worker_ips)} worker(s) configured")

    # Fetch stable version
    print("\n  [INFO] Fetching latest stable Kubernetes version...")
    result = ssh_run(
        host, user,
        "curl -sL https://dl.k8s.io/release/stable.txt",
        port=port, ssh_key=ssh_key, password=password
    )
    k8s_version = result.stdout.strip() if result.returncode == 0 else "v1.36.2"
    print(f"  [INFO] Will install Kubernetes {k8s_version}")

    print(f"\n  Summary:")
    print(f"    Server       : {host}")
    print(f"    Cluster type : {'Single-node' if cluster_type == 'single' else f'Multi-node ({1+len(worker_ips)} nodes)'}")
    print(f"    K8s version  : {k8s_version}")
    if worker_ips:
        for i, w in enumerate(worker_ips, 1):
            print(f"    Worker {i}      : {w}")
    print()

    # Ask which IP to use for kubeadm init
    # This fixes the "node not ready" issue when server has multiple interfaces
    print("\n  [INFO] Fetching network interfaces from server...")
    ip_result = ssh_run(
        host, user,
        "hostname -I",
        port=port, ssh_key=ssh_key, password=password
    )
    all_ips = [ip for ip in ip_result.stdout.strip().split()
               if not ip.startswith("127.") and ":" not in ip]

    node_ip = all_ips[0] if all_ips else host

    if len(all_ips) > 1:
        print(f"\n  ⚠  Multiple network interfaces found on {host}:")
        for i, ip in enumerate(all_ips, 1):
            marker = " ← auto-selected" if ip == node_ip else ""
            print(f"    {i}) {ip}{marker}")
        print(f"\n  Select the IP that your laptop and other nodes can reach.")
        print(f"  This will be the Kubernetes API server address (port 6443).")
        print(f"  Enter the NUMBER (e.g. 1) or the full IP (e.g. 192.168.1.229).")
        user_input = input(f"  Choose [default: {node_ip}]: ").strip()

        if user_input:
            # Accept number like "1", "2", "3" OR full IP like "192.168.1.229"
            if user_input.isdigit():
                idx = int(user_input) - 1
                if 0 <= idx < len(all_ips):
                    node_ip = all_ips[idx]
                    print(f"  ✔ Selected: {node_ip}")
                else:
                    print(f"  ⚠ Invalid number — using default: {node_ip}")
            else:
                # User typed the full IP directly
                node_ip = user_input
                print(f"  ✔ Using: {node_ip}")
    else:
        print(f"  [INFO] Using IP: {node_ip}")

    confirm = input("\n  Proceed with installation on the remote server? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("\n  Installation aborted.\n")
        return False

    # Build remote install script
    ver = k8s_version.lstrip("v")
    parts = ver.split(".")
    minor_ver = f"v{parts[0]}.{parts[1]}"

    # ── Auto-detect safe pod CIDR ────────────────────────────
    if node_ip.startswith("192.168."):
        pod_cidr = "10.244.0.0/16"
    elif node_ip.startswith("10."):
        pod_cidr = "192.168.0.0/16"
    else:
        pod_cidr = "10.244.0.0/16"
    print(f"  [INFO] Pod network CIDR : {pod_cidr}")

    # ── Configure passwordless sudo if using password auth ───
    # Needed when user (e.g. administrator) requires sudo password
    if password:
        print(f"\n  [INFO] Configuring sudo access for {user}...")
        nopasswd = user + " ALL=(ALL) NOPASSWD:ALL"
        sudoers_file = "/etc/sudoers.d/99-" + user + "-nopasswd"
        sudoers_cmd = "echo " + password + " | sudo -S bash -c 'echo " + nopasswd + " > " + sudoers_file + "'"
        sudo_result = ssh_run(
            host, user, sudoers_cmd,
            port=port, ssh_key=ssh_key, password=password
        )
        if sudo_result.returncode == 0:
            print(f"  ✔ Sudo configured")
        else:
            print(f"  ⚠ Could not configure sudo automatically.")
            print(f"  Run this on the server first, then re-run:")
            print(f"    echo \"{user} ALL=(ALL) NOPASSWD:ALL\" | sudo tee /etc/sudoers.d/99-{user}")
            cont = input("  Continue anyway? (yes/no): ").strip().lower()
            if cont != "yes":
                return False

    install_script = f"""
set -e
echo "=== STEP 1: Installing dependencies ==="
sudo apt-get update -qq
sudo apt-get install -y apt-transport-https ca-certificates curl gpg socat conntrack ebtables ipset

echo "=== STEP 2: Installing containerd ==="
sudo apt-get install -y containerd
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml > /dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl enable containerd && sudo systemctl restart containerd

echo "=== STEP 3: Disabling swap ==="
sudo swapoff -a
sudo sed -i '/swap/d' /etc/fstab

echo "=== STEP 4: Kernel modules ==="
echo -e 'overlay\\nbr_netfilter' | sudo tee /etc/modules-load.d/k8s.conf
sudo modprobe overlay && sudo modprobe br_netfilter
printf 'net.bridge.bridge-nf-call-iptables=1\\nnet.bridge.bridge-nf-call-ip6tables=1\\nnet.ipv4.ip_forward=1\\n' | sudo tee /etc/sysctl.d/k8s.conf
sudo sysctl --system -q

echo "=== STEP 5: Installing Kubernetes tools ==="
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg --batch --yes
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update -qq
sudo apt-get install -y kubeadm={ver}-* kubelet={ver}-* kubectl={ver}-* 2>/dev/null || sudo apt-get install -y kubeadm={ver} kubelet={ver} kubectl={ver}
sudo apt-mark hold kubeadm kubelet kubectl
sudo systemctl enable kubelet

echo "=== STEP 6: kubeadm init ==="
sudo kubeadm init --kubernetes-version={k8s_version} --pod-network-cidr={pod_cidr} --apiserver-advertise-address={node_ip} --node-name=$(hostname) 2>&1 | tee /tmp/kubeadm_init.log

echo "=== STEP 7: Configure kubectl ==="
mkdir -p $HOME/.kube
sudo cp /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

echo "=== STEP 8: Install Calico CNI ==="
sleep 15
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml

{"" if cluster_type == "multi" else '''
echo "=== STEP 9: Remove control-plane taint (single-node) ==="
kubectl taint nodes --all node-role.kubernetes.io/control-plane- 2>/dev/null || true
'''}

echo "INSTALL_COMPLETE"
"""

    print(f"\n  [INFO] Running installation on {host}...\n")
    print(f"  This will take 5-10 minutes. Please wait.\n")

    result = ssh_run(
        host, user, install_script,
        port=port, ssh_key=ssh_key, password=password,
        timeout=600
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0 or "INSTALL_COMPLETE" not in result.stdout:
        print(f"\n  ❌ Installation failed on {host}")
        print(f"\n  Possible causes:")
        print(f"    1. sudo password required — user needs passwordless sudo")
        print(f"       Fix on server: echo '{user} ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/{user}")
        print(f"    2. Internet not reachable from server")
        print(f"       Fix: ping 8.8.8.8  from the server")
        print(f"    3. Ports blocked — check firewall")
        print(f"       Fix: sudo ufw status")
        print(f"\n  Check logs on server:")
        print(f"    ssh {user}@{host}")
        print(f"    cat /tmp/kubeadm_init.log")
        print(f"    sudo journalctl -u kubelet -n 50 --no-pager")
        return False

    print(f"\n  ✔ Control plane installed on {host}")

    # Multi-node: join workers
    if cluster_type == "multi" and worker_ips:

        # Get join command from control plane
        result = ssh_run(
            host, user,
            "sudo kubeadm token create --print-join-command",
            port=port, ssh_key=ssh_key, password=password
        )
        join_cmd = result.stdout.strip()

        if not join_cmd:
            print("  ⚠ Could not get join command — workers must be joined manually")
        else:
            for w_ip in worker_ips:
                print(f"\n  [INFO] Joining worker {w_ip}...")
                w_script = f"""
set -e
sudo apt-get update -qq
sudo apt-get install -y apt-transport-https ca-certificates curl gpg socat conntrack
sudo apt-get install -y containerd
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml > /dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl enable containerd && sudo systemctl restart containerd
sudo swapoff -a && sudo sed -i '/swap/d' /etc/fstab
echo -e 'overlay\\nbr_netfilter' | sudo tee /etc/modules-load.d/k8s.conf
sudo modprobe overlay && sudo modprobe br_netfilter
printf 'net.bridge.bridge-nf-call-iptables=1\\nnet.ipv4.ip_forward=1\\n' | sudo tee /etc/sysctl.d/k8s.conf
sudo sysctl --system -q
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg --batch --yes
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update -qq
sudo apt-get install -y kubeadm={ver}-* kubelet={ver}-* 2>/dev/null || sudo apt-get install -y kubeadm={ver} kubelet={ver}
sudo apt-mark hold kubeadm kubelet
sudo systemctl enable kubelet
sudo {join_cmd}
echo "WORKER_JOINED"
"""
                w_result = ssh_run(
                    w_ip, user, w_script,
                    port=port, ssh_key=ssh_key, password=password,
                    timeout=300
                )

                if "WORKER_JOINED" in w_result.stdout:
                    print(f"  ✔ Worker {w_ip} joined successfully")
                else:
                    print(f"  ⚠ Worker {w_ip} may have failed — check manually")
                    print(f"    ssh {user}@{w_ip} then run: sudo {join_cmd}")

    print("\n======================================")
    print(" INSTALLATION COMPLETE ✔")
    print("======================================\n")
    print(f"  Kubernetes {k8s_version} is now running on {host}")
    print(f"  Run: ssh {user}@{host} kubectl get nodes\n")
    return True


# ─────────────────────────────────────────────────────────
# UPGRADE FLOW
# ─────────────────────────────────────────────────────────
def run_upgrade_flow(data, mode="local"):

    from modules.discovery              import detect_cluster_info
    from modules.component_detector     import detect_components
    from modules.report_generator       import save_inventory, save_application_inventory
    from modules.version_manager        import get_upgrade_information
    from modules.validation             import check_cluster_health
    from modules.application_inventory  import get_application_inventory
    from modules.risk_analyzer          import analyze_risk
    from modules.compatibility_engine   import check_compatibility
    from modules.upgrade_engine         import build_upgrade_plan
    from modules.upgrade_executor       import execute_upgrade
    from modules.dependency_engine      import analyze_dependencies

    inventory = detect_cluster_info(data)
    inventory["components"] = detect_components(data)
    inventory["mode"] = mode

    applications = get_application_inventory()
    inventory["applications"] = applications

    risks         = analyze_risk(inventory, applications)
    compatibility = check_compatibility(inventory["cluster_version"], applications)
    inventory["risks"]         = risks
    inventory["compatibility"] = compatibility
    inventory["health"]        = check_cluster_health()

    version_info    = get_upgrade_information()
    current_version = version_info.get("current_version") or inventory.get("cluster_version")
    stable_version  = version_info.get("stable_version")
    inventory["current_version"] = current_version
    inventory["stable_version"]  = stable_version

    print("\n======================================")
    print(" Version Analysis")
    print("======================================\n")
    print(f"  Current Version : {current_version}")
    print(f"  Stable Version  : {stable_version}")
    print(f"  Mode            : {mode.upper()}")

    if current_version and stable_version:
        if current_version == stable_version:
            print("\n  ✔ Already on stable version — no upgrade required")
            save_inventory(inventory)
            save_application_inventory(applications)
            print("\nDone.\n")
            return
        else:
            print("\n  ⚠ Upgrade available")
    else:
        print("\n  ❌ Could not determine versions")
        save_inventory(inventory)
        save_application_inventory(applications)
        return

    dependency_report = analyze_dependencies(applications, stable_version, current_version)
    inventory["dependency_report"] = dependency_report

    upgrade_plan = build_upgrade_plan(inventory, compatibility, risks)
    inventory["upgrade_plan"] = upgrade_plan

    print("\n======================================")
    print(" Upgrade Plan")
    print("======================================\n")
    print(f"  Eligible       : {upgrade_plan.get('eligible')}")
    print(f"  Target Version : {upgrade_plan.get('target_version')}")
    print(f"  Risk Score     : {upgrade_plan.get('risk_score')}")

    for p in upgrade_plan.get("phases", []):
        print(f"\n  - {p.get('phase')}")
        for a in p.get("actions", []):
            print(f"      * {a}")

    if upgrade_plan.get("blockers"):
        print("\n  Blockers:")
        for b in upgrade_plan["blockers"]:
            print(f"    - {b}")

    nodes = [
        n.get("metadata", {}).get("name")
        for n in data.get("nodes", {}).get("items", [])
        if n.get("metadata", {}).get("name")
    ]

    if upgrade_plan.get("eligible"):
        print("\n=== EXECUTION STARTED ===\n")
        confirm = input("Proceed with upgrade? (yes/no): ").strip().lower()
        if confirm == "yes":
            success = execute_upgrade(upgrade_plan, nodes, mode=mode)
            if not success:
                print("\n❌ Upgrade failed — check summary above")
        else:
            print("\nUpgrade aborted by user")
    else:
        print("\nUpgrade not eligible — skipping")

    save_inventory(inventory)
    save_application_inventory(applications)
    print("\nDone.\n")


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():

    # ── 1. Check dependencies ─────────────────────────────
    check_dependencies()

    args = parse_args()

    print("\n======================================")
    print(" Kubernetes Lifecycle Manager")
    print("======================================\n")

    # ── 2. Setup help ─────────────────────────────────────
    if args.setup:
        from modules.remote_connection import print_local_setup_instructions
        print_local_setup_instructions()
        return

    # ── 3. Detect local or remote mode ───────────────────
    mode = detect_mode(args.mode)
    print(f"  Mode : {mode.upper()}\n")

    # ── 4. REMOTE MODE — run connection wizard ────────────
    remote_config = None

    if mode == "remote":
        from modules.remote_connection import setup_remote_connection
        print("[INFO] Starting connection wizard...\n")
        try:
            remote_config = setup_remote_connection()
        except Exception as e:
            print(f"\n❌ Connection failed: {e}")
            print("\nFor help: python3 run.py --setup\n")
            sys.exit(1)

        # Auto-update inventory/hosts.ini
        update_inventory(remote_config)

        # Store reference so run_playbook can use SSH on Windows
        global _remote_config_ref
        _remote_config_ref = remote_config

    # ── 5. DETECT CLUSTER STATE ───────────────────────────
    # In remote mode: reuse the state already detected during
    # setup_remote_connection() — avoids a duplicate SSH check
    # that fails when password is not passed correctly.

    if mode == "remote":
        _password  = remote_config.get("_session_password")
        _raw_state = remote_config.get("_cluster_state", "UNKNOWN")
        _node_count= remote_config.get("_node_count", 0)

        # If state was not stored, do a fresh check with password
        if _raw_state == "UNKNOWN":
            from modules.remote_connection import (
                check_remote_cluster_state, get_remote_nodes
            )
            _raw_state, _node_count = check_remote_cluster_state(
                remote_config, password=_password
            )

        print(f"\n[INFO] Cluster state on {remote_config.get('host')}:")
        print(f"  State      : {_raw_state}")
        if _node_count > 0:
            print(f"  Node Count : {_node_count}")

        if _raw_state == "HEALTHY":
            state = "HEALTHY"
        elif _raw_state == "NOT_INSTALLED":
            state = "NOT_INSTALLED"
        else:
            state = "UNKNOWN"

    else:
        # Check cluster state on LOCAL machine
        from modules.cluster_detector import (
            detect_cluster_state, get_tool_versions,
            print_cluster_state,
            STATE_HEALTHY, STATE_DEGRADED,
            STATE_NOT_INSTALLED, STATE_INSTALLED_NO_CLUSTER,
            STATE_UNREACHABLE
        )
        tool_versions = get_tool_versions()
        state = detect_cluster_state()
        print_cluster_state(state, tool_versions)

    # ── 6. BRANCH ON STATE ────────────────────────────────

    # ── No cluster → offer to install ─────────────────────
    if state in ["NOT_INSTALLED", "INSTALLED_NO_CLUSTER",
                 "NOT_REACHABLE", "NO_NODES"]:

        print("\n======================================")
        print(" No Cluster Found")
        print("======================================\n")

        if mode == "remote":
            print(f"  No Kubernetes cluster found on {remote_config.get('host')}\n")
        else:
            print("  No Kubernetes cluster found on this server.\n")

        print("  Options:")
        print("    install - Install a fresh Kubernetes cluster")
        print("    exit    - Exit\n")

        choice = input("Choose [install/exit]: ").strip().lower()

        if choice != "install":
            print("\nExiting.\n")
            return

        if mode == "remote":
            # Install ON THE REMOTE SERVER via SSH
            success = remote_install_cluster(remote_config)
        else:
            # Install locally
            from modules.cluster_installer import install_fresh_cluster
            success = install_fresh_cluster()

        if success:
            print("\n✔ Cluster installed! Re-run: python3 run.py\n")
        else:
            print("\n❌ Installation failed.\n")
        return

    # ── Cluster unreachable ───────────────────────────────
    elif state in ["UNREACHABLE", "UNKNOWN"]:
        print("\n======================================")
        print(" Cluster Unreachable")
        print("======================================\n")
        print("  Kubernetes API server is not responding.\n")
        print("  On the server, check:")
        print("    sudo systemctl status kubelet")
        print("    sudo systemctl restart kubelet")
        print("    sudo journalctl -u kubelet -n 50 --no-pager\n")
        if mode == "remote":
            print(f"  SSH in: ssh {remote_config.get('user')}@{remote_config.get('host')}\n")
        return

    # ── Cluster degraded ──────────────────────────────────
    elif state == "DEGRADED":
        print("\n======================================")
        print(" Cluster Degraded — Nodes Not Ready")
        print("======================================\n")
        print("  One or more nodes are NOT READY.")
        print("  Upgrading a degraded cluster is risky.\n")
        subprocess.run("kubectl get nodes -o wide", shell=True)
        print()
        if input("Continue anyway? (yes/no): ").strip().lower() != "yes":
            print("\nExiting.\n")
            return

    # ── 7. HEALTHY → DISCOVERY + UPGRADE ─────────────────
    run_playbook("playbooks/discovery.yaml", mode=mode)
    run_playbook("playbooks/precheck.yaml",  mode=mode)

    if not os.path.exists("output/discovery_raw.json"):
        print("ERROR: discovery_raw.json not found")
        sys.exit(1)

    from modules.discovery import load_discovery_data
    data = load_discovery_data()
    run_upgrade_flow(data, mode=mode)


if __name__ == "__main__":
    main()
