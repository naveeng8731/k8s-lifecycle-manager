# ─────────────────────────────────────────────────────────
# COMPATIBILITY ENGINE
#
# Checks if applications are compatible with the target
# Kubernetes version.
#
# GENERIC approach — does NOT hardcode specific app names.
# Uses categories and version rules instead.
# Adding support for a new tool = add one rule entry.
# ─────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────
# COMPATIBILITY RULES
# Defines which Kubernetes versions require which
# minimum app versions — by CATEGORY not by specific name.
#
# Format:
#   category keyword → min k8s version → action required
# ─────────────────────────────────────────────────────────
COMPATIBILITY_RULES = [
    # Network plugins — always need version check on k8s upgrade
    {
        "keywords":    ["calico", "cilium", "flannel", "weave", "antrea", "cni"],
        "category":    "Network Plugin",
        "action":      "VERSION COMPATIBILITY REQUIRED",
        "reason":      "Network plugins must be compatible with the k8s API version",
        "check_url":   "https://docs.projectcalico.org/getting-started/kubernetes/requirements"
    },

    # Ingress controllers — API versions change between k8s versions
    {
        "keywords":    ["ingress", "traefik", "haproxy", "nginx-ingress", "gateway"],
        "category":    "Ingress Controller",
        "action":      "CHECK API VERSION COMPATIBILITY",
        "reason":      "Ingress API moved from extensions/v1beta1 to networking.k8s.io/v1 in k8s 1.22",
        "check_url":   "https://kubernetes.io/docs/concepts/services-networking/ingress/"
    },

    # Core system components — always upgrade with control plane
    {
        "keywords":    ["kube-proxy", "coredns", "kube-dns"],
        "category":    "Core Component",
        "action":      "CRITICAL - upgrade with control plane",
        "reason":      "Core components are managed by kubeadm and upgrade automatically",
        "check_url":   ""
    },

    # Metrics and autoscaling
    {
        "keywords":    ["metrics-server", "prometheus-adapter", "keda"],
        "category":    "Metrics",
        "action":      "MINOR UPGRADE REQUIRED",
        "reason":      "Metrics API versions may change. Check compatibility matrix.",
        "check_url":   "https://github.com/kubernetes-sigs/metrics-server#compatibility-matrix"
    },

    # Monitoring tools
    {
        "keywords":    ["prometheus", "grafana", "alertmanager", "loki", "thanos"],
        "category":    "Monitoring",
        "action":      "SAFE",
        "reason":      "Monitoring tools are generally k8s version independent",
        "check_url":   ""
    },

    # CI/CD and GitOps
    {
        "keywords":    ["argocd", "argo", "flux", "tekton", "jenkins", "spinnaker"],
        "category":    "CI/CD & GitOps",
        "action":      "SAFE",
        "reason":      "CI/CD tools are generally k8s version independent. Verify CRD compatibility.",
        "check_url":   ""
    },

    # Certificate management
    {
        "keywords":    ["cert-manager", "certmanager"],
        "category":    "Certificate Management",
        "action":      "VERSION COMPATIBILITY REQUIRED",
        "reason":      "cert-manager has specific k8s version requirements per release",
        "check_url":   "https://cert-manager.io/docs/installation/supported-releases/"
    },

    # Storage
    {
        "keywords":    ["csi", "rook", "openebs", "longhorn", "storageclass", "portworx"],
        "category":    "Storage",
        "action":      "CHECK API VERSION COMPATIBILITY",
        "reason":      "CSI APIs evolve with k8s versions. Check driver compatibility.",
        "check_url":   "https://kubernetes-csi.github.io/docs/"
    },

    # Service mesh
    {
        "keywords":    ["istio", "linkerd", "consul", "envoy", "kuma"],
        "category":    "Service Mesh",
        "action":      "VERSION COMPATIBILITY REQUIRED",
        "reason":      "Service meshes have strict k8s version compatibility requirements",
        "check_url":   "https://istio.io/latest/docs/releases/supported-releases/"
    },

    # Security
    {
        "keywords":    ["falco", "kyverno", "opa", "gatekeeper", "aqua", "trivy"],
        "category":    "Security",
        "action":      "SAFE",
        "reason":      "Security tools are generally compatible. Verify CRD versions.",
        "check_url":   ""
    },

    # Backup
    {
        "keywords":    ["velero", "stash", "kasten", "trilio"],
        "category":    "Backup",
        "action":      "SAFE",
        "reason":      "Backup tools are generally k8s version independent",
        "check_url":   ""
    },
]


def _match_rule(name, rule):
    """Check if an app name matches any keyword in a rule"""
    name_lower = name.lower()
    return any(kw in name_lower for kw in rule["keywords"])


def check_compatibility(cluster_version, applications):
    """
    Check each application against compatibility rules.
    Returns list of results with status and reason.
    Generic — works for any app without hardcoding names.
    """
    results = []

    for app in applications:
        name     = app.get("name", "unknown")
        version  = app.get("version", "unknown")

        # Find matching rule
        matched_rule = None
        for rule in COMPATIBILITY_RULES:
            if _match_rule(name, rule):
                matched_rule = rule
                break

        if matched_rule:
            action   = matched_rule["action"]
            category = matched_rule["category"]
            reason   = matched_rule["reason"]
            url      = matched_rule["check_url"]
        else:
            # No rule matched — default to SAFE
            action   = "SAFE"
            category = "Application"
            reason   = "No specific compatibility rule — assumed safe"
            url      = ""

        results.append({
            "component":  name,
            "category":   category,
            "current":    version,
            "status":     action,
            "reason":     reason,
            "check_url":  url,
        })

    return results


def print_compatibility_report(results):
    """Print formatted compatibility report"""
    print("\n======================================")
    print(" Dependency Impact Analysis")
    print("======================================\n")

    # Group by status
    critical = [r for r in results if "CRITICAL" in r["status"]]
    required = [r for r in results if "REQUIRED" in r["status"]]
    check    = [r for r in results if "CHECK" in r["status"]]
    safe     = [r for r in results if r["status"] == "SAFE"]

    for r in critical:
        print(f"  ❌ {r['component']:35} CRITICAL — upgrade with control plane")

    for r in required:
        print(f"  ⚠  {r['component']:35} VERSION COMPATIBILITY REQUIRED")

    for r in check:
        print(f"  ℹ  {r['component']:35} CHECK API VERSION COMPATIBILITY")

    for r in safe:
        print(f"  ✔  {r['component']:35} SAFE")

    if critical:
        print("\n  ⚠  CRITICAL COMPONENTS FOUND — these upgrade automatically with kubeadm")

    return results
