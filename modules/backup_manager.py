import os
import subprocess
import datetime
import json
import shutil


# -------------------------
# BACKUP STORAGE LOCATION
# Defined in config/settings.yaml → backup_path: backups
# Final path: output/backups/etcd-backup-<version>-<timestamp>.db
# -------------------------

BACKUP_DIR = "output/backups"

# Default etcd cert paths (standard kubeadm cluster)
ETCD_CACERT    = "/etc/kubernetes/pki/etcd/ca.crt"
ETCD_CERT      = "/etc/kubernetes/pki/etcd/server.crt"
ETCD_KEY       = "/etc/kubernetes/pki/etcd/server.key"
ETCD_ENDPOINTS = "https://127.0.0.1:2379"


def ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    print(f"  [INFO] Backup directory: {os.path.abspath(BACKUP_DIR)}")


def generate_backup_filename(cluster_version="unknown"):
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    version = cluster_version.lstrip("v").replace(".", "-")
    filename = f"etcd-backup-v{version}-{timestamp}.db"
    return os.path.join(BACKUP_DIR, filename)


def get_file_size(filepath):
    if not os.path.exists(filepath):
        return "0B"
    size = os.path.getsize(filepath)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def verify_snapshot(backup_file):
    print(f"\n  [INFO] Verifying snapshot: {backup_file}\n")
    result = subprocess.run(
        f"sudo ETCDCTL_API=3 etcdctl snapshot status {backup_file} --write-out=table",
        shell=True
    )
    if result.returncode != 0:
        raise Exception(f"Snapshot verification failed: {backup_file}")
    print("\n  ✔ Snapshot integrity verified")


def save_backup_metadata(backup_file, cluster_version):
    meta_file = backup_file.replace(".db", ".json")
    metadata = {
        "backup_file": os.path.abspath(backup_file),
        "cluster_version": cluster_version,
        "timestamp": datetime.datetime.now().isoformat(),
        "etcd_endpoint": ETCD_ENDPOINTS,
        "size_bytes": os.path.getsize(backup_file) if os.path.exists(backup_file) else 0,
        "status": "SUCCESS"
    }
    with open(meta_file, "w") as f:
        json.dump(metadata, f, indent=4)
    print(f"  [INFO] Metadata saved: {meta_file}")


# -------------------------
# TAKE ETCD SNAPSHOT
# -------------------------
def take_etcd_snapshot(cluster_version="unknown"):

    ensure_backup_dir()
    backup_file = generate_backup_filename(cluster_version)

    print("\n======================================")
    print(" ETCD BACKUP")
    print("======================================\n")
    print(f"  Target file  : {backup_file}")
    print(f"  Endpoint     : {ETCD_ENDPOINTS}")
    print()

    # Check etcdctl is available
    if shutil.which("etcdctl") is None:
        raise Exception(
            "etcdctl not found. Install it:\n"
            "  ETCD_VER=v3.5.0\n"
            "  curl -LO https://github.com/etcd-io/etcd/releases/download/"
            "${ETCD_VER}/etcd-${ETCD_VER}-linux-amd64.tar.gz\n"
            "  tar -xf etcd-*.tar.gz && sudo mv etcd-*/etcdctl /usr/local/bin/"
        )

    # Check cert files exist
    for f in [ETCD_CACERT, ETCD_CERT, ETCD_KEY]:
        if not os.path.exists(f):
            raise Exception(
                f"etcd cert not found: {f}\n"
                f"Make sure you are running on the control plane node."
            )

    cmd = (
        f"sudo ETCDCTL_API=3 etcdctl snapshot save {backup_file} "
        f"--endpoints={ETCD_ENDPOINTS} "
        f"--cacert={ETCD_CACERT} "
        f"--cert={ETCD_CERT} "
        f"--key={ETCD_KEY}"
    )

    print(f"  [EXEC] {cmd}\n")
    result = subprocess.run(cmd, shell=True)

    if result.returncode != 0:
        raise Exception(
            "etcd snapshot failed.\n"
            "Check etcd pod: kubectl get pods -n kube-system | grep etcd"
        )

    verify_snapshot(backup_file)
    save_backup_metadata(backup_file, cluster_version)

    print(f"\n  ✔ Backup saved : {backup_file}")
    print(f"  Size          : {get_file_size(backup_file)}")

    return backup_file


# -------------------------
# LIST ALL BACKUPS
# -------------------------
def list_backups():
    ensure_backup_dir()
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],
        reverse=True
    )

    if not backups:
        print(f"\n  [INFO] No backups found in: {BACKUP_DIR}")
        return []

    print("\n======================================")
    print(" Available etcd Backups")
    print("======================================\n")
    for b in backups:
        full_path = os.path.join(BACKUP_DIR, b)
        print(f"  {b}  [{get_file_size(full_path)}]")

    return backups


# -------------------------
# RESTORE INSTRUCTIONS (manual only — never automate)
# -------------------------
def print_restore_instructions(backup_file):
    print("\n======================================")
    print(" RESTORE INSTRUCTIONS (Manual Steps)")
    print("======================================\n")
    print("  Run on control plane node:\n")
    print(f"  1. sudo systemctl stop etcd")
    print(f"  2. sudo mv /var/lib/etcd /var/lib/etcd.bak")
    print(f"  3. sudo ETCDCTL_API=3 etcdctl snapshot restore {backup_file} \\")
    print(f"       --data-dir=/var/lib/etcd")
    print(f"  4. sudo systemctl start etcd")
    print(f"  5. kubectl get nodes   # verify cluster is back\n")
    print("  ⚠ Only do this if cluster is in unrecoverable state.\n")
