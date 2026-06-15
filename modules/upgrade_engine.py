from modules.version_manager import get_upgrade_information
from packaging.version import Version


def _v(v):
    return Version(v.replace("v", ""))


def _fmt(v):
    return f"v{v.major}.{v.minor}.{v.micro}"


def build_upgrade_plan(inventory, compatibility, risks):

    version_info = get_upgrade_information()

    current = inventory.get("cluster_version")
    stable = version_info.get("stable_version")

    if not current or not stable:
        return {
            "eligible": False,
            "risk_score": 999,
            "phases": [],
            "blockers": ["Missing version information"]
        }

    current_v = _v(current)
    stable_v = _v(stable)

    if current_v >= stable_v:
        return {
            "eligible": False,
            "risk_score": 0,
            "target_version": stable,
            "phases": [],
            "blockers": ["Already at stable version"]
        }

    phases = []
    temp = current_v

    # -------------------------
    # SAFE UPGRADE RULE
    # minor only steps
    # -------------------------
    while temp < stable_v:

        next_minor = Version(f"{temp.major}.{temp.minor + 1}.0")

        if next_minor > stable_v:
            next_step = stable_v
        else:
            next_step = next_minor

        phases.append({
            "phase": f"Upgrade to {_fmt(next_step)}",
            "actions": [
                "cordon nodes",
                "drain nodes",
                f"kubeadm upgrade apply {_fmt(next_step)}",
                "uncordon nodes",
                "validate cluster"
            ]
        })

        temp = next_step

    risk_score = 50 + len(risks) * 5 + len(compatibility) * 3

    return {
        "eligible": True,
        "risk_score": risk_score,
        "current_version": current,
        "target_version": stable,
        "phases": phases,
        "blockers": []
    }
