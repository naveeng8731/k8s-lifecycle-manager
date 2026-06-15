import json


def save_inventory(inventory):

    with open(
        "output/cluster_inventory.json",
        "w"
    ) as outfile:

        json.dump(
            inventory,
            outfile,
            indent=4
        )

def save_application_inventory(apps):

    import json

    with open(
        "output/component_inventory.json",
        "w"
    ) as f:

        json.dump(
            apps,
            f,
            indent=4
        )
