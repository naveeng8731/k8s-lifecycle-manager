import json
import os
import datetime


# ─────────────────────────────────────────────────────────
# REPORT GENERATOR
# Generates human-readable reports for:
#   1. Discovery Report    → output/discovery_report.txt
#   2. Upgrade Report      → output/upgrade_report.txt
#   3. Cluster Inventory   → output/cluster_inventory.json
#   4. Component Inventory → output/component_inventory.json
# ─────────────────────────────────────────────────────────

os.makedirs("output", exist_ok=True)


def save_inventory(inventory):
    with open("output/cluster_inventory.json", "w") as f:
        json.dump(inventory, f, indent=2, default=str)


def save_application_inventory(applications):
    with open("output/component_inventory.json", "w") as f:
        json.dump(applications, f, indent=2, default=str)


def generate_discovery_report(inventory, node_details, detected_components, helm_releases):
    """
    Generate a human-readable discovery report.
    This is what an engineer reads to understand the cluster.
    """

    lines = []
    ts    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append("=" * 60)
    lines.append(" CLUSTER DISCOVERY REPORT")
    lines.append(f" Generated : {ts}")
    lines.append("=" * 60)

    # ── Cluster Summary ───────────────────────────────────
    lines.append("\n CLUSTER SUMMARY")
    lines.append("-" * 60)
    lines.append(f" Kubernetes Version : {inventory.get('cluster_version', 'Unknown')}")
    lines.append(f" Control Planes     : {inventory.get('control_planes', 0)}")
    lines.append(f" Workers            : {inventory.get('workers', 0)}")
    lines.append(f" Total Nodes        : {inventory.get('control_planes', 0) + inventory.get('workers', 0)}")
    lines.append(f" Namespaces         : {inventory.get('namespace_count', 0)}")
    lines.append(f" Storage Classes    : {inventory.get('storage_class_count', 0)}")
    lines.append(f" CRDs Installed     : {inventory.get('crd_count', 0)}")

    # ── Node Details ──────────────────────────────────────
    if node_details:
        lines.append("\n NODE DETAILS")
        lines.append("-" * 60)
        for node in node_details:
            lines.append(f"\n  Node     : {node['name']}")
            lines.append(f"  Role     : {node['role']}")
            lines.append(f"  Status   : {node['status']}")
            lines.append(f"  OS       : {node['os']}")
            lines.append(f"  Kernel   : {node['kernel']}")
            lines.append(f"  Runtime  : {node['container_runtime']}")
            lines.append(f"  CPU      : {node['cpu']} cores")
            lines.append(f"  Memory   : {node['memory']}")
            lines.append(f"  Kubelet  : {node['kubelet_version']}")

    # ── Detected Components ───────────────────────────────
    if detected_components:
        lines.append("\n DETECTED COMPONENTS")
        lines.append("-" * 60)
        for category, components in detected_components.items():
            lines.append(f"\n  {category}:")
            for c in components:
                lines.append(f"    ✔ {c}")

    # ── Helm Releases ─────────────────────────────────────
    if helm_releases:
        lines.append("\n HELM RELEASES (detected)")
        lines.append("-" * 60)
        for h in helm_releases:
            lines.append(f"  ✔ {h}")

    lines.append("\n" + "=" * 60)

    report = "\n".join(lines)

    with open("output/discovery_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n  [INFO] Discovery report → output/discovery_report.txt")
    return report


def generate_upgrade_report(
    cluster_name,
    original_version,
    target_version,
    completed_phases,
    failed_at,
    node_details,
    detected_components,
    dependency_report,
    backup_file=None
):
    """
    Generate upgrade report showing:
    - What version we started at
    - What phases completed successfully
    - What failed and why
    - Current state
    - Which dependency applications were affected
    - What to do next
    """

    lines = []
    ts    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append("=" * 60)
    lines.append(" UPGRADE REPORT")
    lines.append(f" Generated  : {ts}")
    lines.append("=" * 60)

    # ── Upgrade Summary ───────────────────────────────────
    lines.append("\n UPGRADE SUMMARY")
    lines.append("-" * 60)
    lines.append(f" Cluster         : {cluster_name}")
    lines.append(f" Before Upgrade  : {original_version}")
    lines.append(f" Target Version  : {target_version}")
    lines.append(f" Current State   : {completed_phases[-1] if completed_phases else original_version}")

    if backup_file:
        lines.append(f" etcd Backup     : {backup_file}")

    # ── Phase Results ─────────────────────────────────────
    lines.append("\n UPGRADE PHASES")
    lines.append("-" * 60)

    if completed_phases:
        for phase in completed_phases:
            lines.append(f"  ✔ COMPLETED : {original_version} → {phase}")
            original_version = phase   # next phase starts from here

    if failed_at:
        lines.append(f"  ❌ FAILED AT : {failed_at}")
        lines.append(f"\n  Cluster is currently stable at: {completed_phases[-1] if completed_phases else 'original version'}")
        lines.append(f"\n  OPTIONS:")
        lines.append(f"    1. Stay at {completed_phases[-1] if completed_phases else 'current'}")
        lines.append(f"       → Run: python3 k8s-install-upgrade.py  (continues from here next time)")
        lines.append(f"    2. Rollback to original version")
        lines.append(f"       → Run: ansible-playbook playbooks/rollback.yaml")
        lines.append(f"       NOTE: Binary downgrade must be done manually on server")
    else:
        lines.append(f"\n  ✔ ALL PHASES COMPLETED SUCCESSFULLY")

    # ── Dependency Applications ───────────────────────────
    # This is the key section — shows which apps need attention
    if dependency_report:
        lines.append("\n DEPENDENCY APPLICATIONS — UPGRADE IMPACT")
        lines.append("-" * 60)
        lines.append(" These applications were checked for compatibility:")
        lines.append(" (Generic detection — not tied to specific app names)")
        lines.append("")

        status_groups = {
            "SAFE":                          [],
            "MINOR UPGRADE REQUIRED":        [],
            "VERSION COMPATIBILITY REQUIRED": [],
            "CHECK API VERSION COMPATIBILITY": [],
            "CRITICAL - upgrade with control plane": [],
        }

        for dep in dependency_report:
            name   = dep.get("name") or dep.get("component", "unknown")
            status = dep.get("status", "UNKNOWN")
            for key in status_groups:
                if key in status:
                    status_groups[key].append(name)
                    break

        for status, apps in status_groups.items():
            if apps:
                icon = "[OK]" if status == "SAFE" else "[WARN]" if "MINOR" in status else "[FAIL]"
                lines.append(f"  {icon} {status}:")
                for app in apps:
                    lines.append(f"      - {app}")
                lines.append("")

    # ── Detected Components ───────────────────────────────
    if detected_components:
        lines.append(" COMPONENTS IN CLUSTER (Generic Detection)")
        lines.append("-" * 60)
        for category, components in detected_components.items():
            lines.append(f"  {category}: {', '.join(components)}")

    # ── Node Status ───────────────────────────────────────
    if node_details:
        lines.append("\n NODE STATUS AFTER UPGRADE")
        lines.append("-" * 60)
        for node in node_details:
            icon = "[OK]" if node["status"] == "Ready" else "[FAIL]"
            lines.append(
                f"  {icon} {node['name']:30} "
                f"{node['role']:15} "
                f"{node['status']:10} "
                f"{node.get('kubelet_version', '')}"
            )

    lines.append("\n" + "=" * 60)

    report = "\n".join(lines)

    with open("output/upgrade_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n  [INFO] Upgrade report → output/upgrade_report.txt")
    return report
