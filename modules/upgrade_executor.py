import subprocess
import time


# -------------------------
# RUN COMMAND
# -------------------------
def run(cmd):
    print(f"\n[EXEC] {cmd}\n")
    result = subprocess.run(cmd, shell=True)
    return result.returncode


# -------------------------
# NODE OPERATIONS
# -------------------------
def cordon_node(node):
    return run(f"kubectl cordon {node}")


def drain_node(node):
    # FIX: avoid infinite retry loops caused by PDB
    return run(
        f"kubectl drain {node} "
        f"--ignore-daemonsets "
        f"--delete-emptydir-data "
        f"--force "
        f"--timeout=120s"
    )


def uncordon_node(node):
    return run(f"kubectl uncordon {node}")


# -------------------------
# ROLLBACK ENGINE
# -------------------------
def rollback(state):

    print("\n======================================")
    print(" ROLLBACK ENGINE STARTED")
    print("======================================\n")

    nodes = state.get("cordoned_nodes", [])

    if not nodes:
        print("❌ No rollback targets found")
        return

    for node in nodes:
        print(f"Uncordoning node: {node}")
        uncordon_node(node)

    print("\n✔ Rollback completed (best-effort)")


# -------------------------
# EXECUTION ENGINE
# -------------------------
def execute_upgrade(plan, nodes):

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

    state = {
        "cordoned_nodes": [],
        "last_success": None
    }

    try:

        print("\nStarting step-by-step upgrade...\n")

        for phase in phases:

            # FIX: correct field usage
            version = phase.get("version")
            if not version:
                version = phase.get("phase", "").replace("Upgrade to ", "").strip()

            print("\n--------------------------------------")
            print(f"Upgrading to: {version}")
            print("--------------------------------------\n")

            # -------------------------
            # NODE DRAIN SEQUENCE
            # -------------------------
            for node in nodes:

                if cordon_node(node) != 0:
                    raise Exception(f"Failed to cordon {node}")

                rc = drain_node(node)

                if rc != 0:
                    raise Exception(f"Drain failed on {node} at version {version}")

                state["cordoned_nodes"].append(node)

            # -------------------------
            # CONTROL PLANE UPGRADE
            # -------------------------
            cmd = f"sudo kubeadm upgrade apply {version} -y"

            if run(cmd) != 0:
                raise Exception(f"Upgrade failed at {version}")

            # -------------------------
            # RESTORE NODES
            # -------------------------
            for node in nodes:
                uncordon_node(node)

            state["last_success"] = version

            print(f"\n✔ Completed upgrade step: {version}")

        print("\n✔ ALL UPGRADES COMPLETED SUCCESSFULLY")
        return True


    except Exception as e:

        print(f"\n❌ ERROR DURING UPGRADE: {str(e)}")

        print("\n======================================")
        print(" UPGRADE FAILED - RECOVERY MODE")
        print("======================================\n")

        last = state.get("last_success")
        print(f"Last successful version: {last}")

        choice = input("Rollback to last stable state? (yes/no): ").strip().lower()

        if choice == "yes":
            rollback(state)
        else:
            print("\nRollback skipped by user")

        return False
