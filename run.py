#!/usr/bin/env python3

import os
import sys
import subprocess

from modules.cluster_detector import (
    detect_cluster_state,
    get_tool_versions,
    print_cluster_state,
    STATE_HEALTHY,
    STATE_DEGRADED,
    STATE_NOT_INSTALLED,
    STATE_INSTALLED_NO_CLUSTER,
    STATE_UNREACHABLE
)
from modules.cluster_installer import install_fresh_cluster
from modules.discovery import load_discovery_data, detect_cluster_info
from modules.component_detector import detect_components
from modules.report_generator import save_inventory, save_application_inventory
from modules.version_manager import get_upgrade_information
from modules.validation import check_cluster_health
from modules.application_inventory import get_application_inventory
from modules.risk_analyzer import analyze_risk
from modules.compatibility_engine import check_compatibility
from modules.upgrade_engine import build_upgrade_plan
from modules.upgrade_executor import execute_upgrade
from modules.dependency_engine import analyze_dependencies


# -------------------------
# RUN PLAYBOOK
# -------------------------
def run_playbook(playbook):
    print(f"\nRunning {playbook}...\n")

    result = subprocess.run([
        "ansible-playbook",
        "-i",
        "inventory/hosts.ini",
        playbook
    ])

    if result.returncode != 0:
        print(f"\nERROR: {playbook} failed")
        sys.exit(1)


# -------------------------
# UPGRADE FLOW
# Called when cluster already exists
# -------------------------
def run_upgrade_flow(data):

    # Inventory build
    inventory = detect_cluster_info(data)
    inventory["components"] = detect_components(data)

    applications = get_application_inventory()
    inventory["applications"] = applications

    # Risk + Compatibility
    risks = analyze_risk(inventory, applications)
    inventory["risks"] = risks

    compatibility = check_compatibility(
        inventory["cluster_version"],
        applications
    )
    inventory["compatibility"] = compatibility
    inventory["health"] = check_cluster_health()

    # Version info
    version_info = get_upgrade_information()

    current_version = version_info.get("current_version") or inventory.get("cluster_version")
    stable_version  = version_info.get("stable_version")

    inventory["current_version"] = current_version
    inventory["stable_version"]  = stable_version

    print("\n======================================")
    print(" Version Analysis")
    print("======================================\n")
    print(f"  Current Version : {current_version}")
    print(f"  Stable Version  : {stable_version}")

    if current_version and stable_version:
        if current_version == stable_version:
            print("\n  ✔ Already on stable version — no upgrade required")
            save_inventory(inventory)
            save_application_inventory(applications)
            print("\nCluster Summary Generated Successfully\n")
            return
        else:
            print("\n  ⚠ Upgrade opportunity detected")
    else:
        print("\n  ❌ Unable to determine versions")
        save_inventory(inventory)
        save_application_inventory(applications)
        return

    # Dependency analysis
    dependency_report = analyze_dependencies(
        applications,
        stable_version,
        current_version
    )
    inventory["dependency_report"] = dependency_report

    # Upgrade plan
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

    # Node list
    nodes = []
    for n in data.get("nodes", {}).get("items", []):
        name = n.get("metadata", {}).get("name")
        if name:
            nodes.append(name)

    # Execute
    if upgrade_plan.get("eligible"):
        print("\n=== EXECUTION STARTED ===\n")
        confirm = input("Proceed with upgrade? (yes/no): ").strip().lower()

        if confirm == "yes":
            success = execute_upgrade(upgrade_plan, nodes)
            if not success:
                print("\n❌ Upgrade failed → check summary above")
        else:
            print("\nUpgrade aborted by user")
    else:
        print("\nUpgrade not eligible → skipping execution")

    # Save output
    save_inventory(inventory)
    save_application_inventory(applications)
    print("\nCluster Summary Generated Successfully\n")


# -------------------------
# MAIN
# -------------------------
def main():

    print("\n======================================")
    print(" Kubernetes Lifecycle Manager")
    print("======================================\n")

    # ─────────────────────────────────────────
    # PHASE 0: DETECT CLUSTER STATE
    # Check if cluster exists before doing anything
    # ─────────────────────────────────────────
    print("[INFO] Detecting cluster state...\n")

    tool_versions = get_tool_versions()
    state = detect_cluster_state()
    print_cluster_state(state, tool_versions)

    # ─────────────────────────────────────────
    # CASE 1: Tools not installed OR no cluster
    # → Offer fresh installation
    # ─────────────────────────────────────────
    if state in [STATE_NOT_INSTALLED, STATE_INSTALLED_NO_CLUSTER]:

        print("\n======================================")
        print(" No Cluster Detected")
        print("======================================\n")
        print("  Kubernetes is not installed or not initialized on this node.\n")
        print("  Options:")
        print("    1) install - Install a fresh Kubernetes cluster (kubeadm)")
        print("    2) exit    - Exit and handle manually\n")

        choice = input("Choose [install/exit]: ").strip().lower()

        if choice == "install":
            success = install_fresh_cluster()
            if success:
                print("\n✔ Cluster installed successfully!")
                print("  Re-run python3 run.py to manage upgrades.\n")
            else:
                print("\n❌ Installation failed. See errors above.\n")
        else:
            print("\nExiting. No changes made.\n")

        return

    # ─────────────────────────────────────────
    # CASE 2: Cluster unreachable
    # → Cannot proceed, show diagnostic info
    # ─────────────────────────────────────────
    elif state == STATE_UNREACHABLE:

        print("\n======================================")
        print(" Cluster Unreachable")
        print("======================================\n")
        print("  Kubernetes was initialized but the API server is not responding.\n")
        print("  Troubleshooting steps:")
        print("    sudo systemctl status kubelet")
        print("    sudo systemctl restart kubelet")
        print("    sudo crictl ps | grep apiserver")
        print("    sudo journalctl -u kubelet -n 50 --no-pager\n")
        print("  Once cluster is accessible, re-run: python3 run.py\n")
        return

    # ─────────────────────────────────────────
    # CASE 3: Cluster degraded
    # → Warn user and ask if they want to continue
    # ─────────────────────────────────────────
    elif state == STATE_DEGRADED:

        print("\n======================================")
        print(" Cluster Degraded — Nodes Not Ready")
        print("======================================\n")
        print("  One or more nodes are in NotReady state.")
        print("  Running an upgrade on a degraded cluster is risky.\n")
        print("  Check node status:")
        subprocess.run("kubectl get nodes -o wide", shell=True)
        print()

        choice = input("Continue anyway? (yes/no): ").strip().lower()
        if choice != "yes":
            print("\nExiting. Fix node issues first then re-run.\n")
            return
        # Fall through to upgrade flow

    # ─────────────────────────────────────────
    # CASE 4: Cluster is HEALTHY (or user chose to continue on DEGRADED)
    # → Run discovery + upgrade flow
    # ─────────────────────────────────────────

    # Discovery phase
    run_playbook("playbooks/discovery.yaml")
    run_playbook("playbooks/precheck.yaml")

    if not os.path.exists("output/discovery_raw.json"):
        print("ERROR: discovery_raw.json not found")
        sys.exit(1)

    data = load_discovery_data()
    run_upgrade_flow(data)


if __name__ == "__main__":
    main()
