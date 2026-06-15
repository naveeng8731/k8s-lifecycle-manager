def detect_components(data):

    components = []

    crds = str(data.get("crds", ""))

    pods = str(data.get("pods", ""))

    if "projectcalico.org" in crds:
        components.append("Calico")

    if "ingress-nginx" in pods:
        components.append("NGINX Ingress")

    if "metrics-server" in pods:
        components.append("Metrics Server")

    if "etcd" in pods:
        components.append("ETCD")

    return components
