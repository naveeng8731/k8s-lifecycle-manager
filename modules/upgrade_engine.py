from modules.version_manager import get_upgrade_information


# -------------------------
# VERSION HELPERS
# No external libraries - pure Python
# -------------------------
def _parse(v):
    """Parse 'v1.30.2' or '1.30.2' → (1, 30, 2)"""
    v = v.strip().lstrip("v")
    parts = v.split(".")
    return tuple(int(x) for x in parts[:3])


def _fmt(t):
    """Format (1, 30, 2) → 'v1.30.2'"""
    return f"v{t[0]}.{t[1]}.{t[2]}"


# -------------------------
# BUILD UPGRADE PLAN
# -------------------------
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

    try:
        current_v = _parse(current)
        stable_v = _parse(stable)
    except Exception as e:
        return {
            "eligible": False,
            "risk_score": 999,
            "phases": [],
            "blockers": [f"Version parse error: {e}"]
        }

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
    # Step one minor version at a time (k8s upgrade policy)
    # FIX: use a step counter to prevent any infinite loop
    # -------------------------
    max_steps = 20
    steps = 0

    while temp < stable_v and steps < max_steps:

        steps += 1

        next_minor = (temp[0], temp[1] + 1, 0)

        if next_minor >= stable_v:
            # Final step — go exactly to stable
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

        # FIX: always advance temp to avoid infinite loop
        temp = next_step

        # If we've reached stable, stop
        if temp >= stable_v:
            break

    risk_score = 50 + len(risks) * 5 + len(compatibility) * 3

    return {
        "eligible": True,
        "risk_score": risk_score,
        "current_version": current,
        "target_version": stable,
        "phases": phases,
        "blockers": []
    }
