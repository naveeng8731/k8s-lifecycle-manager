import json
import re


def extract_version(image):

    if not image:
        return "unknown"

    # handles:
    # nginx:1.25
    # calico/node:v3.30.3
    # registry.io/app:latest
    match = re.search(r':v?([0-9]+\.[0-9]+\.[0-9]+)', image)

    if match:
        return "v" + match.group(1)

    # fallback: last part after :
    if ":" in image:
        return image.split(":")[-1]

    return "latest"

def get_application_inventory():

    with open("output/discovery_raw.json") as f:
        data = json.load(f)

    applications = []

    #
    # Deployments
    #
    for item in data.get("deployments", {}).get("items", []):

        try:

            name = item["metadata"]["name"]

            namespace = item["metadata"]["namespace"]

            image = item["spec"]["template"]["spec"]["containers"][0]["image"]

            applications.append({
                "name": name,
                "namespace": namespace,
                "image": image,
                "version": extract_version(image)
            })

        except:
            pass

    #
    # Daemonsets
    #
    for item in data.get("daemonsets", {}).get("items", []):

        try:

            name = item["metadata"]["name"]

            namespace = item["metadata"]["namespace"]

            image = item["spec"]["template"]["spec"]["containers"][0]["image"]

            applications.append({
                "name": name,
                "namespace": namespace,
                "image": image,
                "version": extract_version(image)
            })

        except:
            pass

    #
    # Statefulsets
    #
    for item in data.get("statefulsets", {}).get("items", []):

        try:

            name = item["metadata"]["name"]

            namespace = item["metadata"]["namespace"]

            image = item["spec"]["template"]["spec"]["containers"][0]["image"]

            applications.append({
                "name": name,
                "namespace": namespace,
                "image": image,
                "version": extract_version(image)
            })

        except:
            pass

    return applications
