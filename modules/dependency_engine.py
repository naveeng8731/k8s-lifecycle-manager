def analyze_dependencies(applications, target_version, cluster_version):

    print("\n======================================")
    print(" Dependency Impact Analysis")
    print("======================================\n")

    report = []

    # simple rule engine (you can later replace with real matrix)
    for app in applications:

        name = app.get("name")
        version = app.get("version")

        status = "SAFE"

        # -----------------------------
        # Kubernetes core components
        # -----------------------------
        if "kube-proxy" in name:
            status = "CRITICAL - upgrade with control plane"

        elif "coredns" in name:
            status = "SAFE"

        elif "metrics-server" in name:
            status = "MINOR UPGRADE REQUIRED"

        # -----------------------------
        # CNI / networking layer
        # -----------------------------
        elif "calico" in name:
            status = "VERSION COMPATIBILITY REQUIRED"

        # -----------------------------
        # ingress controllers
        # -----------------------------
        elif "ingress" in name:
            status = "CHECK API VERSION COMPATIBILITY"

        # -----------------------------
        # default case
        # -----------------------------
        else:
            status = "SAFE"

        report.append({
            "component": name,
            "current_version": version,
            "status": status
        })

        print(f"  - {name} → {status}")

    # -----------------------------
    # overall risk summary
    # -----------------------------
    critical = [r for r in report if "CRITICAL" in r["status"]]

    if critical:
        print("\n CRITICAL COMPONENTS FOUND")
    else:
        print("\n No critical dependency blockers")

    return report
