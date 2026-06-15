import subprocess
import shutil
import socket
import json


# -------------------------
# CLUSTER STATE CONSTANTS
# -------------------------
STATE_HEALTHY       = "HEALTHY"        # cluster running, nodes ready
STATE_DEGRADED      = "DEGRADED"       # cluster running but nodes not ready
STATE_NOT_INSTALLED = "NOT_INSTALLED"  # kubectl missing or kubeadm not installed
STATE_INSTALLED_NO_CLUSTER = "INSTALLED_NO_CLUSTER"  # tools exist but no cluster init yet
STATE_UNREACHABLE   = "UNREACHABLE"    # tools exist, cluster init done but API unreachable


# -------------------------
# DETECT CLUSTER STATE
# Returns one of the STATE_* constants above
# -------------------------
def detect_cluster_state():

    # Step 1: Check if kubectl is installed
    if shutil.which("kubectl") is None:
        print("  [DETECT] kubectl not found → NOT_INSTALLED")
        return STATE_NOT_INSTALLED

    # Step 2: Check if kubeadm is installed
    if shutil.which("kubeadm") is None:
        print("  [DETECT] kubeadm not found → NOT_INSTALLED")
        return STATE_NOT_INSTALLED

    # Step 3: Try connecting to the cluster API
    try:
        result = subprocess.run(
            "kubectl cluster-info --request-timeout=5s",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            # Step 4: Check if any nodes exist and are ready
            nodes_result = subprocess.run(
                "kubectl get nodes -o json --request-timeout=5s",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )

            if nodes_result.returncode == 0:
                nodes_data = json.loads(nodes_result.stdout)
                items = nodes_data.get("items", [])

                if len(items) == 0:
                    print("  [DETECT] API reachable but no nodes found → INSTALLED_NO_CLUSTER")
                    return STATE_INSTALLED_NO_CLUSTER

                # Check if all nodes are Ready
                all_ready = True
                for node in items:
                    for condition in node["status"]["conditions"]:
                        if condition["type"] == "Ready":
                            if condition["status"] != "True":
                                all_ready = False

                if all_ready:
                    print("  [DETECT] Cluster running, all nodes ready → HEALTHY")
                    return STATE_HEALTHY
                else:
                    print("  [DETECT] Cluster running but nodes not ready → DEGRADED")
                    return STATE_DEGRADED

    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

    # Step 5: kubectl exists but API not reachable
    # Check if /etc/kubernetes/admin.conf exists (kubeadm init was run before)
    try:
        result = subprocess.run(
            "test -f /etc/kubernetes/admin.conf",
            shell=True
        )
        if result.returncode == 0:
            print("  [DETECT] kubeadm init was run but API is unreachable → UNREACHABLE")
            return STATE_UNREACHABLE
    except Exception:
        pass

    print("  [DETECT] Tools installed but no cluster exists → INSTALLED_NO_CLUSTER")
    return STATE_INSTALLED_NO_CLUSTER


# -------------------------
# GET NODE COUNT
# -------------------------
def get_node_count():
    try:
        result = subprocess.run(
            "kubectl get nodes --no-headers --request-timeout=5s | wc -l",
            shell=True,
            capture_output=True,
            text=True
        )
        return int(result.stdout.strip())
    except Exception:
        return 0


# -------------------------
# GET INSTALLED TOOL VERSIONS
# -------------------------
def get_tool_versions():

    versions = {}

    # kubectl
    try:
        r = subprocess.run(
            "kubectl version --client --output=json",
            shell=True, capture_output=True, text=True
        )
        data = json.loads(r.stdout)
        versions["kubectl"] = data.get("clientVersion", {}).get("gitVersion", "unknown")
    except Exception:
        versions["kubectl"] = "not installed" if shutil.which("kubectl") is None else "unknown"

    # kubeadm
    try:
        r = subprocess.run(
            "kubeadm version -o json",
            shell=True, capture_output=True, text=True
        )
        data = json.loads(r.stdout)
        versions["kubeadm"] = data.get("clientVersion", {}).get("gitVersion", "unknown")
    except Exception:
        versions["kubeadm"] = "not installed" if shutil.which("kubeadm") is None else "unknown"

    # kubelet
    try:
        r = subprocess.run(
            "kubelet --version",
            shell=True, capture_output=True, text=True
        )
        versions["kubelet"] = r.stdout.strip().replace("Kubernetes ", "")
    except Exception:
        versions["kubelet"] = "not installed" if shutil.which("kubelet") is None else "unknown"

    return versions


# -------------------------
# PRINT CLUSTER STATE REPORT
# -------------------------
def print_cluster_state(state, tool_versions):

    print("\n======================================")
    print(" Cluster Detection Report")
    print("======================================\n")

    print(f"  kubectl  : {tool_versions.get('kubectl', 'not found')}")
    print(f"  kubeadm  : {tool_versions.get('kubeadm', 'not found')}")
    print(f"  kubelet  : {tool_versions.get('kubelet', 'not found')}")
    print(f"\n  Cluster State : {state}\n")

    if state == STATE_HEALTHY:
        print("  ✔ Cluster is running and healthy")

    elif state == STATE_DEGRADED:
        print("  ⚠ Cluster is running but one or more nodes are NOT READY")
        print("    Check: kubectl get nodes")
        print("    Check: kubectl describe node <name>")

    elif state == STATE_NOT_INSTALLED:
        print("  ❌ Kubernetes tools not installed")
        print("    → Fresh install will be performed")

    elif state == STATE_INSTALLED_NO_CLUSTER:
        print("  ❌ Tools installed but no cluster initialized")
        print("    → Fresh cluster installation will be performed")

    elif state == STATE_UNREACHABLE:
        print("  ❌ Cluster was initialized but API server is unreachable")
        print("    Check: sudo systemctl status kubelet")
        print("    Check: sudo crictl ps | grep apiserver")
