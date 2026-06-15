import json


def load_discovery_data():

    with open("output/discovery_raw.json") as f:
        return json.load(f)


def detect_cluster_info(data):

    inventory = {}

    inventory["control_planes"] = 0
    inventory["workers"] = 0

    for node in data["nodes"]["items"]:

        labels = node["metadata"].get("labels", {})

        if "node-role.kubernetes.io/control-plane" in labels:
            inventory["control_planes"] += 1
        else:
            inventory["workers"] += 1

    inventory["cluster_version"] = (
        data["version"]
        .get("serverVersion", {})
        .get("gitVersion", "Unknown")
    )

    inventory["namespace_count"] = len(
        data["namespaces"].get("items", [])
    )

    inventory["crd_count"] = len(
        data["crds"].get("items", [])
    )

    inventory["storage_class_count"] = len(
        data["storageclasses"].get("items", [])
    )

    return inventory
