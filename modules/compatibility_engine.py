def check_compatibility(cluster_version, applications):

    results = []

    for app in applications:

        name = app.get("name", "")
        version = app.get("version", "unknown")

        status = "PASS"
        recommended = version

        # simple rule-based matrix (Day 2 will upgrade this)
        if "calico" in name:
            if version not in ["v3.30.3", "3.30.3"]:
                status = "WARNING"
                recommended = "3.30.3"

        elif "metrics" in name:
            if version not in ["0.8.1", "v0.8.1"]:
                status = "WARNING"
                recommended = "0.8.1"

        elif "ingress" in name:
            status = "PASS"
            recommended = version

        results.append({
            "component": name,
            "current": version,
            "status": status,
            "recommended": recommended
        })

    return results
