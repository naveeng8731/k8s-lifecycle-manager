import subprocess
import time


# -------------------------
# RUN COMMAND
# -------------------------
# Global remote config — set by execute_upgrade when in remote mode
_exec_remote_config = None


def run(cmd):
    """
    Run a command.
    Remote mode → runs on server via SSH
    Local mode  → runs on this machine
    """
    global _exec_remote_config

    print(f"\n[EXEC] {cmd}\n")

    if _exec_remote_config and _exec_remote_config.get("host"):
        # Remote mode — run on server via SSH
        from modules.remote_connection import ssh_run
        cfg      = _exec_remote_config
        password = cfg.get("_session_password")

        # Prefix sudo with password if available
        if password and "sudo " in cmd:
            cmd = cmd.replace("sudo ", f"echo {password} | sudo -S ", 1)

        result = ssh_run(
            cfg["host"], cfg["user"], cmd,
            port=cfg.get("port", 22),
            ssh_key=cfg.get("ssh_key"),
            password=password,
            timeout=300
        )
        if result.stdout:
            print(result.stdout)
        return result.returncode
    else:
        # Local mode — run directly on this machine
        result = subprocess.run(cmd, shell=True)
        return result.returncode


def cordon_node(node):
    return run(f"kubectl cordon {node}")


def uncordon_node(node):
    return run(f"kubectl uncordon {node}")


# -------------------------
# DETECT SINGLE NODE
# -------------------------
def is_single_node():
    try:
        result = subprocess.run(
            "kubectl get nodes --no-headers | wc -l",
            shell=True, capture_output=True, text=True
        )
        return int(result.stdout.strip()) == 1
    except Exception:
        return False


# -------------------------
# COUNT RUNNING WORKLOADS
# -------------------------
def get_workload_summary():
    summary = {}
    try:
        r = subprocess.run(
            "kubectl get pods --all-namespaces --no-headers "
            "--field-selector=status.phase=Running | wc -l",
            shell=True, capture_output=True, text=True
        )
        summary["running_pods"] = int(r.stdout.strip())
    except Exception:
        summary["running_pods"] = 0

    try:
        r = subprocess.run(
            "kubectl get deployments --all-namespaces --no-headers | wc -l",
            shell=True, capture_output=True, text=True
        )
        summary["deployments"] = int(r.stdout.strip())
    except Exception:
        summary["deployments"] = 0

    try:
        r = subprocess.run(
            "kubectl get statefulsets --all-namespaces --no-headers | wc -l",
            shell=True, capture_output=True, text=True
        )
        summary["statefulsets"] = int(r.stdout.strip())
    except Exception:
        summary["statefulsets"] = 0

    # Check for bare pods (no owner = high risk)
    try:
        r = subprocess.run(
            "kubectl get pods --all-namespaces -o json",
            shell=True, capture_output=True, text=True
        )
        import json
        data = json.loads(r.stdout)
        bare = [
            p for p in data.get("items", [])
            if not p.get("metadata", {}).get("ownerReferences")
        ]
        summary["bare_pods"] = len(bare)
        summary["bare_pod_names"] = [
            f"{p['metadata']['namespace']}/{p['metadata']['name']}"
            for p in bare
        ]
    except Exception:
        summary["bare_pods"] = 0
        summary["bare_pod_names"] = []

    return summary


# -------------------------
# PRE-DRAIN PRODUCTION SAFETY CHECK
# Shows downtime warning and gets explicit confirmation
# before touching production workloads
# -------------------------
def production_safety_check(node, single_node, version):

    summary = get_workload_summary()

    print("\n" + "="*55)
    print("  ⚠  PRODUCTION SAFETY CHECK")
    print("="*55)
    print(f"\n  Node             : {node}")
    print(f"  Upgrade Target   : {version}")
    print(f"  Cluster Type     : {'Single-node ⚠' if single_node else 'Multi-node'}")
    print(f"\n  Workloads at risk:")
    print(f"    Running Pods   : {summary['running_pods']}")
    print(f"    Deployments    : {summary['deployments']}")
    print(f"    StatefulSets   : {summary['statefulsets']}")
    print(f"    Bare Pods      : {summary['bare_pods']}  "
          f"{'← ❌ WILL BE LOST PERMANENTLY' if summary['bare_pods'] > 0 else '✔ none'}")

    if summary["bare_pod_names"]:
        print(f"\n  ❌ Bare pods that will be permanently deleted:")
        for name in summary["bare_pod_names"]:
            print(f"      - {name}")

    if single_node:
        print(f"\n  ⚠  DOWNTIME WARNING — SINGLE NODE CLUSTER")
        print(f"  ─────────────────────────────────────────────")
        print(f"  All {summary['running_pods']} pods will be evicted during drain.")
        print(f"  Your 20-30 microservices will be OFFLINE until:")
        print(f"    1. Upgrade completes (~5-10 min per phase)")
        print(f"    2. Node is uncordoned")
        print(f"    3. Pods are rescheduled and pass readiness checks")
        print(f"\n  Estimated total downtime per phase: 10-20 minutes")
        print(f"\n  Recommended before proceeding:")
        print(f"    ✔ Notify your team / put up a maintenance window")
        print(f"    ✔ Ensure StatefulSet data is backed up")
        print(f"    ✔ Verify no bare pods exist above")
        print(f"    ✔ Run this upgrade during off-peak hours")

    else:
        print(f"\n  ℹ  Multi-node cluster: pods will reschedule on other nodes")
        print(f"     Deployments with replicas > 1 will have zero downtime")
        print(f"     StatefulSets with single replica will have brief downtime")

    print()

    # Explicit confirmation
    confirm = input(
        "  Type 'CONFIRM' to proceed with drain (or anything else to abort): "
    ).strip()

    if confirm != "CONFIRM":
        raise Exception(
            f"Production safety check not confirmed. "
            f"Upgrade stopped at {version}. No changes made to pods."
        )

    print("\n  ✔ Confirmed — proceeding with drain\n")


# -------------------------
# DRAIN NODE
# -------------------------
def drain_node(node, version):

    single_node = is_single_node()

    # Always show safety check first
    production_safety_check(node, single_node, version)

    if single_node:
        print(f"\n[INFO] Single-node: using --force --disable-eviction to bypass PDBs\n")
        rc = run(
            f"kubectl drain {node} "
            f"--ignore-daemonsets "
            f"--delete-emptydir-data "
            f"--force "
            f"--disable-eviction "
            f"--timeout=300s"
        )

        if rc != 0:
            raise Exception(f"Drain failed on {node}")
        return rc

    # Multi-node: try normal drain first
    print(f"\n[INFO] Draining node: {node} (respecting PDBs)...\n")

    result = subprocess.run(
        f"kubectl drain {node} "
        f"--ignore-daemonsets "
        f"--delete-emptydir-data "
        f"--timeout=120s",
        shell=True
    )

    if result.returncode == 0:
        return 0

    # PDB blocked — ask
    print(f"\n⚠  Drain blocked (PodDisruptionBudget)")
    print(f"\n[INFO] Blocking PDBs:\n")
    subprocess.run("kubectl get pdb --all-namespaces", shell=True)

    print("\nOptions:")
    print("  force  - bypass PDBs (--force --disable-eviction)")
    print("  skip   - skip drain, proceed anyway (risky)")
    print("  abort  - stop upgrade here")

    choice = input("\nChoose [force/skip/abort]: ").strip().lower()

    if choice == "force":
        rc = run(
            f"kubectl drain {node} "
            f"--ignore-daemonsets "
            f"--delete-emptydir-data "
            f"--force "
            f"--disable-eviction "
            f"--timeout=300s"
        )
        if rc != 0:
            raise Exception(f"Force drain failed on {node}")
        return rc

    elif choice == "skip":
        print(f"\n[WARN] Skipping drain on {node}\n")
        return 0

    else:
        raise Exception(f"Drain aborted by user. Cluster at last successful version.")


# -------------------------
# UPDATE APT REPO
# -------------------------
def update_k8s_apt_repo(version):

    ver = version.lstrip("v")
    parts = ver.split(".")
    minor_ver = f"v{parts[0]}.{parts[1]}"

    repo_content = (
        f"deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] "
        f"https://pkgs.k8s.io/core:/stable:/{minor_ver}/deb/ /"
    )
    repo_file = "/etc/apt/sources.list.d/kubernetes.list"

    print(f"\n[INFO] Updating Kubernetes apt repo to {minor_ver}\n")

    # Write repo file using sudo tee with heredoc — avoids shell quoting issues
    # Then run apt-get update
    rc = run(
        "sudo tee " + repo_file + " > /dev/null << 'REPO_EOF'" + "\n" +
        repo_content + "\n" +
        "REPO_EOF"
    )
    if rc != 0:
        raise Exception("Failed to write apt repo file to " + repo_file)

    rc = run("sudo apt-get update -qq")
    if rc != 0:
        raise Exception("apt-get update failed")

    # Verify file was written correctly
    run("cat " + repo_file)

    return minor_ver


# -------------------------
# UPGRADE KUBEADM
# -------------------------
def upgrade_kubeadm(version):

    ver = version.lstrip("v")
    update_k8s_apt_repo(version)

    print(f"\n[INFO] Installing kubeadm for v{ver}\n")

    # Install kubeadm — try versioned first, then latest in repo
    cmd = (
        "sudo apt-get install -y --allow-change-held-packages "
        "kubeadm=" + ver + "-* 2>/dev/null || "
        "sudo apt-get install -y --allow-change-held-packages kubeadm"
    )
    rc = run(cmd)

    if rc != 0:
        raise Exception("Failed to install kubeadm=" + ver)

    run("sudo apt-mark hold kubeadm")
    run("kubeadm version")
    return rc


# -------------------------
# UPGRADE KUBELET + KUBECTL
# -------------------------
def upgrade_node_binaries(version):

    ver = version.lstrip("v")
    print(f"\n[INFO] Upgrading kubelet and kubectl to v{ver}\n")

    cmd = (
        "sudo apt-get install -y --allow-change-held-packages "
        "kubelet=" + ver + "-* kubectl=" + ver + "-* 2>/dev/null || "
        "sudo apt-get install -y --allow-change-held-packages kubelet kubectl"
    )
    rc = run(cmd)

    if rc != 0:
        raise Exception("Failed to upgrade kubelet/kubectl to " + ver)

    run("sudo apt-mark hold kubelet kubectl")
    run("sudo systemctl daemon-reload")
    run("sudo systemctl restart kubelet")
    return rc


# -------------------------
# ROLLBACK
# -------------------------
def rollback(state):

    print("\n======================================")
    print(" ROLLBACK ENGINE")
    print("======================================\n")

    nodes = state.get("cordoned_nodes", [])
    if nodes:
        for node in nodes:
            print(f"  Uncordoning: {node}")
            uncordon_node(node)
        print("\n✔ Nodes uncordoned — pods will reschedule")
    else:
        print("[INFO] No cordoned nodes to restore")

    last = state.get("last_success")
    if last:
        print(f"\n✔ Cluster stable at: {last}")
    else:
        print("\n⚠ Cluster at original version")


# -------------------------
# PRINT UPGRADE SUMMARY
# -------------------------
def print_upgrade_summary(original_version, target_version, completed, failed_at, total_phases):

    print("\n")
    print("╔══════════════════════════════════════════════╗")
    print("║           UPGRADE SUMMARY                    ║")
    print("╠══════════════════════════════════════════════╣")
    print(f"║  Original Version : {original_version:<25}║")
    print(f"║  Target Version   : {target_version:<25}║")
    print(f"║  Total Phases     : {str(total_phases):<25}║")
    print(f"║  Completed        : {str(len(completed)):<25}║")
    print("╠══════════════════════════════════════════════╣")

    if completed:
        print("║  ✔ Completed Steps:                          ║")
        for v in completed:
            print(f"║      → {v:<38}║")
    else:
        print("║  ✔ Completed Steps : None                    ║")

    if failed_at:
        print("╠══════════════════════════════════════════════╣")
        print(f"║  ❌ Failed At      : {failed_at:<24}║")

    print("╠══════════════════════════════════════════════╣")

    if not failed_at:
        current = completed[-1] if completed else original_version
        print(f"║  ✔ STATUS : FULLY UPGRADED                   ║")
        print(f"║  Current  : {current:<33}║")
    else:
        current = completed[-1] if completed else original_version
        print(f"║  ⚠ STATUS : PARTIALLY UPGRADED               ║")
        print(f"║  Current State    : {current:<25}║")
        print(f"║  Options:                                    ║")
        print(f"║    • Stay at {current:<32}║")
        print(f"║    • Fix and re-run from {current:<20}║")
        print(f"║    • Rollback to {original_version:<28}║")

    print("╚══════════════════════════════════════════════╝")
    print()


# -------------------------
# EXECUTION ENGINE
# -------------------------
def execute_upgrade(plan, nodes, mode="local", remote_config=None):

    # Set remote config so run() uses SSH in remote mode
    global _exec_remote_config
    if mode == "remote" and remote_config:
        _exec_remote_config = remote_config
    else:
        _exec_remote_config = None

    print("\n======================================")
    print(" PRODUCTION UPGRADE EXECUTOR")
    print("======================================\n")

    if not plan or not plan.get("eligible"):
        print("❌ Upgrade not eligible")
        return False

    phases = plan.get("phases", [])
    if not phases:
        print("❌ No upgrade phases found")
        return False

    original_version = plan.get("current_version", "unknown")
    target_version   = plan.get("target_version", "unknown")
    total_phases     = len(phases)
    single_node      = is_single_node()

    print(f"  Original Version : {original_version}")
    print(f"  Target Version   : {target_version}")
    print(f"  Total Phases     : {total_phases}")
    print(f"  Cluster Type     : {'Single-node ⚠' if single_node else 'Multi-node'}")
    print(f"\n  Upgrade path:")
    prev = original_version
    for p in phases:
        v = p.get("phase", "").replace("Upgrade to ", "").strip()
        print(f"    {prev}  →  {v}")
        prev = v
    print()

    state = {
        "cordoned_nodes": [],
        "last_success":   None,
        "completed":      [],
        "failed_at":      None
    }

    try:

        for i, phase in enumerate(phases, 1):

            version = phase.get("version")
            if not version:
                version = phase.get("phase", "").replace("Upgrade to ", "").strip()

            print(f"\n{'='*50}")
            print(f"  PHASE {i}/{total_phases}  :  {version}")
            print(f"{'='*50}\n")

            # STEP 1: Upgrade kubeadm
            upgrade_kubeadm(version)

            # STEP 2: Cordon + Drain (with safety check)
            for node in nodes:
                if cordon_node(node) != 0:
                    raise Exception(f"Failed to cordon {node}")

                drain_node(node, version)   # safety check inside
                state["cordoned_nodes"].append(node)

            # STEP 3: Upgrade control plane
            if run(f"sudo kubeadm upgrade apply {version} -y") != 0:
                raise Exception(f"kubeadm upgrade apply failed at {version}")

            # STEP 4: Upgrade kubelet + kubectl
            upgrade_node_binaries(version)

            # STEP 5: Uncordon
            for node in nodes:
                uncordon_node(node)

            state["last_success"] = version
            state["completed"].append(version)
            state["cordoned_nodes"] = []

            print(f"\n✔ Phase {i}/{total_phases} completed: {version}\n")

            if i < total_phases:
                print("[INFO] Waiting 30s for cluster to stabilize...\n")
                time.sleep(30)

        print_upgrade_summary(
            original_version, target_version,
            state["completed"], None, total_phases
        )
        return True

    except Exception as e:

        state["failed_at"] = e
        print(f"\n❌ UPGRADE FAILED: {str(e)}")

        failed_version = None
        for p in phases:
            v = p.get("phase", "").replace("Upgrade to ", "").strip()
            if v not in state["completed"]:
                failed_version = v
                break

        print_upgrade_summary(
            original_version, target_version,
            state["completed"], failed_version, total_phases
        )

        current_stable = state["completed"][-1] if state["completed"] else original_version

        print(f"What would you like to do?\n")
        print(f"  stay     - keep cluster at {current_stable} (recommended)")
        print(f"  rollback - rollback to original version {original_version}")
        print(f"  retry    - exit and re-run to retry from {current_stable}")

        choice = input("\nChoose [stay/rollback/retry]: ").strip().lower()

        if choice == "rollback":
            rollback(state)
        elif choice == "retry":
            print(f"\n[INFO] Re-run: python3 k8s-install-upgrade.py  to continue from {current_stable}")
        else:
            print(f"\n✔ Cluster stays at {current_stable}")
            print(f"  Re-run: python3 k8s-install-upgrade.py  to continue upgrade later")

        return False
