#!/usr/bin/env python3

import os
import sys
import subprocess
import argparse

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


# ─────────────────────────────────────────────────────────
# ARGUMENT PARSER
# Supports:
#   python3 run.py                → local mode (default)
#   python3 run.py --mode remote  → remote mode (from local machine)
#   python3 run.py --mode local   → explicit local mode
#   python3 run.py --setup        → show local machine setup instructions
# ─────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="Kubernetes Lifecycle Manager",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=["local", "remote"],
        default="local",
        help=(
            "local  : run directly on the k8s cluster node (default)\n"
            "remote : run from your local machine (Windows/Linux/Mac)\n"
            "         connects to remote cluster via SSH + kubeconfig"
        )
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Show local machine setup instructions for remote mode"
    )
    return parser.parse_args()


# ─────────────────────────────────────────────────────────
# RUN PLAYBOOK
# Supports both local and remote inventory
# ─────────────────────────────────────────────────────────
def run_playbook(playbook, mode="local"):

    print(f"\nRunning {playbook}...\n")

    if mode == "remote":
        # Use k8s_cluster group with SSH connection
        inventory = "inventory/hosts.ini"
        hosts_arg = "k8s_cluster"
        cmd = [
            "ansible-playbook",
            "-i", inventory,
            "--limit", hosts_arg,
            playbook
        ]
    else:
        # Run locally
        cmd = [
            "ansible-playbook",
            "-i", "inventory/hosts.ini",
            "--limit", "local",
            playbook
        ]

    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"\nERROR: {playbook} failed")
        sys.exit(1)


# ─────────────────────────────────────────────────────────
# UPGRADE FLOW
# ─────────────────────────────────────────────────────────
def run_upgrade_flow(data, mode="local"):

    inventory = detect_cluster_info(data)
    inventory["components"] = detect_components(data)
    inventory["mode"] = mode

    applications = get_application_inventory()
    inventory["applications"] = applications

    risks = analyze_risk(inventory, applications)
    inventory["risks"] = risks

    compatibility = check_compatibility(
        inventory["cluster_version"],
        applications
    )
    inventory["compatibility"] = compatibility
    inventory["health"] = check_cluster_health()

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
    print(f"  Mode            : {mode.upper()}")

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

    dependency_report = analyze_dependencies(
        applications, stable_version, current_version
    )
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

    nodes = []
    for n in data.get("nodes", {}).get("items", []):
        name = n.get("metadata", {}).get("name")
        if name:
            nodes.append(name)

    if mode == "remote":
        print("\n" + "="*55)
        print("  ℹ  REMOTE MODE — UPGRADE EXECUTION")
        print("="*55)
        print("\n  You are running in REMOTE mode from your local machine.")
        print("  The upgrade commands (kubeadm, apt-get) will run on")
        print(f"  the remote server via SSH.\n")

    if upgrade_plan.get("eligible"):
        print("\n=== EXECUTION STARTED ===\n")
        confirm = input("Proceed with upgrade? (yes/no): ").strip().lower()

        if confirm == "yes":
            success = execute_upgrade(upgrade_plan, nodes, mode=mode)
            if not success:
                print("\n❌ Upgrade failed → check summary above")
        else:
            print("\nUpgrade aborted by user")
    else:
        print("\nUpgrade not eligible → skipping execution")

    save_inventory(inventory)
    save_application_inventory(applications)
    print("\nCluster Summary Generated Successfully\n")


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():

    args = parse_args()
    mode = args.mode

    print("\n======================================")
    print(" Kubernetes Lifecycle Manager")
    print(f" Mode: {mode.upper()}")
    print("======================================\n")

    # ─────────────────────────────────────────
    # SETUP INSTRUCTIONS MODE
    # ─────────────────────────────────────────
    if args.setup:
        from modules.remote_connection import print_local_setup_instructions
        print_local_setup_instructions()
        return

    # ─────────────────────────────────────────
    # REMOTE MODE SETUP
    # Connect from local machine to remote cluster
    # ─────────────────────────────────────────
    if mode == "remote":
        from modules.remote_connection import setup_remote_connection
        print("[INFO] Establishing remote connection...\n")
        try:
            local_kubeconfig = setup_remote_connection()
        except Exception as e:
            print(f"\n❌ Remote connection failed: {e}")
            print("\nFor setup instructions run:")
            print("  python3 run.py --setup")
            sys.exit(1)

    # ─────────────────────────────────────────
    # DETECT CLUSTER STATE
    # ─────────────────────────────────────────
    print("[INFO] Detecting cluster state...\n")

    tool_versions = get_tool_versions()
    state = detect_cluster_state()
    print_cluster_state(state, tool_versions)

    # ─────────────────────────────────────────
    # NO CLUSTER → OFFER INSTALL
    # Only available in local mode
    # ─────────────────────────────────────────
    if state in [STATE_NOT_INSTALLED, STATE_INSTALLED_NO_CLUSTER]:

        print("\n======================================")
        print(" No Cluster Detected")
        print("======================================\n")

        if mode == "remote":
            print("  ❌ No cluster found on the remote server.")
            print("  Fresh install via remote mode is not supported.")
            print("  Please install Kubernetes on the server first,")
            print("  then re-run: python3 run.py --mode remote\n")
            return

        print("  Kubernetes is not installed or not initialized.\n")
        print("  Options:")
        print("    install - Install a fresh Kubernetes cluster")
        print("    exit    - Exit and handle manually\n")

        choice = input("Choose [install/exit]: ").strip().lower()

        if choice == "install":
            success = install_fresh_cluster()
            if success:
                print("\n✔ Cluster installed! Re-run: python3 run.py\n")
            else:
                print("\n❌ Installation failed. See errors above.\n")
        else:
            print("\nExiting.\n")
        return

    # ─────────────────────────────────────────
    # UNREACHABLE
    # ─────────────────────────────────────────
    elif state == STATE_UNREACHABLE:

        print("\n======================================")
        print(" Cluster Unreachable")
        print("======================================\n")
        print("  Kubernetes API server is not responding.\n")
        print("  Troubleshooting:")
        print("    sudo systemctl status kubelet")
        print("    sudo systemctl restart kubelet")
        print("    sudo crictl ps | grep apiserver")
        print("    sudo journalctl -u kubelet -n 50 --no-pager\n")

        if mode == "remote":
            config = {}
            try:
                from modules.remote_connection import load_remote_config
                config = load_remote_config()
            except Exception:
                pass
            host = config.get("host", "remote-server")
            print(f"  SSH into server and check: ssh {host}")
        return

    # ─────────────────────────────────────────
    # DEGRADED → WARN AND ASK
    # ─────────────────────────────────────────
    elif state == STATE_DEGRADED:

        print("\n======================================")
        print(" Cluster Degraded — Nodes Not Ready")
        print("======================================\n")
        print("  One or more nodes are NOT READY.")
        print("  Upgrading a degraded cluster is risky.\n")
        subprocess.run("kubectl get nodes -o wide", shell=True)
        print()

        choice = input("Continue anyway? (yes/no): ").strip().lower()
        if choice != "yes":
            print("\nExiting. Fix node issues first.\n")
            return

    # ─────────────────────────────────────────
    # HEALTHY → RUN DISCOVERY + UPGRADE FLOW
    # ─────────────────────────────────────────
    run_playbook("playbooks/discovery.yaml", mode=mode)
    run_playbook("playbooks/precheck.yaml", mode=mode)

    if not os.path.exists("output/discovery_raw.json"):
        print("ERROR: discovery_raw.json not found")
        sys.exit(1)

    data = load_discovery_data()
    run_upgrade_flow(data, mode=mode)


if __name__ == "__main__":
    main()
