import subprocess
import socket
import os
import shutil
import time
import requests


# ─────────────────────────────────────────────────────────
# KUBERNETES CLUSTER INSTALLER
# Supports:
#   - Single-node  (control plane only, untainted)
#   - Multi-node   (control plane + N worker nodes via SSH join)
#
# Uses kubeadm + containerd + Calico CNI
# ─────────────────────────────────────────────────────────

K8S_REPO_TEMPLATE = (
    "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] "
    "https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/ /"
)
CALICO_MANIFEST = "https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml"


def run(cmd, check=False):
    print(f"\n[EXEC] {cmd}\n")
    result = subprocess.run(cmd, shell=True)
    if check and result.returncode != 0:
        raise Exception(f"Command failed: {cmd}")
    return result.returncode


def run_remote(host, user, cmd, ssh_key=None, password=None, port=22):
    """Run a command on a remote worker node via SSH"""
    if ssh_key:
        ssh_cmd = (
            f"ssh -i {ssh_key} -p {port} "
            f"-o StrictHostKeyChecking=no "
            f"-o ConnectTimeout=10 "
            f"{user}@{host} \"{cmd}\""
        )
    else:
        ssh_cmd = (
            f"sshpass -p '{password}' ssh -p {port} "
            f"-o StrictHostKeyChecking=no "
            f"-o ConnectTimeout=10 "
            f"{user}@{host} \"{cmd}\""
        )
    print(f"\n[REMOTE {host}] {cmd}\n")
    return subprocess.run(ssh_cmd, shell=True).returncode


def get_stable_version():
    try:
        url = "https://dl.k8s.io/release/stable.txt"
        version = requests.get(url, timeout=5).text.strip()
        print(f"  [INFO] Latest stable Kubernetes: {version}")
        return version
    except Exception as e:
        raise Exception(f"Could not fetch stable version: {e}")


def get_all_ips():
    """Get all non-loopback IPv4 addresses on this machine"""
    ips = []
    try:
        result = subprocess.run(
            "hostname -I", shell=True, capture_output=True, text=True
        )
        for ip in result.stdout.strip().split():
            if not ip.startswith("127.") and ":" not in ip:  # skip loopback and IPv6
                ips.append(ip)
    except Exception:
        pass
    return ips


def get_node_ip():
    """
    Get the best IP for this node.
    Returns the first non-loopback IPv4 address.
    Falls back to socket method if hostname -I fails.
    """
    ips = get_all_ips()
    if ips:
        return ips[0]
    # Fallback
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
    Ask user to confirm or change the detected node IP.
    This prevents kubeadm from using the wrong interface
    on machines with multiple network adapters.
    """
    all_ips   = get_all_ips()
    auto_ip   = get_node_ip()

    print(f"\n  [INFO] Network interfaces detected on this server:")
    for i, ip in enumerate(all_ips, 1):
        marker = " ← auto-selected" if ip == auto_ip else ""
        print(f"    {i}) {ip}{marker}")

    if len(all_ips) > 1:
        print(f"\n  ⚠  Multiple network interfaces found.")
        print(f"     The wrong IP can cause the node to not register.")
        print(f"     Select the IP that other nodes/your laptop can reach.\n")
        print(f"  Enter the correct IP [default: {auto_ip}]: ", end="")
        user_input = input().strip()
        if user_input:
            return user_input
    else:
        print(f"\n  [INFO] Using IP: {auto_ip}")

    return auto_ip


# ─────────────────────────────────────────────────────────
# INTERACTIVE CLUSTER TYPE WIZARD
# Asks user: single-node or multi-node?
# For multi-node: collects worker IPs
# ─────────────────────────────────────────────────────────
def ask_cluster_type():
    """
    Interactively ask what kind of cluster to install.
    Returns:
        cluster_type : "single" or "multi"
        workers      : list of {"host":ip, "user":user, "ssh_key":key}
    """
    print("\n" + "="*55)
    print("  CLUSTER TYPE SELECTION")
    print("="*55)
    print()
    print("  What type of Kubernetes cluster do you want to install?\n")
    print("  1) Single-node   — 1 server acts as both control plane and worker")
    print("                     Good for: testing, development, learning")
    print()
    print("  2) Multi-node    — 1 control plane + multiple worker nodes")
    print("                     Good for: production, high availability")
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
    print("  WORKER NODE SETUP")
    print("="*55)
    print()
    print("  The control plane will be installed on THIS machine.")
    print("  Worker nodes will be joined via SSH.\n")
    print("  Requirements for each worker node:")
    print("    ✔ Ubuntu 20.04 / 22.04 / 24.04")
    print("    ✔ SSH access from this machine")
    print("    ✔ Minimum 2 CPU, 2GB RAM")
    print("    ✔ Swap disabled (tool will do this automatically)\n")

    workers = []
    while True:
        print(f"  Worker node #{len(workers)+1}")
        w_host = input("    IP address (or press Enter to finish): ").strip()
        if not w_host:
            break

        w_user_input = input(f"    SSH username [default: ubuntu]: ").strip()
        w_user = w_user_input if w_user_input else "ubuntu"

        print(f"    Authentication:")
        print(f"      1) SSH key")
        print(f"      2) Password")
        w_auth = input("    Choose [1/2]: ").strip()

        if w_auth == "2":
            import getpass
            w_password = getpass.getpass(f"    Password for {w_user}@{w_host}: ")
            workers.append({
                "host": w_host,
                "user": w_user,
                "auth_method": "password",
                "password": w_password,
                "ssh_key": None
            })
        else:
            w_key_input = input(f"    SSH key path [default: ~/.ssh/id_rsa]: ").strip()
            w_key = w_key_input if w_key_input else "~/.ssh/id_rsa"
            workers.append({
                "host": w_host,
                "user": w_user,
                "auth_method": "key",
                "ssh_key": w_key,
                "password": None
            })

        print(f"\n    ✔ Worker {w_host} added")

        another = input(f"\n  Add another worker node? (yes/no): ").strip().lower()
        if another != "yes":
            break

    if not workers:
        print("\n  ⚠ No workers added — installing as single-node instead")
        return "single", []

    print(f"\n  ✔ {len(workers)} worker node(s) configured:")
    for i, w in enumerate(workers, 1):
        print(f"    Worker {i}: {w['user']}@{w['host']} (auth: {w['auth_method']})")

    return "multi", workers


# ─────────────────────────────────────────────────────────
# CONTROL PLANE SETUP STEPS
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
        print("  [INFO] containerd already installed, skipping")
        return
    run("sudo apt-get install -y containerd", check=True)
    run("sudo mkdir -p /etc/containerd", check=True)
    run("containerd config default | sudo tee /etc/containerd/config.toml", check=True)
    run(
        "sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' "
        "/etc/containerd/config.toml", check=True
    )
    run("sudo systemctl enable containerd", check=True)
    run("sudo systemctl restart containerd", check=True)
    print("  ✔ containerd installed and started")


def disable_swap():
    print("\n[STEP 3] Disabling swap...\n")
    run("sudo swapoff -a")
    run("sudo sed -i '/swap/d' /etc/fstab")
    print("  ✔ Swap disabled")


def configure_kernel():
    print("\n[STEP 4] Configuring kernel modules...\n")
    run("cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf\noverlay\nbr_netfilter\nEOF")
    run("sudo modprobe overlay")
    run("sudo modprobe br_netfilter")
    run(
        "cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf\n"
        "net.bridge.bridge-nf-call-iptables  = 1\n"
        "net.bridge.bridge-nf-call-ip6tables = 1\n"
        "net.ipv4.ip_forward                 = 1\n"
        "EOF"
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
        f"| sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg --batch --yes",
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
    print("  ✔ kubeadm, kubelet, kubectl installed")


def kubeadm_init(version, pod_cidr="192.168.0.0/16", node_ip=None):
    print(f"\n[STEP 6] Initializing Kubernetes control plane...\n")

    # Ask user to confirm the correct IP if not already provided
    # This prevents the "node not ready" issue on multi-interface machines
    if node_ip is None:
        node_ip = ask_node_ip()

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
            "kubeadm init failed. Common causes:\n"
            "  - swap not disabled      : sudo swapoff -a\n"
            "  - port 6443 in use       : sudo ss -tlnp | grep 6443\n"
            "  - containerd not running : sudo systemctl status containerd\n"
            "  - wrong IP selected      : check network interfaces\n"
            "  - reset and retry        : sudo kubeadm reset -f"
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
    time.sleep(15)
    rc = run(f"kubectl apply -f {CALICO_MANIFEST}")
    if rc != 0:
        raise Exception(f"Calico install failed. Try: kubectl apply -f {CALICO_MANIFEST}")
    print("  ✔ Calico CNI installed")


def untaint_control_plane():
    print("\n[STEP 9] Removing control-plane taint (single-node)...\n")
    run(
        "kubectl taint nodes --all "
        "node-role.kubernetes.io/control-plane- "
        "2>/dev/null || true"
    )
    print("  ✔ Taint removed — workloads can run on control plane")


def wait_for_node_ready(timeout=180):
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
    return False


# ─────────────────────────────────────────────────────────
# GET JOIN COMMAND FROM CONTROL PLANE
# ─────────────────────────────────────────────────────────
def get_join_command():
    """Extract kubeadm join command from the control plane"""
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
# Runs all prerequisites on each worker then joins cluster
# ─────────────────────────────────────────────────────────
def setup_worker_node(worker, version, join_cmd):
    """
    Prepares a worker node and joins it to the cluster.
    Runs all steps remotely via SSH.
    """
    host     = worker["host"]
    user     = worker["user"]
    ssh_key  = worker.get("ssh_key")
    password = worker.get("password")
    port     = worker.get("port", 22)

    print(f"\n{'='*55}")
    print(f"  Setting up worker node: {host}")
    print(f"{'='*55}\n")

    ver = version.lstrip("v")
    parts = ver.split(".")
    minor_ver = f"v{parts[0]}.{parts[1]}"

    repo_line = K8S_REPO_TEMPLATE.format(minor_ver=minor_ver)

    # All steps as a single remote script
    worker_script = f"""
        set -e

        echo '[WORKER] Step 1: Installing dependencies...'
        sudo apt-get update -qq
        sudo apt-get install -y apt-transport-https ca-certificates curl gpg socat conntrack ebtables ipset

        echo '[WORKER] Step 2: Installing containerd...'
        sudo apt-get install -y containerd
        sudo mkdir -p /etc/containerd
        containerd config default | sudo tee /etc/containerd/config.toml > /dev/null
        sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
        sudo systemctl enable containerd
        sudo systemctl restart containerd

        echo '[WORKER] Step 3: Disabling swap...'
        sudo swapoff -a
        sudo sed -i '/swap/d' /etc/fstab

        echo '[WORKER] Step 4: Kernel modules...'
        echo 'overlay' | sudo tee /etc/modules-load.d/k8s.conf
        echo 'br_netfilter' | sudo tee -a /etc/modules-load.d/k8s.conf
        sudo modprobe overlay
        sudo modprobe br_netfilter
        echo 'net.bridge.bridge-nf-call-iptables=1' | sudo tee /etc/sysctl.d/k8s.conf
        echo 'net.bridge.bridge-nf-call-ip6tables=1' | sudo tee -a /etc/sysctl.d/k8s.conf
        echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.d/k8s.conf
        sudo sysctl --system -q

        echo '[WORKER] Step 5: Installing kubernetes tools...'
        sudo mkdir -p /etc/apt/keyrings
        curl -fsSL https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg --batch --yes
        echo '{repo_line}' | sudo tee /etc/apt/sources.list.d/kubernetes.list
        sudo apt-get update -qq
        sudo apt-get install -y kubeadm={ver}-* kubelet={ver}-* kubectl={ver}-* 2>/dev/null || sudo apt-get install -y kubeadm={ver} kubelet={ver} kubectl={ver}
        sudo apt-mark hold kubeadm kubelet kubectl
        sudo systemctl enable kubelet

        echo '[WORKER] Step 6: Joining cluster...'
        sudo {join_cmd}

        echo '[WORKER] DONE'
    """

    rc = run_remote(host, user, worker_script, ssh_key=ssh_key, password=password, port=port)

    if rc != 0:
        raise Exception(
            f"Worker setup failed on {host}.\n"
            f"SSH into the worker and check:\n"
            f"  sudo systemctl status kubelet\n"
            f"  sudo journalctl -u kubelet -n 30 --no-pager"
        )

    print(f"\n  ✔ Worker {host} joined the cluster successfully")


# ─────────────────────────────────────────────────────────
# VERIFY CLUSTER
# ─────────────────────────────────────────────────────────
def verify_cluster(expected_nodes):
    """Wait for all nodes to be Ready"""
    print(f"\n[INFO] Waiting for all {expected_nodes} node(s) to be Ready...\n")

    timeout = 300
    start = time.time()

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
        print(f"  Ready: {ready_count}/{expected_nodes} nodes ({remaining}s remaining)")
        time.sleep(15)

    print(f"  ⚠ Not all nodes became Ready in time")
    run("kubectl get nodes -o wide")
    return False


# ─────────────────────────────────────────────────────────
# MAIN INSTALL FUNCTION
# ─────────────────────────────────────────────────────────
def install_fresh_cluster(target_version=None):

    print("\n======================================")
    print(" KUBERNETES CLUSTER INSTALLER")
    print("======================================\n")

    if target_version is None:
        target_version = get_stable_version()

    # Ask single or multi-node
    cluster_type, workers = ask_cluster_type()

    print(f"\n  Summary:")
    print(f"    K8s Version  : {target_version}")
    print(f"    Cluster Type : {'Single-node' if cluster_type == 'single' else f'Multi-node (1 control + {len(workers)} workers)'}")
    print(f"    CNI          : Calico v3.28.0")
    print(f"    Runtime      : containerd")
    print(f"    Control Plane: {get_node_ip()} (this machine)\n")

    if workers:
        print(f"    Workers:")
        for i, w in enumerate(workers, 1):
            print(f"      {i}. {w['user']}@{w['host']}")
    print()

    confirm = input("Proceed with installation? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("\nInstallation aborted.\n")
        return False

    try:
        # ── Control plane setup ──────────────────────────
        install_dependencies()
        install_containerd()
        disable_swap()
        configure_kernel()
        install_k8s_tools(target_version)
        kubeadm_init(target_version)
        configure_kubectl()
        install_calico()

        if cluster_type == "single":
            # Remove taint so workloads can run on control plane
            untaint_control_plane()
            wait_for_node_ready()

        else:
            # Multi-node: wait for control plane then join workers
            print("\n[INFO] Waiting for control plane to be Ready before joining workers...\n")
            wait_for_node_ready(timeout=180)

            # Get join command ONCE and reuse for all workers
            join_cmd = get_join_command()

            # Setup each worker
            failed_workers = []
            for i, worker in enumerate(workers, 1):
                print(f"\n[INFO] Setting up worker {i}/{len(workers)}: {worker['host']}")
                try:
                    setup_worker_node(worker, target_version, join_cmd)
                except Exception as e:
                    print(f"\n  ⚠ Worker {worker['host']} failed: {e}")
                    print(f"  Continuing with remaining workers...")
                    failed_workers.append(worker["host"])

            # Verify all nodes
            expected = 1 + (len(workers) - len(failed_workers))
            verify_cluster(expected)

            if failed_workers:
                print(f"\n  ⚠ These workers failed to join:")
                for w in failed_workers:
                    print(f"    - {w}")
                print(f"\n  To retry a failed worker, SSH into it and run:")
                print(f"    sudo {join_cmd}")

        # Success
        print("\n======================================")
        print(f" CLUSTER INSTALLATION COMPLETE ✔")
        print("======================================\n")
        print(f"  Kubernetes {target_version} is running!")
        if cluster_type == "single":
            print(f"  Type: Single-node")
        else:
            print(f"  Type: Multi-node ({1 + len(workers) - len(failed_workers if 'failed_workers' in dir() else [])} nodes)")
        print(f"\n  Run: kubectl get nodes")
        print(f"  Run: kubectl get pods -A\n")
        return True

    except Exception as e:
        print(f"\n❌ INSTALLATION FAILED: {e}")
        print("\nTo reset and retry:")
        print("  sudo kubeadm reset -f")
        print("  sudo rm -rf /etc/kubernetes /var/lib/etcd ~/.kube")
        print("  python3 run.py")
        return False
