import subprocess
import socket
import os
import shutil
import time
import sys
import requests


# ─────────────────────────────────────────────────────────
# KUBERNETES CLUSTER INSTALLER
# Supports:
#   - Single-node  (control plane only, untainted)
#   - Multi-node   (control plane + N worker nodes via SSH)
#
# Uses kubeadm + containerd + Calico CNI
# ─────────────────────────────────────────────────────────

K8S_REPO_TEMPLATE = (
    "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] "
    "https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/ /"
)
CALICO_MANIFEST = (
    "https://raw.githubusercontent.com/projectcalico/calico"
    "/v3.28.0/manifests/calico.yaml"
)


# ─────────────────────────────────────────────────────────
# RUN LOCAL COMMAND
# ─────────────────────────────────────────────────────────
def run(cmd, check=False):
    print(f"\n[EXEC] {cmd}\n")
    result = subprocess.run(cmd, shell=True)
    if check and result.returncode != 0:
        raise Exception(f"Command failed: {cmd}")
    return result.returncode


# ─────────────────────────────────────────────────────────
# RUN REMOTE COMMAND VIA SSH
# Uses paramiko for password auth (works on Windows too)
# Uses system ssh for key auth
# ─────────────────────────────────────────────────────────
def run_remote(host, user, cmd, ssh_key=None, password=None, port=22, timeout=300):
    """Run a command on a remote node via SSH"""

    print(f"\n[REMOTE {host}] {cmd[:80]}...\n" if len(cmd) > 80 else f"\n[REMOTE {host}] {cmd}\n")

    if ssh_key:
        # Key auth — use system ssh
        ssh_cmd = (
            f"ssh -i {ssh_key} -p {port} "
            f"-o StrictHostKeyChecking=no "
            f"-o ConnectTimeout=10 "
            f"{user}@{host} '{cmd}'"
        )
        result = subprocess.run(ssh_cmd, shell=True)
        return result.returncode

    else:
        # Password auth — use paramiko (no sshpass needed, works on Windows)
        try:
            import paramiko
        except ImportError:
            print("  [INFO] Installing paramiko...")
            subprocess.run([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
            import paramiko

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host, port=port,
                username=user, password=password,
                timeout=30, allow_agent=False, look_for_keys=False
            )
            _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            # Stream output live
            for line in stdout:
                print(line, end="")
            rc = stdout.channel.recv_exit_status()
            client.close()
            return rc

        except Exception as e:
            print(f"  ❌ Remote command failed on {host}: {e}")
            return 1


# ─────────────────────────────────────────────────────────
# FETCH STABLE VERSION
# ─────────────────────────────────────────────────────────
def get_stable_version():
    try:
        url = "https://dl.k8s.io/release/stable.txt"
        version = requests.get(url, timeout=5).text.strip()
        print(f"  [INFO] Latest stable Kubernetes: {version}")
        return version
    except Exception as e:
        raise Exception(f"Could not fetch stable version: {e}")


# ─────────────────────────────────────────────────────────
# IP DETECTION
# ─────────────────────────────────────────────────────────
def get_all_ips():
    """Get all non-loopback IPv4 addresses on this machine"""
    ips = []
    try:
        result = subprocess.run(
            "hostname -I", shell=True, capture_output=True, text=True
        )
        for ip in result.stdout.strip().split():
            if not ip.startswith("127.") and ":" not in ip:
                ips.append(ip)
    except Exception:
        pass
    return ips


def get_node_ip():
    """Get first non-loopback IPv4, fallback to socket method"""
    ips = get_all_ips()
    if ips:
        return ips[0]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def ask_node_ip():
    """
    Show all detected IPs and ask user to confirm the right one.
    Prevents 'node not ready' issue on multi-interface machines.
    This was the root cause of the node registration failure.
    """
    all_ips = get_all_ips()
    auto_ip = get_node_ip()

    print(f"\n  [INFO] Network interfaces on this server:")
    for i, ip in enumerate(all_ips, 1):
        marker = "  ← auto-selected" if ip == auto_ip else ""
        print(f"    {i}) {ip}{marker}")

    if len(all_ips) > 1:
        print(f"\n  ⚠  Multiple network interfaces found.")
        print(f"     Choose the IP that other servers and your laptop can reach.")
        print(f"     Using the wrong IP = node will not register (NotReady).\n")
        user_input = input(f"  Enter the correct IP [default: {auto_ip}]: ").strip()
        if user_input:
            return user_input
    else:
        print(f"\n  [INFO] Using IP: {auto_ip}")

    return auto_ip


# ─────────────────────────────────────────────────────────
# POD NETWORK CIDR SELECTION
# Auto-detects a safe CIDR that does not overlap with
# the server's own network. User can override if needed.
# ─────────────────────────────────────────────────────────
def ask_pod_cidr(node_ip):
    """
    Suggest a pod network CIDR that does not conflict
    with the server's own IP range, then let user confirm.

    Rule: Pod CIDR must NOT overlap with server network.
    Example: server on 192.168.x.x → use 10.244.0.0/16
    """

    # Detect server network range
    if node_ip.startswith("192.168."):
        suggested = "10.244.0.0/16"
        reason    = "server is on 192.168.x.x — using 10.244.0.0/16 to avoid conflict"
    elif node_ip.startswith("10."):
        suggested = "192.168.0.0/16"
        reason    = "server is on 10.x.x.x — using 192.168.0.0/16 to avoid conflict"
    elif node_ip.startswith("172."):
        suggested = "10.244.0.0/16"
        reason    = "server is on 172.x.x.x — using 10.244.0.0/16 to avoid conflict"
    else:
        suggested = "10.244.0.0/16"
        reason    = "default safe range"

    print(f"\n  [INFO] Pod Network CIDR Selection")
    print(f"  ─────────────────────────────────────────────")
    print(f"  Server IP     : {node_ip}")
    print(f"  Suggested CIDR: {suggested}  ({reason})")
    print(f"\n  This is the internal IP range for pods inside the cluster.")
    print(f"  It must NOT overlap with your server network.\n")
    print(f"  Options:")
    print(f"    1) {suggested}  ← recommended (auto-detected safe range)")
    print(f"    2) Enter custom CIDR manually")
    print()

    choice = input("  Choose [1/2] or press Enter for default: ").strip()

    if choice == "2":
        custom = input(f"  Enter pod network CIDR: ").strip()
        if custom:
            print(f"\n  ✔ Using custom CIDR: {custom}")
            return custom

    print(f"\n  ✔ Using CIDR: {suggested}")
    return suggested


# ─────────────────────────────────────────────────────────
# CLUSTER TYPE WIZARD
# ─────────────────────────────────────────────────────────
def ask_cluster_type():
    """
    Ask single-node or multi-node.
    For multi-node: collect worker IPs and auth details.
    """
    print("\n" + "="*55)
    print("  CLUSTER TYPE")
    print("="*55)
    print()
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

    if choice == "1":
        print("\n  ✔ Single-node cluster selected")
        return "single", []

    # Multi-node — collect worker details
    print("\n  ✔ Multi-node cluster selected")
    print("\n" + "="*55)
    print("  WORKER NODE DETAILS")
    print("="*55)
    print()
    print("  Control plane : THIS machine")
    print("  Workers       : other servers joined via SSH\n")
    print("  Each worker needs:")
    print("    ✔ Ubuntu 20.04 / 22.04 / 24.04")
    print("    ✔ SSH access from this machine")
    print("    ✔ Minimum 2 CPU, 2GB RAM\n")

    workers = []
    while True:
        print(f"  Worker node #{len(workers)+1}")
        w_host = input("    IP address (or Enter to finish): ").strip()
        if not w_host:
            break

        w_user_input = input(f"    SSH username [default: ubuntu]: ").strip()
        w_user = w_user_input if w_user_input else "ubuntu"

        print(f"    Auth: 1) SSH key   2) Password")
        w_auth = input("    Choose [1/2]: ").strip()

        if w_auth == "2":
            import getpass
            w_password = getpass.getpass(f"    Password for {w_user}@{w_host}: ")
            workers.append({
                "host": w_host, "user": w_user,
                "auth_method": "password",
                "password": w_password, "ssh_key": None
            })
        else:
            w_key_input = input(f"    SSH key [default: ~/.ssh/id_rsa]: ").strip()
            w_key = w_key_input if w_key_input else "~/.ssh/id_rsa"
            workers.append({
                "host": w_host, "user": w_user,
                "auth_method": "key",
                "ssh_key": w_key, "password": None
            })

        print(f"\n    ✔ Worker {w_host} added")
        another = input(f"\n  Add another worker? (yes/no): ").strip().lower()
        if another != "yes":
            break

    if not workers:
        print("\n  ⚠ No workers added — switching to single-node")
        return "single", []

    print(f"\n  ✔ {len(workers)} worker(s) configured:")
    for i, w in enumerate(workers, 1):
        print(f"    {i}. {w['user']}@{w['host']} ({w['auth_method']})")

    return "multi", workers


# ─────────────────────────────────────────────────────────
# CONTROL PLANE STEPS
# ─────────────────────────────────────────────────────────
def install_dependencies():
    print("\n[STEP 1] Installing system dependencies...\n")
    run("sudo apt-get update -qq", check=True)
    run(
        "sudo apt-get install -y "
        "apt-transport-https ca-certificates curl gpg "
        "socat conntrack ebtables ipset",
        check=True
    )


def install_containerd():
    print("\n[STEP 2] Installing containerd runtime...\n")
    if shutil.which("containerd"):
        print("  [INFO] containerd already installed — checking config")
    else:
        run("sudo apt-get install -y containerd", check=True)

    run("sudo mkdir -p /etc/containerd", check=True)
    run("containerd config default | sudo tee /etc/containerd/config.toml", check=True)
    run(
        "sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' "
        "/etc/containerd/config.toml", check=True
    )
    run("sudo systemctl enable containerd", check=True)
    run("sudo systemctl restart containerd", check=True)
    print("  ✔ containerd ready with SystemdCgroup=true")


def disable_swap():
    print("\n[STEP 3] Disabling swap...\n")
    run("sudo swapoff -a")
    run("sudo sed -i '/swap/d' /etc/fstab")
    print("  ✔ Swap disabled")


def configure_kernel():
    print("\n[STEP 4] Configuring kernel modules...\n")
    run("printf 'overlay\\nbr_netfilter\\n' | sudo tee /etc/modules-load.d/k8s.conf")
    run("sudo modprobe overlay")
    run("sudo modprobe br_netfilter")
    run(
        "printf 'net.bridge.bridge-nf-call-iptables=1\\n"
        "net.bridge.bridge-nf-call-ip6tables=1\\n"
        "net.ipv4.ip_forward=1\\n' | sudo tee /etc/sysctl.d/k8s.conf"
    )
    run("sudo sysctl --system -q")
    print("  ✔ Kernel configured")


def install_k8s_tools(version):
    print(f"\n[STEP 5] Installing kubeadm, kubelet, kubectl ({version})...\n")
    ver = version.lstrip("v")
    parts = ver.split(".")
    minor_ver = f"v{parts[0]}.{parts[1]}"

    run("sudo mkdir -p /etc/apt/keyrings", check=True)
    run(
        f"curl -fsSL https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/Release.key "
        f"| sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg "
        f"--batch --yes",
        check=True
    )
    repo_line = K8S_REPO_TEMPLATE.format(minor_ver=minor_ver)
    run(f"echo '{repo_line}' | sudo tee /etc/apt/sources.list.d/kubernetes.list", check=True)
    run("sudo apt-get update -qq", check=True)
    run(
        f"sudo apt-get install -y "
        f"kubeadm={ver}-* kubelet={ver}-* kubectl={ver}-* "
        f"|| sudo apt-get install -y kubeadm={ver} kubelet={ver} kubectl={ver}",
        check=True
    )
    run("sudo apt-mark hold kubeadm kubelet kubectl")
    run("sudo systemctl enable kubelet")
    print("  ✔ kubeadm, kubelet, kubectl installed and held")


def kubeadm_init(version, pod_cidr=None, node_ip=None):
    print(f"\n[STEP 6] Initializing Kubernetes control plane...\n")

    # Step 1: Ask user to confirm the correct node IP
    # Prevents 'node not ready' on multi-interface machines
    if node_ip is None:
        node_ip = ask_node_ip()

    # Step 2: Ask user to confirm a safe pod network CIDR
    # Auto-detects a range that does not conflict with server network
    if pod_cidr is None:
        pod_cidr = ask_pod_cidr(node_ip)

    print(f"\n  Node IP    : {node_ip}")
    print(f"  Pod CIDR   : {pod_cidr}")
    print(f"  K8s version: {version}\n")

    rc = run(
        f"sudo kubeadm init "
        f"--kubernetes-version={version} "
        f"--pod-network-cidr={pod_cidr} "
        f"--apiserver-advertise-address={node_ip} "
        f"--node-name=$(hostname) 2>&1 | tee /tmp/kubeadm_init.log"
    )

    if rc != 0:
        raise Exception(
            "kubeadm init failed.\n"
            "  Common causes:\n"
            "  - Swap not disabled      : sudo swapoff -a\n"
            "  - Port 6443 in use       : sudo ss -tlnp | grep 6443\n"
            "  - containerd not running : sudo systemctl status containerd\n"
            "  - Wrong IP selected      : re-run and pick correct interface\n"
            "  To reset and retry       : sudo kubeadm reset -f\n"
            "                             sudo rm -rf /etc/kubernetes /var/lib/etcd ~/.kube"
        )
    print("  ✔ Control plane initialized")


def configure_kubectl():
    print("\n[STEP 7] Configuring kubectl...\n")
    home = os.path.expanduser("~")
    kube_dir = os.path.join(home, ".kube")
    run(f"mkdir -p {kube_dir}")
    run(f"sudo cp /etc/kubernetes/admin.conf {kube_dir}/config", check=True)
    run(f"sudo chown $(id -u):$(id -g) {kube_dir}/config", check=True)
    print("  ✔ kubectl configured")


def install_calico():
    print("\n[STEP 8] Installing Calico CNI...\n")
    print("  [INFO] Waiting 15s for API server to be ready...")
    time.sleep(15)
    rc = run(f"kubectl apply -f {CALICO_MANIFEST}")
    if rc != 0:
        raise Exception(
            f"Calico install failed.\n"
            f"  Try manually: kubectl apply -f {CALICO_MANIFEST}"
        )
    print("  ✔ Calico CNI installed")


def install_etcdctl():
    """
    Install etcdctl — the CLI tool to backup/restore etcd.
    etcd POD runs inside Kubernetes but etcdctl binary
    must be installed separately on the control plane node.
    Without etcdctl, etcd backups before upgrades will be skipped.
    """
    print("\n[STEP] Installing etcdctl...\n")

    # Check if already installed
    import shutil
    if shutil.which("etcdctl"):
        print("  [INFO] etcdctl already installed — skipping")
        run("etcdctl version")
        return

    ETCD_VER = "v3.5.0"
    rc = run(
        f"curl -sLO https://github.com/etcd-io/etcd/releases/download/{ETCD_VER}/"
        f"etcd-{ETCD_VER}-linux-amd64.tar.gz && "
        f"tar -xf etcd-{ETCD_VER}-linux-amd64.tar.gz && "
        f"sudo mv etcd-{ETCD_VER}-linux-amd64/etcdctl /usr/local/bin/ && "
        f"sudo chmod +x /usr/local/bin/etcdctl && "
        f"rm -rf etcd-{ETCD_VER}-linux-amd64*"
    )
    if rc != 0:
        print("  \u26a0 etcdctl install failed — backups will be skipped during upgrades")
        print("    Install manually: https://github.com/etcd-io/etcd/releases")
        return

    run("etcdctl version")
    print("  ✔ etcdctl installed — etcd backups enabled")


def untaint_control_plane():
    print("\n[STEP 9] Removing control-plane taint (single-node)...\n")
    run(
        "kubectl taint nodes --all "
        "node-role.kubernetes.io/control-plane- "
        "2>/dev/null || true"
    )
    print("  ✔ Control-plane taint removed — pods can schedule here")


def wait_for_node_ready(timeout=300):
    print(f"\n[STEP] Waiting for node to become Ready (timeout: {timeout}s)...\n")
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            "kubectl get nodes --no-headers | grep -v NotReady | grep Ready",
            shell=True, capture_output=True
        )
        if result.returncode == 0:
            print("  ✔ Node is Ready!")
            run("kubectl get nodes -o wide")
            return True
        remaining = int(timeout - (time.time() - start))
        print(f"  Waiting... ({remaining}s remaining)")
        time.sleep(10)

    print("  ⚠ Node did not become Ready in time")
    print("    Check: kubectl describe node $(hostname)")
    print("    Check: kubectl get pods -n kube-system")
    return False


# ─────────────────────────────────────────────────────────
# GET JOIN COMMAND
# ─────────────────────────────────────────────────────────
def get_join_command():
    print("\n[INFO] Generating worker join token...\n")
    result = subprocess.run(
        "sudo kubeadm token create --print-join-command",
        shell=True, capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise Exception(
            "Failed to generate join command.\n"
            "Make sure kubeadm init completed successfully."
        )
    join_cmd = result.stdout.strip()
    print(f"  ✔ Join command generated")
    return join_cmd


# ─────────────────────────────────────────────────────────
# SETUP WORKER NODE
# Runs all prerequisites remotely then joins cluster
# ─────────────────────────────────────────────────────────
def setup_worker_node(worker, version, join_cmd):
    host     = worker["host"]
    user     = worker["user"]
    ssh_key  = worker.get("ssh_key")
    password = worker.get("password")
    port     = worker.get("port", 22)

    print(f"\n{'='*55}")
    print(f"  Setting up worker: {host}")
    print(f"{'='*55}\n")

    ver = version.lstrip("v")
    parts = ver.split(".")
    minor_ver = f"v{parts[0]}.{parts[1]}"
    repo_line = K8S_REPO_TEMPLATE.format(minor_ver=minor_ver)

    worker_script = f"""
set -e
echo '[1/6] Installing dependencies...'
sudo apt-get update -qq
sudo apt-get install -y apt-transport-https ca-certificates curl gpg socat conntrack ebtables ipset

echo '[2/6] Installing containerd...'
sudo apt-get install -y containerd
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml > /dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl enable containerd && sudo systemctl restart containerd

echo '[3/6] Disabling swap...'
sudo swapoff -a && sudo sed -i '/swap/d' /etc/fstab

echo '[4/6] Kernel modules...'
printf 'overlay\\nbr_netfilter\\n' | sudo tee /etc/modules-load.d/k8s.conf
sudo modprobe overlay && sudo modprobe br_netfilter
printf 'net.bridge.bridge-nf-call-iptables=1\\nnet.bridge.bridge-nf-call-ip6tables=1\\nnet.ipv4.ip_forward=1\\n' | sudo tee /etc/sysctl.d/k8s.conf
sudo sysctl --system -q

echo '[5/6] Installing Kubernetes tools...'
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg --batch --yes
echo '{repo_line}' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update -qq
sudo apt-get install -y kubeadm={ver}-* kubelet={ver}-* kubectl={ver}-* 2>/dev/null || sudo apt-get install -y kubeadm={ver} kubelet={ver} kubectl={ver}
sudo apt-mark hold kubeadm kubelet kubectl
sudo systemctl enable kubelet

echo '[6/6] Joining cluster...'
sudo {join_cmd}

echo 'WORKER_DONE'
"""

    rc = run_remote(host, user, worker_script,
                    ssh_key=ssh_key, password=password, port=port, timeout=600)

    if rc != 0:
        raise Exception(
            f"Worker setup failed on {host}.\n"
            f"  SSH in and check: ssh {user}@{host}\n"
            f"  sudo systemctl status kubelet\n"
            f"  sudo journalctl -u kubelet -n 30 --no-pager"
        )
    print(f"\n  ✔ Worker {host} joined successfully")


# ─────────────────────────────────────────────────────────
# VERIFY ALL NODES READY
# ─────────────────────────────────────────────────────────
def verify_cluster(expected_nodes):
    print(f"\n[INFO] Waiting for all {expected_nodes} node(s) to be Ready...\n")
    timeout = 300
    start   = time.time()

    while time.time() - start < timeout:
        result = subprocess.run(
            "kubectl get nodes --no-headers | grep ' Ready' | grep -v 'NotReady' | wc -l",
            shell=True, capture_output=True, text=True
        )
        try:
            ready_count = int(result.stdout.strip())
        except Exception:
            ready_count = 0

        if ready_count >= expected_nodes:
            print(f"  ✔ All {expected_nodes} node(s) are Ready!")
            run("kubectl get nodes -o wide")
            return True

        remaining = int(timeout - (time.time() - start))
        print(f"  Ready: {ready_count}/{expected_nodes} ({remaining}s remaining)")
        time.sleep(15)

    print(f"  ⚠ Not all nodes became Ready in time")
    run("kubectl get nodes -o wide")
    return False


# ─────────────────────────────────────────────────────────
# MAIN INSTALL
# ─────────────────────────────────────────────────────────
def install_fresh_cluster(target_version=None):

    print("\n======================================")
    print(" KUBERNETES CLUSTER INSTALLER")
    print("======================================\n")

    if target_version is None:
        target_version = get_stable_version()

    # Step 1: Ask single or multi-node
    cluster_type, workers = ask_cluster_type()

    # Step 2: Show summary
    print(f"\n  Installation Summary:")
    print(f"  ─────────────────────────────────────")
    print(f"  K8s Version  : {target_version}")
    print(f"  Cluster Type : {'Single-node' if cluster_type == 'single' else f'Multi-node (1 control + {len(workers)} workers)'}")
    print(f"  CNI          : Calico v3.28.0")
    print(f"  Runtime      : containerd")
    if workers:
        print(f"  Workers:")
        for i, w in enumerate(workers, 1):
            print(f"    {i}. {w['user']}@{w['host']}")
    print()

    confirm = input("Proceed with installation? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("\nInstallation aborted.\n")
        return False

    try:
        # ── Control plane ─────────────────────────────────
        install_dependencies()          # Step 1
        install_containerd()            # Step 2
        disable_swap()                  # Step 3
        configure_kernel()              # Step 4
        install_k8s_tools(target_version)  # Step 5
        kubeadm_init(target_version)    # Step 6 — asks user to confirm IP
        configure_kubectl()             # Step 7
        install_calico()                # Step 8
        install_etcdctl()               # Step 9 — needed for etcd backups during upgrades

        if cluster_type == "single":
            untaint_control_plane()     # Step 10 — single node only
            wait_for_node_ready()       # Step 11

        else:
            # Multi-node
            print("\n[INFO] Waiting for control plane before joining workers...\n")
            wait_for_node_ready(timeout=180)

            join_cmd = get_join_command()

            failed_workers = []
            for i, worker in enumerate(workers, 1):
                print(f"\n[INFO] Setting up worker {i}/{len(workers)}: {worker['host']}")
                try:
                    setup_worker_node(worker, target_version, join_cmd)
                except Exception as e:
                    print(f"\n  ⚠ Worker {worker['host']} failed: {e}")
                    failed_workers.append(worker["host"])

            expected = 1 + len(workers) - len(failed_workers)
            verify_cluster(expected)

            if failed_workers:
                print(f"\n  ⚠ Failed workers — join manually:")
                for w in failed_workers:
                    print(f"    ssh {w}")
                    print(f"    sudo {join_cmd}")

        # ── Success ───────────────────────────────────────
        print("\n======================================")
        print(" INSTALLATION COMPLETE ✔")
        print("======================================\n")
        print(f"  Kubernetes {target_version} is running!")
        print(f"  Type : {'Single-node' if cluster_type == 'single' else 'Multi-node'}")
        print(f"\n  Verify:")
        print(f"    kubectl get nodes -o wide")
        print(f"    kubectl get pods -A\n")
        return True

    except Exception as e:
        print(f"\n❌ INSTALLATION FAILED: {e}")
        print("\n  To reset and retry:")
        print("    sudo kubeadm reset -f")
        print("    sudo rm -rf /etc/kubernetes /var/lib/etcd ~/.kube")
        print("    python3 k8s-install-upgrade.py")
        return False
