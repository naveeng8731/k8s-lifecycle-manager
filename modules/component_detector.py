import json


# ─────────────────────────────────────────────────────────
# COMPONENT DETECTOR
#
# Detects what is running in the cluster GENERICALLY
# Does NOT hardcode specific app names like "grafana" or "argocd"
# Instead detects by CATEGORY using CRDs, namespaces, pod labels
#
# Categories detected:
#   - Network Plugin (CNI)
#   - Ingress Controllers
#   - Monitoring Stack
#   - Service Mesh
#   - CI/CD / GitOps
#   - Certificate Management
#   - Backup Tools
#   - Storage Operators
#   - API Gateways
#   - Helm releases
# ─────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────
# GENERIC DETECTION RULES
# Matches by CRD group, namespace pattern, or pod label
# Adding a new tool = add one entry here. No code change.
# ─────────────────────────────────────────────────────────
DETECTION_RULES = {

    "Network Plugin": [
        {"type": "crd",       "match": "projectcalico.org",         "name": "Calico"},
        {"type": "crd",       "match": "cilium.io",                 "name": "Cilium"},
        {"type": "pod_ns",    "match": "flannel",                   "name": "Flannel"},
        {"type": "pod_ns",    "match": "weave",                     "name": "Weave Net"},
        {"type": "crd",       "match": "antrea.io",                 "name": "Antrea"},
    ],

    "Ingress Controller": [
        {"type": "pod_name",  "match": "ingress-nginx",             "name": "NGINX Ingress"},
        {"type": "pod_name",  "match": "traefik",                   "name": "Traefik"},
        {"type": "crd",       "match": "gateway.networking.k8s.io", "name": "Gateway API"},
        {"type": "pod_name",  "match": "haproxy-ingress",           "name": "HAProxy Ingress"},
        {"type": "pod_name",  "match": "istio-ingressgateway",      "name": "Istio Ingress"},
    ],

    "Monitoring Stack": [
        {"type": "crd",       "match": "monitoring.coreos.com",     "name": "Prometheus Operator"},
        {"type": "pod_name",  "match": "prometheus",                "name": "Prometheus"},
        {"type": "pod_name",  "match": "grafana",                   "name": "Grafana"},
        {"type": "pod_name",  "match": "alertmanager",              "name": "Alertmanager"},
        {"type": "pod_name",  "match": "loki",                      "name": "Loki"},
        {"type": "pod_name",  "match": "thanos",                    "name": "Thanos"},
        {"type": "pod_name",  "match": "victoria-metrics",          "name": "VictoriaMetrics"},
        {"type": "pod_name",  "match": "datadog",                   "name": "Datadog Agent"},
        {"type": "pod_name",  "match": "newrelic",                  "name": "New Relic"},
    ],

    "Service Mesh": [
        {"type": "crd",       "match": "istio.io",                  "name": "Istio"},
        {"type": "crd",       "match": "linkerd.io",                "name": "Linkerd"},
        {"type": "crd",       "match": "consul.hashicorp.com",      "name": "Consul Connect"},
        {"type": "pod_name",  "match": "kuma",                      "name": "Kuma"},
        {"type": "pod_name",  "match": "osm-controller",            "name": "Open Service Mesh"},
    ],

    "CI/CD & GitOps": [
        {"type": "crd",       "match": "argoproj.io",               "name": "ArgoCD"},
        {"type": "crd",       "match": "fluxcd.io",                 "name": "Flux CD"},
        {"type": "crd",       "match": "tekton.dev",                "name": "Tekton"},
        {"type": "pod_name",  "match": "jenkins",                   "name": "Jenkins"},
        {"type": "pod_name",  "match": "spinnaker",                 "name": "Spinnaker"},
    ],

    "Certificate Management": [
        {"type": "crd",       "match": "cert-manager.io",           "name": "cert-manager"},
        {"type": "crd",       "match": "certificates.k8s.io",       "name": "Kubernetes Cert API"},
        {"type": "pod_name",  "match": "vault",                     "name": "HashiCorp Vault"},
    ],

    "Backup & DR": [
        {"type": "crd",       "match": "velero.io",                 "name": "Velero"},
        {"type": "pod_name",  "match": "stash",                     "name": "Stash"},
        {"type": "pod_name",  "match": "kasten",                    "name": "Kasten K10"},
        {"type": "pod_name",  "match": "trilio",                    "name": "TrilioVault"},
    ],

    "Storage Operator": [
        {"type": "crd",       "match": "rook.io",                   "name": "Rook Ceph"},
        {"type": "pod_name",  "match": "openebs",                   "name": "OpenEBS"},
        {"type": "pod_name",  "match": "longhorn",                  "name": "Longhorn"},
        {"type": "crd",       "match": "storageos.com",             "name": "StorageOS"},
        {"type": "pod_name",  "match": "portworx",                  "name": "Portworx"},
    ],

    "Security": [
        {"type": "crd",       "match": "falco.org",                 "name": "Falco"},
        {"type": "crd",       "match": "aquasecurity.github.io",    "name": "Aqua Security"},
        {"type": "pod_name",  "match": "kyverno",                   "name": "Kyverno"},
        {"type": "pod_name",  "match": "opa",                       "name": "Open Policy Agent"},
        {"type": "pod_name",  "match": "trivy",                     "name": "Trivy"},
    ],

    "Core Components": [
        {"type": "pod_name",  "match": "metrics-server",            "name": "Metrics Server"},
        {"type": "pod_name",  "match": "coredns",                   "name": "CoreDNS"},
        {"type": "pod_name",  "match": "kube-proxy",                "name": "kube-proxy"},
        {"type": "pod_name",  "match": "etcd",                      "name": "etcd"},
        {"type": "pod_name",  "match": "kube-apiserver",            "name": "kube-apiserver"},
    ],
}


def detect_components(data):
    """
    Detect all components running in the cluster generically.
    Returns a dict grouped by category.
    """

    # Build lookup sets for fast matching
    all_crds      = _get_crds(data)
    all_pod_names = _get_pod_names(data)
    all_pod_ns    = _get_pod_namespaces(data)

    detected = {}

    for category, rules in DETECTION_RULES.items():
        found = []
        for rule in rules:
            match = rule["match"].lower()
            name  = rule["name"]

            if rule["type"] == "crd":
                if any(match in crd.lower() for crd in all_crds):
                    found.append(name)

            elif rule["type"] == "pod_name":
                if any(match in pod.lower() for pod in all_pod_names):
                    found.append(name)

            elif rule["type"] == "pod_ns":
                if any(match in ns.lower() for ns in all_pod_ns):
                    found.append(name)

        if found:
            detected[category] = found

    return detected


def _get_crds(data):
    """Get all CRD group names"""
    crds = []
    try:
        for item in data.get("crds", {}).get("items", []):
            group = item.get("spec", {}).get("group", "")
            name  = item.get("metadata", {}).get("name", "")
            crds.append(group)
            crds.append(name)
    except Exception:
        pass
    return crds


def _get_pod_names(data):
    """Get all pod names across all namespaces"""
    names = []
    try:
        for pod in data.get("pods", {}).get("items", []):
            name = pod.get("metadata", {}).get("name", "")
            names.append(name)
    except Exception:
        pass
    return names


def _get_pod_namespaces(data):
    """Get all namespaces that have pods"""
    namespaces = []
    try:
        for pod in data.get("pods", {}).get("items", []):
            ns = pod.get("metadata", {}).get("namespace", "")
            namespaces.append(ns)
    except Exception:
        pass
    return namespaces


def get_node_details(data):
    """
    Get detailed info about each node:
    OS, Kernel, CPU, Memory, Container Runtime
    """
    nodes = []
    try:
        for node in data.get("nodes", {}).get("items", []):
            info   = node.get("status", {}).get("nodeInfo", {})
            caps   = node.get("status", {}).get("capacity", {})
            labels = node.get("metadata", {}).get("labels", {})
            conds  = node.get("status", {}).get("conditions", [])

            # Determine role
            if "node-role.kubernetes.io/control-plane" in labels:
                role = "control-plane"
            elif "node-role.kubernetes.io/master" in labels:
                role = "control-plane"
            else:
                role = "worker"

            # Determine status
            status = "Unknown"
            for cond in conds:
                if cond.get("type") == "Ready":
                    status = "Ready" if cond.get("status") == "True" else "NotReady"

            nodes.append({
                "name":              node.get("metadata", {}).get("name", ""),
                "role":              role,
                "status":            status,
                "os":                info.get("osImage", "Unknown"),
                "kernel":            info.get("kernelVersion", "Unknown"),
                "container_runtime": info.get("containerRuntimeVersion", "Unknown"),
                "cpu":               caps.get("cpu", "Unknown"),
                "memory":            caps.get("memory", "Unknown"),
                "kubelet_version":   info.get("kubeletVersion", "Unknown"),
            })
    except Exception:
        pass
    return nodes


def get_helm_releases(data):
    """
    Detect Helm releases by looking at pod labels
    helm.sh/chart label is set by Helm on all managed resources
    Returns list of unique chart names
    """
    charts = set()
    try:
        # Check deployments
        for item in data.get("deployments", {}).get("items", []):
            labels = item.get("metadata", {}).get("labels", {})
            chart  = labels.get("helm.sh/chart", "") or labels.get("chart", "")
            if chart:
                charts.add(chart.split("-")[0])  # just the name, not version

        # Check pods
        for pod in data.get("pods", {}).get("items", []):
            labels = pod.get("metadata", {}).get("labels", {})
            chart  = labels.get("helm.sh/chart", "") or labels.get("chart", "")
            if chart:
                charts.add(chart.split("-")[0])

    except Exception:
        pass

    return sorted(list(charts))


def print_component_summary(detected):
    """Print a formatted component summary"""
    print("\n======================================")
    print(" Detected Components")
    print("======================================\n")

    if not detected:
        print("  No additional components detected")
        return

    for category, components in detected.items():
        print(f"  {category}:")
        for c in components:
            print(f"    ✔ {c}")
        print()
