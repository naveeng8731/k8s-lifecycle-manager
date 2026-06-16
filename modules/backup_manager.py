import os
import subprocess
import datetime
import json
import shutil
import yaml


# ─────────────────────────────────────────────────────────
# BACKUP MANAGER
#
# Backup storage location is configured in:
#   config/settings.yaml → backup_path
#
# Default  : output/backups     (inside project folder)
# Custom   : any path you set   e.g. /mnt/nas/k8s-backups
#                                     /backup/etcd
#                                     D:\Backups\k8s  (Windows)
#
# To change backup location — edit config/settings.yaml:
#
#   backup_path: /mnt/nas/k8s-backups
#
# That's all. No code changes needed.
# ─────────────────────────────────────────────────────────

# Default etcd cert paths (standard kubeadm cluster)
ETCD_CACERT    = "/etc/kubernetes/pki/etcd/ca.crt"
ETCD_CERT      = "/etc/kubernetes/pki/etcd/server.crt"
ETCD_KEY       = "/etc/kubernetes/pki/etcd/server.key"
ETCD_ENDPOINTS = "https://127.0.0.1:2379"


# ─────────────────────────────────────────────────────────
# READ BACKUP PATH FROM settings.yaml
# Falls back to output/backups if not configured
# ─────────────────────────────────────────────────────────
def get_backup_dir():
    """
    Read backup_path from config/settings.yaml.
    Supports any absolute or relative path.
    Falls back to output/backups if not set.
    """
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config", "settings.yaml"
        )
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        backup_path = cfg.get("backup_path", "output/backups")

        # If relative path — make it relative to project root
        if not os.path.isabs(backup_path):
            project_root = os.path.dirname(os.path.dirname(__file__))
            backup_path  = os.path.join(project_root, backup_path)

        return backup_path

    except Exception:
        # Fallback
        return "output/backups"


def ensure_backup_dir():
    backup_dir = get_backup_dir()
    os.makedirs(backup_dir, exist_ok=True)
    print(f"  [INFO] Backup directory : {os.path.abspath(backup_dir)}")
    return backup_dir


def generate_backup_filename(cluster_version="unknown"):
    backup_dir = get_backup_dir()
    timestamp  = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    version    = cluster_version.lstrip("v").replace(".", "-")
    filename   = f"etcd-backup-v{version}-{timestamp}.db"
    return os.path.join(backup_dir, filename)


def get_file_size(filepath):
    if not os.path.exists(filepath):
        return "0 B"
    size = os.path.getsize(filepath)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def verify_snapshot(backup_file):
    print(f"\n  [INFO] Verifying snapshot integrity...\n")
    result = subprocess.run(
        f"sudo ETCDCTL_API=3 etcdctl snapshot status {backup_file} --write-out=table",
        shell=True
    )
    if result.returncode != 0:
        raise Exception(f"Snapshot verification failed: {backup_file}")
    print("\n  ✔ Snapshot integrity verified")


def save_backup_metadata(backup_file, cluster_version):
    meta_file = backup_file.replace(".db", ".json")
    metadata  = {
        "backup_file":     os.path.abspath(backup_file),
        "cluster_version": cluster_version,
        "timestamp":       datetime.datetime.now().isoformat(),
        "etcd_endpoint":   ETCD_ENDPOINTS,
        "size_bytes":      os.path.getsize(backup_file) if os.path.exists(backup_file) else 0,
        "size_human":      get_file_size(backup_file),
        "status":          "SUCCESS"
    }
    with open(meta_file, "w") as f:
        json.dump(metadata, f, indent=4)
    print(f"  [INFO] Metadata saved   : {meta_file}")


# ─────────────────────────────────────────────────────────
# TAKE ETCD SNAPSHOT
# ─────────────────────────────────────────────────────────
def take_etcd_snapshot(cluster_version="unknown"):

    backup_dir  = ensure_backup_dir()
    backup_file = generate_backup_filename(cluster_version)

    print("\n======================================")
    print(" ETCD BACKUP")
    print("======================================\n")
    print(f"  Backup location : {backup_dir}")
    print(f"  Snapshot file   : {os.path.basename(backup_file)}")
    print(f"  Endpoint        : {ETCD_ENDPOINTS}")
    print()

    # Check etcdctl is installed
    if shutil.which("etcdctl") is None:
        raise Exception(
            "etcdctl not found on this server.\n"
            "  Install it:\n"
            "    ETCD_VER=v3.5.0\n"
            "    curl -LO https://github.com/etcd-io/etcd/releases/download/"
            "${ETCD_VER}/etcd-${ETCD_VER}-linux-amd64.tar.gz\n"
            "    tar -xf etcd-*.tar.gz\n"
            "    sudo mv etcd-*/etcdctl /usr/local/bin/"
        )

    # Check cert files exist
    for f in [ETCD_CACERT, ETCD_CERT, ETCD_KEY]:
        if not os.path.exists(f):
            raise Exception(
                f"etcd certificate not found: {f}\n"
                f"  Make sure you are running on the control plane node."
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
            "  Check etcd is running: kubectl get pods -n kube-system | grep etcd"
        )

    verify_snapshot(backup_file)
    save_backup_metadata(backup_file, cluster_version)

    print(f"\n  ✔ Backup complete")
    print(f"  File : {backup_file}")
    print(f"  Size : {get_file_size(backup_file)}")

    return backup_file


# ─────────────────────────────────────────────────────────
# LIST ALL BACKUPS
# ─────────────────────────────────────────────────────────
def list_backups():
    backup_dir = get_backup_dir()

    if not os.path.exists(backup_dir):
        print(f"\n  [INFO] No backups found — backup dir does not exist: {backup_dir}")
        return []

    backups = sorted(
        [f for f in os.listdir(backup_dir) if f.endswith(".db")],
        reverse=True   # newest first
    )

    if not backups:
        print(f"\n  [INFO] No backups found in: {backup_dir}")
        return []

    print("\n======================================")
    print(" Available etcd Backups")
    print("======================================\n")
    print(f"  Location: {backup_dir}\n")

    for b in backups:
        full_path = os.path.join(backup_dir, b)
        print(f"  {b}  [{get_file_size(full_path)}]")

    return backups


# ─────────────────────────────────────────────────────────
# RESTORE INSTRUCTIONS (manual only — never automate)
# ─────────────────────────────────────────────────────────
def print_restore_instructions(backup_file):
    print("\n======================================")
    print(" RESTORE INSTRUCTIONS (Manual Steps)")
    print("======================================\n")
    print("  Run on the control plane node:\n")
    print(f"  1. sudo systemctl stop etcd")
    print(f"  2. sudo mv /var/lib/etcd /var/lib/etcd.bak")
    print(f"  3. sudo ETCDCTL_API=3 etcdctl snapshot restore {backup_file} \\")
    print(f"         --data-dir=/var/lib/etcd")
    print(f"  4. sudo systemctl start etcd")
    print(f"  5. kubectl get nodes   # verify cluster is back\n")
    print("  ⚠ Only do this if cluster is in unrecoverable state.\n")
