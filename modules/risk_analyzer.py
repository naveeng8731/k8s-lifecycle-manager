def analyze_risk(inventory, applications):

    risks = []

    if inventory.get("control_planes", 0) == 1:
        risks.append("Single Control Plane (No HA)")

    if inventory.get("storage_class_count", 0) == 0:
        risks.append("No StorageClass configured")

    if len(applications) > 10:
        risks.append("High number of workloads detected")

    return risks
