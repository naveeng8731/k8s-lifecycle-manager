#!/usr/bin/env python3

import os
import sys
import subprocess

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
# MAIN
# -------------------------
def main():

    print("\n======================================")
    print(" Kubernetes Lifecycle Manager")
    print("======================================\n")

    # -------------------------
    # Discovery phase
    # -------------------------
    run_playbook("playbooks/discovery.yaml")
    run_playbook("playbooks/precheck.yaml")

    if not os.path.exists("output/discovery_raw.json"):
        print("ERROR: discovery_raw.json not found")
        sys.exit(1)

    data = load_discovery_data()

    # -------------------------
    # Inventory build
    # -------------------------
    inventory = detect_cluster_info(data)
    inventory["components"] = detect_components(data)

    applications = get_application_inventory()
    inventory["applications"] = applications

    # -------------------------
    # Risk + Compatibility
    # -------------------------
    risks = analyze_risk(inventory, applications)
    inventory["risks"] = risks

    compatibility = check_compatibility(
        inventory["cluster_version"],
        applications
    )
    inventory["compatibility"] = compatibility

    inventory["health"] = check_cluster_health()

    # -------------------------
    # VERSION INFO
    # -------------------------
    version_info = get_upgrade_information()

    current_version = version_info.get("current_version") or inventory.get("cluster_version")
    stable_version = version_info.get("stable_version")

    inventory["current_version"] = current_version
    inventory["stable_version"] = stable_version

    print("\n======================================")
    print(" Version Analysis")
    print("======================================\n")

    print(f"Current Version : {current_version}")
    print(f"Stable Version  : {stable_version}")

    if current_version and stable_version:
        if current_version == stable_version:
            print("\n✔ Already on stable version")
            print("No upgrade required")
        else:
            print("\n⚠ Upgrade opportunity detected")
    else:
        print("\n❌ Unable to determine stable version")

    # -------------------------
    # DEPENDENCY ANALYSIS (FIXED SAFE PRINT)
    # -------------------------
    dependency_report = analyze_dependencies(
        applications,
        stable_version,
        current_version
    )

    inventory["dependency_report"] = dependency_report

    print("\n======================================")
    print(" Dependency Impact Analysis")
    print("======================================\n")

    for d in dependency_report:
        name = d.get("name") or d.get("component") or "unknown"
        status = d.get("status", "UNKNOWN")
        print(f"  - {name} → {status}")

    # -------------------------
    # UPGRADE PLAN
    # -------------------------
    upgrade_plan = build_upgrade_plan(
        inventory,
        compatibility,
        risks
    )

    inventory["upgrade_plan"] = upgrade_plan

    print("\n======================================")
    print(" Upgrade Plan")
    print("======================================\n")

    print(f"Eligible       : {upgrade_plan.get('eligible')}")
    print(f"Target Version : {upgrade_plan.get('target_version')}")
    print(f"Risk Score     : {upgrade_plan.get('risk_score')}")

    for p in upgrade_plan.get("phases", []):
        print(f"\n  - {p.get('phase')}")
        for a in p.get("actions", []):
            print(f"      * {a}")

    if upgrade_plan.get("blockers"):
        print("\nBlockers:")
        for b in upgrade_plan["blockers"]:
            print(f"  - {b}")

    # -------------------------
    # SAFE NODE LIST
    # -------------------------
    nodes = []
    for n in data.get("nodes", {}).get("items", []):
        name = n.get("metadata", {}).get("name")
        if name:
            nodes.append(name)

    # -------------------------
    # EXECUTION WITH CONFIRMATION
    # -------------------------
    if upgrade_plan.get("eligible"):

        print("\n=== EXECUTION STARTED ===\n")

        confirm = input("Proceed with upgrade? (yes/no): ").strip().lower()

        if confirm == "yes":
            success = execute_upgrade(upgrade_plan, nodes)

            if not success:
                print("\n❌ Upgrade failed → rollback may be required")
        else:
            print("\nUpgrade aborted by user")

    else:
        print("\nUpgrade not eligible → skipping execution")

    # -------------------------
    # SAVE OUTPUT
    # -------------------------
    save_inventory(inventory)
    save_application_inventory(applications)

    print("\nCluster Summary Generated Successfully\n")


if __name__ == "__main__":
    main()
