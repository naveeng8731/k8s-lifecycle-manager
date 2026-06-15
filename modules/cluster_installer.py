import subprocess
import socket
import os
import shutil
import time
import requests


# -------------------------
# FRESH KUBERNETES CLUSTER INSTALLER
# Uses kubeadm to bootstrap a single-node or multi-node cluster
# CNI: Calico (default)
# CRI: containerd (default)
# -------------------------

K8S_REPO_TEMPLATE = (
    "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] "
    "https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/ /"
)

CALICO_MANIFEST = "https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml"


# -------------------------
# RUN COMMAND
# -------------------------
def run(cmd, check=False):
    print(f"\n[EXEC] {cmd}\n")
    result = subprocess.run(cmd, shell=True)
    if check and result.returncode != 0:
        raise Exception(f"Command failed: {cmd}")
    return result.returncode


# -------------------------
# GET STABLE VERSION TO INSTALL
# -------------------------
def get_stable_version():
    try:
        url = "https://dl.k8s.io/release/stable.txt"
        version = requests.get(url, timeout=5).text.strip()
        print(f"  [INFO] Latest stable Kubernetes: {version}")
        return version
    except Exception as e:
        raise Exception(f"Could not fetch stable version: {e}")


# -------------------------
# GET NODE IP
# -------------------------
def get_node_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# -------------------------
# STEP 1: INSTALL DEPENDENCIES
# -------------------------
def install_dependencies():

    print("\n[STEP 1] Installing system dependencies...\n")

    run("sudo apt-get update -qq", check=True)

    run(
        "sudo apt-get install -y "
        "apt-transport-https ca-certificates curl gpg "
        "socat conntrack ebtables ipset",
        check=True
    )


# -------------------------
# STEP 2: INSTALL CONTAINER RUNTIME (containerd)
# -------------------------
def install_containerd():

    print("\n[STEP 2] Installing containerd runtime...\n")

    if shutil.which("containerd"):
        print("  [INFO] containerd already installed, skipping")
        return

    run(
        "sudo apt-get install -y containerd",
        check=True
    )

    # Default containerd config
    run("sudo mkdir -p /etc/containerd", check=True)
    run(
        "containerd config default | sudo tee /etc/containerd/config.toml",
        check=True
    )

    # Enable SystemdCgroup (required for kubeadm)
    run(
        "sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' "
        "/etc/containerd/config.toml",
        check=True
    )

    run("sudo systemctl enable containerd", check=True)
    run("sudo systemctl restart containerd", check=True)
    print("  ✔ containerd installed and started")


# -------------------------
# STEP 3: DISABLE SWAP
# -------------------------
def disable_swap():

    print("\n[STEP 3] Disabling swap...\n")

    run("sudo swapoff -a")
    # Persist across reboots
    run("sudo sed -i '/swap/d' /etc/fstab")
    print("  ✔ Swap disabled")


# -------------------------
# STEP 4: CONFIGURE KERNEL MODULES
# -------------------------
def configure_kernel():

    print("\n[STEP 4] Configuring kernel modules and sysctl...\n")

    run(
        "cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf\n"
        "overlay\n"
        "br_netfilter\n"
        "EOF"
    )

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


# -------------------------
# STEP 5: INSTALL KUBERNETES TOOLS
# -------------------------
def install_k8s_tools(version):

    print(f"\n[STEP 5] Installing kubeadm, kubelet, kubectl ({version})...\n")

    ver = version.lstrip("v")
    parts = ver.split(".")
    minor_ver = f"v{parts[0]}.{parts[1]}"

    # Add k8s apt keyring
    run("sudo mkdir -p /etc/apt/keyrings", check=True)
    run(
        f"curl -fsSL https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/Release.key "
        f"| sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg --batch --yes",
        check=True
    )

    # Add repo
    repo_line = K8S_REPO_TEMPLATE.format(minor_ver=minor_ver)
    run(
        f"echo '{repo_line}' | sudo tee /etc/apt/sources.list.d/kubernetes.list",
        check=True
    )

    run("sudo apt-get update -qq", check=True)

    run(
        f"sudo apt-get install -y "
        f"kubeadm={ver}-* kubelet={ver}-* kubectl={ver}-* "
        f"|| sudo apt-get install -y kubeadm={ver} kubelet={ver} kubectl={ver}",
        check=True
    )

    # Hold versions to prevent accidental upgrade
    run("sudo apt-mark hold kubeadm kubelet kubectl")

    run("sudo systemctl enable kubelet")
    print("  ✔ kubeadm, kubelet, kubectl installed")


# -------------------------
# STEP 6: KUBEADM INIT
# -------------------------
def kubeadm_init(version, pod_cidr="192.168.0.0/16"):

    print(f"\n[STEP 6] Initializing Kubernetes cluster (kubeadm init)...\n")

    node_ip = get_node_ip()
    print(f"  [INFO] Node IP detected: {node_ip}")
    print(f"  [INFO] Pod CIDR        : {pod_cidr}")
    print(f"  [INFO] K8s version     : {version}\n")

    rc = run(
        f"sudo kubeadm init "
        f"--kubernetes-version={version} "
        f"--pod-network-cidr={pod_cidr} "
        f"--apiserver-advertise-address={node_ip} "
        f"--node-name=$(hostname)"
    )

    if rc != 0:
        raise Exception(
            "kubeadm init failed. Common causes:\n"
            "  - swap not disabled (sudo swapoff -a)\n"
            "  - containerd not running (sudo systemctl status containerd)\n"
            "  - ports already in use (sudo ss -tlnp | grep 6443)\n"
            "  - run: sudo kubeadm reset -f  then try again"
        )

    print("  ✔ Control plane initialized")


# -------------------------
# STEP 7: CONFIGURE KUBECTL ACCESS
# -------------------------
def configure_kubectl():

    print("\n[STEP 7] Configuring kubectl access for current user...\n")

    home = os.path.expanduser("~")
    kube_dir = os.path.join(home, ".kube")

    run(f"mkdir -p {kube_dir}")
    run(f"sudo cp /etc/kubernetes/admin.conf {kube_dir}/config", check=True)
    run(f"sudo chown $(id -u):$(id -g) {kube_dir}/config", check=True)

    print("  ✔ kubectl configured")


# -------------------------
# STEP 8: INSTALL CNI (Calico)
# -------------------------
def install_calico():

    print("\n[STEP 8] Installing Calico CNI...\n")

    # Wait for API server to be ready
    print("  [INFO] Waiting for API server to be ready...")
    time.sleep(15)

    rc = run(f"kubectl apply -f {CALICO_MANIFEST}")

    if rc != 0:
        raise Exception(
            f"Calico install failed. Try manually:\n"
            f"  kubectl apply -f {CALICO_MANIFEST}"
        )

    print("  ✔ Calico CNI installed")


# -------------------------
# STEP 9: UNTAINT CONTROL PLANE
# (Allow workloads on single-node cluster)
# -------------------------
def untaint_control_plane():

    print("\n[STEP 9] Removing control-plane taint (single-node setup)...\n")

    run(
        "kubectl taint nodes --all "
        "node-role.kubernetes.io/control-plane- "
        "2>/dev/null || true"
    )

    print("  ✔ Control-plane taint removed")


# -------------------------
# STEP 10: WAIT FOR NODE READY
# -------------------------
def wait_for_node_ready(timeout=180):

    print(f"\n[STEP 10] Waiting for node to become Ready (timeout: {timeout}s)...\n")

    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            "kubectl get nodes --no-headers | grep -v NotReady | grep Ready",
            shell=True,
            capture_output=True
        )
        if result.returncode == 0:
            print("  ✔ Node is Ready!")
            run("kubectl get nodes -o wide")
            return True

        remaining = int(timeout - (time.time() - start))
        print(f"  [INFO] Node not ready yet... waiting ({remaining}s remaining)")
        time.sleep(10)

    print("  ⚠ Node did not become Ready within timeout")
    print("    Check: kubectl describe node $(hostname)")
    print("    Check: kubectl get pods -n kube-system")
    return False


# -------------------------
# MAIN INSTALL FUNCTION
# Called from run.py when cluster is not present
# -------------------------
def install_fresh_cluster(target_version=None):

    print("\n======================================")
    print(" FRESH KUBERNETES CLUSTER INSTALLER")
    print("======================================\n")

    if target_version is None:
        target_version = get_stable_version()

    print(f"  Installing Kubernetes {target_version}")
    print(f"  CNI       : Calico v3.28.0")
    print(f"  Runtime   : containerd")
    print(f"  Node IP   : {get_node_ip()}\n")

    confirm = input("Proceed with fresh cluster installation? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("\nInstallation aborted by user.")
        return False

    try:
        install_dependencies()         # Step 1
        install_containerd()           # Step 2
        disable_swap()                 # Step 3
        configure_kernel()             # Step 4
        install_k8s_tools(target_version)  # Step 5
        kubeadm_init(target_version)   # Step 6
        configure_kubectl()            # Step 7
        install_calico()               # Step 8
        untaint_control_plane()        # Step 9
        wait_for_node_ready()          # Step 10

        print("\n======================================")
        print(" CLUSTER INSTALLATION COMPLETE ✔")
        print("======================================\n")
        print(f"  Kubernetes {target_version} is now running!")
        print(f"  Run: kubectl get nodes")
        print(f"  Run: kubectl get pods -A\n")
        return True

    except Exception as e:
        print(f"\n❌ INSTALLATION FAILED: {str(e)}")
        print("\nTo reset and try again:")
        print("  sudo kubeadm reset -f")
        print("  sudo rm -rf /etc/kubernetes /var/lib/etcd ~/.kube")
        print("  python3 run.py")
        return False
