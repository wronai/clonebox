#!/usr/bin/env python3
"""
Argument parsers for CloneBox CLI.
"""

import argparse
import sys

from rich.console import Console

from clonebox import __version__
from clonebox.cli.utils import console, custom_style
from clonebox.cli.interactive import interactive_mode

# Import command modules
from clonebox.cli.vm_commands import *
from clonebox.cli.container_commands import *
from clonebox.cli.snapshot_commands import *
from clonebox.cli.monitoring_commands import *
from clonebox.cli.import_export_commands import *
from clonebox.cli.remote_commands import *
from clonebox.cli.policy_audit_commands import *
from clonebox.cli.plugin_commands import *
from clonebox.cli.compose_commands import *
from clonebox.cli.misc_commands import *


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="clonebox", description="Clone your workstation environment to an isolated VM"
    )
    parser.add_argument("--version", action="version", version=f"clonebox {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Interactive mode (default)
    parser.set_defaults(func=lambda args: interactive_mode())

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new CloneBox configuration")
    init_parser.add_argument(
        "path", nargs="?", default=None, help="Path for config file (default: ./.clonebox.yaml)"
    )
    init_parser.add_argument("--name", "-n", help="VM name (default: clonebox-vm)")
    init_parser.add_argument("--ram", type=int, help="RAM in MB (default: 4096)")
    init_parser.add_argument("--vcpus", type=int, help="Number of vCPUs (default: 4)")
    init_parser.add_argument("--disk-size-gb", type=int, help="Root disk size in GB (default: 20)")
    init_parser.add_argument("--base-image", help="Path to base qcow2 image")
    init_parser.add_argument("--no-gui", action="store_true", help="Disable SPICE graphics")
    init_parser.add_argument("--network", help="Network mode (default: auto)")
    init_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing config")
    init_parser.set_defaults(func=cmd_init)

    # Create command
    create_parser = subparsers.add_parser("create", help="Create VM from config")
    create_parser.add_argument("--name", "-n", default="clonebox-vm", help="VM name")
    create_parser.add_argument(
        "--config",
        "-c",
        required=True,
        help='JSON config: {"paths": {}, "packages": [], "services": []}',
    )
    create_parser.add_argument("--ram", type=int, default=4096, help="RAM in MB")
    create_parser.add_argument("--vcpus", type=int, default=4, help="Number of vCPUs")
    create_parser.add_argument(
        "--disk-size-gb",
        type=int,
        default=10,
        help="Root disk size in GB (default: 10)",
    )
    create_parser.add_argument("--base-image", help="Path to base qcow2 image")
    create_parser.add_argument("--no-gui", action="store_true", help="Disable SPICE graphics")
    create_parser.add_argument("--start", "-s", action="store_true", help="Start VM after creation")
    create_parser.set_defaults(func=cmd_create)

    # Start command
    start_parser = subparsers.add_parser("start", help="Start a VM")
    start_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    start_parser.add_argument("--no-viewer", action="store_true", help="Don't open virt-viewer")
    start_parser.add_argument("--viewer", action="store_true", help="Open virt-viewer GUI")
    start_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    start_parser.set_defaults(func=cmd_start)

    # Open command - open VM viewer
    open_parser = subparsers.add_parser("open", help="Open VM viewer window")
    open_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    open_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    open_parser.set_defaults(func=cmd_open)

    # Stop command
    stop_parser = subparsers.add_parser("stop", help="Stop a VM")
    stop_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    stop_parser.add_argument("--force", "-f", action="store_true", help="Force stop")
    stop_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    stop_parser.set_defaults(func=cmd_stop)

    # Restart command
    restart_parser = subparsers.add_parser("restart", help="Restart a VM (stop and start)")
    restart_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    restart_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force stop if VM is stuck",
    )
    restart_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    restart_parser.add_argument(
        "--open",
        action="store_true",
        help="Open GUI after restart",
    )
    restart_parser.set_defaults(func=cmd_restart)

    # Set-password command
    set_password_parser = subparsers.add_parser("set-password", help="Set VM user password")
    set_password_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    set_password_parser.add_argument(
        "--password", "-p", help="Password to set (generated if not provided)"
    )
    set_password_parser.add_argument(
        "--username", default="ubuntu", help="Username to set password for (default: ubuntu)"
    )
    set_password_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    set_password_parser.set_defaults(func=cmd_set_password)

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a VM")
    delete_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    delete_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    delete_parser.add_argument("--keep-storage", action="store_true", help="Keep disk images")
    delete_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    delete_parser.add_argument(
        "--approve",
        action="store_true",
        help="Approve policy-gated operation",
    )
    delete_parser.set_defaults(func=cmd_delete)

    # List command
    list_parser = subparsers.add_parser("list", aliases=["ls"], help="List VMs")
    list_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    list_parser.add_argument("--json", action="store_true", help="Output JSON")
    list_parser.set_defaults(func=cmd_list)

    # Container command
    container_parser = subparsers.add_parser("container", help="Manage container sandboxes")
    container_parser.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default="auto",
        help="Container engine: auto (default), podman, docker",
    )
    container_parser.set_defaults(func=lambda args, p=container_parser: p.print_help())
    container_sub = container_parser.add_subparsers(
        dest="container_command", help="Container commands"
    )

    container_up = container_sub.add_parser("up", help="Start container")
    container_up.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_up.add_argument("path", nargs="?", default=".", help="Workspace path")
    container_up.add_argument("--name", help="Container name")
    container_up.add_argument("--image", default="ubuntu:22.04", help="Container image")
    container_up.add_argument("--detach", action="store_true", help="Run container in background")
    container_up.add_argument(
        "--profile",
        help="Profile name (loads ~/.clonebox.d/<name>.yaml, .clonebox.d/<name>.yaml, or built-in templates)",
    )
    container_up.add_argument(
        "--mount",
        action="append",
        default=[],
        help="Extra mount HOST:CONTAINER (repeatable)",
    )
    container_up.add_argument(
        "--port",
        action="append",
        default=[],
        help="Port mapping (e.g. 8080:80) (repeatable)",
    )
    container_up.add_argument(
        "--package",
        action="append",
        default=[],
        help="Package to install (repeatable)",
    )
    container_up.set_defaults(func=cmd_container_up)

    container_ps = container_sub.add_parser("ps", help="List containers")
    container_ps.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_ps.add_argument("--json", action="store_true", help="Output JSON")
    container_ps.add_argument("-a", "--all", action="store_true", help="Show all containers")
    container_ps.set_defaults(func=cmd_container_ps)

    container_stop = container_sub.add_parser("stop", help="Stop container")
    container_stop.add_argument("name", help="Container name or ID")
    container_stop.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_stop.set_defaults(func=cmd_container_stop)

    container_rm = container_sub.add_parser("rm", help="Remove container")
    container_rm.add_argument("name", help="Container name or ID")
    container_rm.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_rm.set_defaults(func=cmd_container_rm)

    container_down = container_sub.add_parser("down", help="Stop and remove container")
    container_down.add_argument("name", help="Container name or ID")
    container_down.add_argument(
        "--engine",
        choices=["auto", "podman", "docker"],
        default=argparse.SUPPRESS,
        help="Container engine: auto (default), podman, docker",
    )
    container_down.set_defaults(func=cmd_container_down)

    # Dashboard command
    dashboard_parser = subparsers.add_parser("dashboard", help="Launch web dashboard")
    dashboard_parser.add_argument("--host", default="localhost", help="Host to bind to")
    dashboard_parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    dashboard_parser.add_argument("--browser", action="store_true", help="Open in browser")
    dashboard_parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    dashboard_parser.set_defaults(func=cmd_dashboard)

    # Diagnose command
    diagnose_parser = subparsers.add_parser("diagnose", help="Run VM diagnostics")
    diagnose_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    diagnose_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    diagnose_parser.set_defaults(func=cmd_diagnose)

    # Status command
    status_parser = subparsers.add_parser("status", help="Show CloneBox system status")
    status_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    status_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    status_parser.add_argument("--verbose", action="store_true", help="Verbose output")
    status_parser.add_argument("--json", action="store_true", help="Output JSON")
    status_parser.set_defaults(func=cmd_status)

    # Export command
    export_parser = subparsers.add_parser("export", help="Export VM")
    export_parser.add_argument("name", help="VM name")
    export_parser.add_argument("output", help="Output file path")
    export_parser.add_argument("--include-disk", action="store_true", help="Include disk image")
    export_parser.add_argument("--include-memory", action="store_true", help="Include memory state")
    export_parser.add_argument("--compress", action="store_true", help="Compress export")
    export_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    export_parser.set_defaults(func=cmd_export)

    # Import command
    import_parser = subparsers.add_parser("import", help="Import VM")
    import_parser.add_argument("import_path", help="Path to exported VM")
    import_parser.add_argument("--name", help="New VM name")
    import_parser.add_argument("--start", action="store_true", help="Start VM after import")
    import_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    import_parser.set_defaults(func=cmd_import)

    # Test command
    test_parser = subparsers.add_parser("test", help="Run CloneBox self-test")
    test_parser.add_argument("--base-image", help="Path to base image to test")
    test_parser.set_defaults(func=cmd_test)

    # Clone command
    clone_parser = subparsers.add_parser("clone", help="Clone current environment")
    clone_parser.add_argument("path", nargs="?", default=".", help="Path to clone")
    clone_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    clone_parser.add_argument("--name", "-n", help="VM name (default: directory name)")
    clone_parser.add_argument(
        "--run", "-r", action="store_true", help="Create and start VM immediately"
    )
    clone_parser.add_argument(
        "--edit", "-e", action="store_true", help="Open config in editor before creating"
    )
    clone_parser.add_argument(
        "--dedupe", action="store_true", default=True, help="Remove duplicate entries"
    )
    clone_parser.add_argument(
        "--network",
        choices=["auto", "default", "user"],
        default="auto",
        help="Network mode: auto (default), default (libvirt network), user (slirp)",
    )
    clone_parser.add_argument(
        "--base-image",
        help="Path to a bootable qcow2 image to use as a base disk",
    )
    clone_parser.add_argument(
        "--disk-size-gb",
        type=int,
        default=None,
        help="Root disk size in GB (default: 20 for generated configs)",
    )
    clone_parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing VM if it exists",
    )
    clone_parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    clone_parser.add_argument(
        "--approve",
        action="store_true",
        help="Approve policy-gated operation",
    )
    clone_parser.add_argument(
        "--browser-profiles",
        nargs="+",
        choices=["chrome", "chromium", "firefox", "edge", "brave", "opera", "all"],
        help="Copy browser profiles from host to VM (chrome, chromium, firefox, edge, brave, opera, or 'all')",
    )
    clone_parser.set_defaults(func=cmd_clone)

    # Detect command
    detect_parser = subparsers.add_parser("detect", help="Detect system configuration")
    detect_parser.add_argument(
        "component",
        nargs="?",
        choices=["packages", "services", "paths", "network", "hardware", "users"],
        help="Component to detect",
    )
    detect_parser.add_argument("--json", action="store_true", help="Output JSON")
    detect_parser.add_argument("--yaml", action="store_true", help="Output YAML")
    detect_parser.add_argument("--output", help="Save results to file")
    detect_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    detect_parser.set_defaults(func=cmd_detect)

    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Monitor VM resources")
    monitor_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    monitor_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    monitor_parser.set_defaults(func=cmd_monitor)

    # Watch command
    watch_parser = subparsers.add_parser("watch", help="Watch VM status")
    watch_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    watch_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    watch_parser.set_defaults(func=cmd_watch)

    # Logs command
    logs_parser = subparsers.add_parser("logs", help="Show VM logs")
    logs_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    logs_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    logs_parser.add_argument("--all", action="store_true", help="Show all logs at once")
    logs_parser.set_defaults(func=cmd_logs)

    # Repair command
    repair_parser = subparsers.add_parser("repair", help="Attempt to repair VM issues")
    repair_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    repair_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    repair_parser.set_defaults(func=cmd_repair)

    # Exec command
    exec_parser = subparsers.add_parser("exec", help="Execute command in VM")
    exec_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    exec_parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute")
    exec_parser.add_argument("-t", "--timeout", type=int, default=30, help="Command timeout")
    exec_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    exec_parser.set_defaults(func=cmd_exec)

    # Snapshot commands
    snapshot_parser = subparsers.add_parser("snapshot", help="Manage VM snapshots")
    snapshot_parser.set_defaults(func=lambda args, p=snapshot_parser: p.print_help())
    snapshot_sub = snapshot_parser.add_subparsers(
        dest="snapshot_command", help="Snapshot commands"
    )

    snapshot_create = snapshot_sub.add_parser("create", help="Create snapshot")
    snapshot_create.add_argument("name", help="Snapshot name")
    snapshot_create.add_argument("--vm", help="VM name (default: from .clonebox.yaml)")
    snapshot_create.add_argument("--description", help="Snapshot description")
    snapshot_create.add_argument(
        "--type", choices=["disk", "memory"], default="disk", help="Snapshot type"
    )
    snapshot_create.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    snapshot_create.set_defaults(func=cmd_snapshot_create)

    snapshot_list = snapshot_sub.add_parser("list", help="List snapshots")
    snapshot_list.add_argument("--vm", help="VM name (default: from .clonebox.yaml)")
    snapshot_list.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    snapshot_list.set_defaults(func=cmd_snapshot_list)

    snapshot_restore = snapshot_sub.add_parser("restore", help="Restore snapshot")
    snapshot_restore.add_argument("vm_name", help="VM name")
    snapshot_restore.add_argument("snapshot_id", help="Snapshot ID")
    snapshot_restore.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    snapshot_restore.set_defaults(func=cmd_snapshot_restore)

    snapshot_delete = snapshot_sub.add_parser("delete", help="Delete snapshot")
    snapshot_delete.add_argument("vm_name", help="VM name")
    snapshot_delete.add_argument("snapshot_id", help="Snapshot ID")
    snapshot_delete.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    snapshot_delete.set_defaults(func=cmd_snapshot_delete)

    # Health command
    health_parser = subparsers.add_parser("health", help="Run VM health check")
    health_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    health_parser.add_argument("--probe", help="Custom probe command")
    health_parser.add_argument("--timeout", type=int, help="Probe timeout")
    health_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    health_parser.set_defaults(func=cmd_health)

    # Keygen command
    keygen_parser = subparsers.add_parser("keygen", help="Generate SSH key pair")
    keygen_parser.add_argument("--output", help="Output path for key")
    keygen_parser.add_argument("--force", action="store_true", help="Overwrite existing key")
    keygen_parser.add_argument("--copy-to-clipboard", action="store_true", help="Copy public key to clipboard")
    keygen_parser.set_defaults(func=cmd_keygen)

    # Export encrypted command
    export_enc_parser = subparsers.add_parser("export-encrypted", help="Export VM with encryption")
    export_enc_parser.add_argument("name", help="VM name")
    export_enc_parser.add_argument("output", help="Output file path")
    export_enc_parser.add_argument("--password", help="Encryption password")
    export_enc_parser.add_argument("--include-disk", action="store_true", help="Include disk image")
    export_enc_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    export_enc_parser.set_defaults(func=cmd_export_encrypted)

    # Import encrypted command
    import_enc_parser = subparsers.add_parser("import-encrypted", help="Import encrypted VM")
    import_enc_parser.add_argument("import_path", help="Path to encrypted export")
    import_enc_parser.add_argument("--name", help="New VM name")
    import_enc_parser.add_argument("--password", help="Decryption password")
    import_enc_parser.add_argument("--start", action="store_true", help="Start VM after import")
    import_enc_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    import_enc_parser.set_defaults(func=cmd_import_encrypted)

    # Export remote command
    export_remote_parser = subparsers.add_parser("export-remote", help="Export VM to remote host")
    export_remote_parser.add_argument("name", help="VM name")
    export_remote_parser.add_argument("remote_host", help="Remote host (user@hostname)")
    export_remote_parser.add_argument("remote_path", help="Remote path")
    export_remote_parser.add_argument("--include-disk", action="store_true", help="Include disk image")
    export_remote_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    export_remote_parser.set_defaults(func=cmd_export_remote)

    # Import remote command
    import_remote_parser = subparsers.add_parser("import-remote", help="Import VM from remote host")
    import_remote_parser.add_argument("remote_host", help="Remote host (user@hostname)")
    import_remote_parser.add_argument("remote_path", help="Remote path")
    import_remote_parser.add_argument("--name", help="New VM name")
    import_remote_parser.add_argument("--start", action="store_true", help="Start VM after import")
    import_remote_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    import_remote_parser.set_defaults(func=cmd_import_remote)

    # Sync key command
    sync_key_parser = subparsers.add_parser("sync-key", help="Sync SSH key with VM")
    sync_key_parser.add_argument(
        "name", nargs="?", default=None, help="VM name or '.' to use .clonebox.yaml"
    )
    sync_key_parser.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="Use user session (qemu:///session) - no root required",
    )
    sync_key_parser.set_defaults(func=cmd_sync_key)

    # List remote command
    list_remote_parser = subparsers.add_parser("list-remote", help="List configured remote hosts")
    list_remote_parser.set_defaults(func=cmd_list_remote)

    # Policy commands
    policy_parser = subparsers.add_parser("policy", help="Manage policies")
    policy_parser.set_defaults(func=lambda args, p=policy_parser: p.print_help())
    policy_sub = policy_parser.add_subparsers(
        dest="policy_command", help="Policy commands"
    )

    policy_validate = policy_sub.add_parser("validate", help="Validate config against policies")
    policy_validate.add_argument("--config", help="Config file to validate")
    policy_validate.set_defaults(func=cmd_policy_validate)

    policy_apply = policy_sub.add_parser("apply", help="Apply policies to config")
    policy_apply.add_argument("--config", help="Config file to modify")
    policy_apply.set_defaults(func=cmd_policy_apply)

    # Audit commands
    audit_parser = subparsers.add_parser("audit", help="Query audit log")
    audit_parser.set_defaults(func=lambda args, p=audit_parser: p.print_help())
    audit_sub = audit_parser.add_subparsers(
        dest="audit_command", help="Audit commands"
    )

    audit_list = audit_sub.add_parser("list", help="List audit entries")
    audit_list.add_argument("--event-type", help="Filter by event type")
    audit_list.add_argument("--outcome", help="Filter by outcome")
    audit_list.add_argument("--user", help="Filter by user")
    audit_list.add_argument("--vm-name", help="Filter by VM name")
    audit_list.add_argument("--since", help="Filter since date (ISO format)")
    audit_list.add_argument("--limit", type=int, help="Limit number of entries")
    audit_list.set_defaults(func=cmd_audit_list)

    audit_show = audit_sub.add_parser("show", help="Show audit entry details")
    audit_show.add_argument("entry_id", help="Audit entry ID")
    audit_show.add_argument("--json", action="store_true", help="Output JSON")
    audit_show.set_defaults(func=cmd_audit_show)

    audit_failures = audit_sub.add_parser("failures", help="Show recent failures")
    audit_failures.add_argument("--since", help="Filter since date (ISO format)")
    audit_failures.add_argument("--limit", type=int, default=20, help="Limit number of entries")
    audit_failures.set_defaults(func=cmd_audit_failures)

    audit_search = audit_sub.add_parser("search", help="Search audit log")
    audit_search.add_argument("query", help="Search query")
    audit_search.add_argument("--event-type", help="Filter by event type")
    audit_search.add_argument("--limit", type=int, default=50, help="Limit number of entries")
    audit_search.set_defaults(func=cmd_audit_search)

    audit_export = audit_sub.add_parser("export", help="Export audit log")
    audit_export.add_argument("output", help="Output file")
    audit_export.add_argument("--since", help="Filter since date (ISO format)")
    audit_export.add_argument("--until", help="Filter until date (ISO format)")
    audit_export.add_argument("--event-type", help="Filter by event type")
    audit_export.add_argument("--format", choices=["json", "csv"], default="json", help="Output format")
    audit_export.set_defaults(func=cmd_audit_export)

    # Compose commands
    compose_parser = subparsers.add_parser("compose", help="Manage multi-VM environments")
    compose_parser.set_defaults(func=lambda args, p=compose_parser: p.print_help())
    compose_sub = compose_parser.add_subparsers(
        dest="compose_command", help="Compose commands"
    )

    compose_up = compose_sub.add_parser("up", help="Create and start services")
    compose_up.add_argument("-f", "--file", help="Compose file path")
    compose_up.add_argument("-d", "--detach", action="store_true", help="Run in background")
    compose_up.add_argument("services", nargs="*", help="Services to start")
    compose_up.set_defaults(func=cmd_compose_up)

    compose_down = compose_sub.add_parser("down", help="Stop and remove services")
    compose_down.add_argument("-f", "--file", help="Compose file path")
    compose_down.add_argument("--volumes", action="store_true", help="Remove named volumes")
    compose_down.add_argument("services", nargs="*", help="Services to stop")
    compose_down.set_defaults(func=cmd_compose_down)

    compose_status = compose_sub.add_parser("status", help="Show service status")
    compose_status.add_argument("-f", "--file", help="Compose file path")
    compose_status.set_defaults(func=cmd_compose_status)

    compose_logs = compose_sub.add_parser("logs", help="Show service logs")
    compose_logs.add_argument("-f", "--file", help="Compose file path")
    compose_logs.add_argument("--follow", action="store_true", help="Follow log output")
    compose_logs.add_argument("--tail", type=int, dest="lines", help="Number of lines to show")
    compose_logs.add_argument("services", nargs="*", help="Services to show logs for")
    compose_logs.set_defaults(func=cmd_compose_logs)

    compose_ps = compose_sub.add_parser("ps", help="List running services")
    compose_ps.add_argument("-f", "--file", help="Compose file path")
    compose_ps.set_defaults(func=cmd_compose_ps)

    compose_exec = compose_sub.add_parser("exec", help="Execute command in service")
    compose_exec.add_argument("-f", "--file", help="Compose file path")
    compose_exec.add_argument("service", help="Service name")
    compose_exec.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute")
    compose_exec.add_argument("-t", "--timeout", type=int, default=30, help="Command timeout")
    compose_exec.set_defaults(func=cmd_compose_exec)

    compose_restart = compose_sub.add_parser("restart", help="Restart services")
    compose_restart.add_argument("-f", "--file", help="Compose file path")
    compose_restart.add_argument("services", nargs="*", help="Services to restart")
    compose_restart.set_defaults(func=cmd_compose_restart)

    # Plugin commands
    plugin_parser = subparsers.add_parser("plugin", help="Manage plugins")
    plugin_parser.set_defaults(func=lambda args, p=plugin_parser: p.print_help())
    plugin_sub = plugin_parser.add_subparsers(
        dest="plugin_command", help="Plugin commands"
    )

    plugin_list = plugin_sub.add_parser("list", help="List plugins")
    plugin_list.add_argument("-v", "--verbose", action="store_true", help="Show detailed info")
    plugin_list.set_defaults(func=cmd_plugin_list)

    plugin_enable = plugin_sub.add_parser("enable", help="Enable plugin")
    plugin_enable.add_argument("name", help="Plugin name")
    plugin_enable.set_defaults(func=cmd_plugin_enable)

    plugin_disable = plugin_sub.add_parser("disable", help="Disable plugin")
    plugin_disable.add_argument("name", help="Plugin name")
    plugin_disable.set_defaults(func=cmd_plugin_disable)

    plugin_discover = plugin_sub.add_parser("discover", help="Discover plugins")
    plugin_discover.add_argument("paths", nargs="*", help="Search paths")
    plugin_discover.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    plugin_discover.set_defaults(func=cmd_plugin_discover)

    plugin_install = plugin_sub.add_parser("install", help="Install plugin")
    plugin_install.add_argument("source", help="Plugin file or URL")
    plugin_install.add_argument("--global", dest="global_install", action="store_true", help="Install globally")
    plugin_install.set_defaults(func=cmd_plugin_install)

    plugin_uninstall = plugin_sub.add_parser("uninstall", help="Uninstall plugin")
    plugin_uninstall.add_argument("name", help="Plugin name")
    plugin_uninstall.add_argument("-f", "--force", action="store_true", help="Force uninstall")
    plugin_uninstall.set_defaults(func=cmd_plugin_uninstall)

    plugin_info = plugin_sub.add_parser("info", help="Show plugin info")
    plugin_info.add_argument("name", help="Plugin name")
    plugin_info.set_defaults(func=cmd_plugin_info)

    plugin_run = plugin_sub.add_parser("run", help="Run plugin hook")
    plugin_run.add_argument("hook", help="Hook name")
    plugin_run.add_argument("--vm", help="VM name")
    plugin_run.add_argument("--user", help="User name")
    plugin_run.add_argument("--config", help="Configuration")
    plugin_run.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    plugin_run.set_defaults(func=cmd_plugin_run)

    # Remote commands
    remote_parser = subparsers.add_parser("remote", help="Manage remote VMs")
    remote_parser.set_defaults(func=lambda args, p=remote_parser: p.print_help())
    remote_sub = remote_parser.add_subparsers(
        dest="remote_command", help="Remote commands"
    )

    remote_list = remote_sub.add_parser("list", help="List VMs on remote host")
    remote_list.add_argument("host", help="Remote host (user@hostname)")
    remote_list.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_list.add_argument("--json", action="store_true", help="Output JSON")
    remote_list.set_defaults(func=cmd_remote_list)

    remote_status = remote_sub.add_parser("status", help="Get VM status from remote host")
    remote_status.add_argument("host", help="Remote host (user@hostname)")
    remote_status.add_argument("vm_name", help="VM name")
    remote_status.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_status.add_argument("--logs", action="store_true", help="Show recent logs")
    remote_status.set_defaults(func=cmd_remote_status)

    remote_start = remote_sub.add_parser("start", help="Start VM on remote host")
    remote_start.add_argument("host", help="Remote host (user@hostname)")
    remote_start.add_argument("vm_name", help="VM name")
    remote_start.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_start.add_argument("--viewer", action="store_true", help="Open remote viewer")
    remote_start.set_defaults(func=cmd_remote_start)

    remote_stop = remote_sub.add_parser("stop", help="Stop VM on remote host")
    remote_stop.add_argument("host", help="Remote host (user@hostname)")
    remote_stop.add_argument("vm_name", help="VM name")
    remote_stop.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_stop.add_argument("-f", "--force", action="store_true", help="Force stop")
    remote_stop.set_defaults(func=cmd_remote_stop)

    remote_delete = remote_sub.add_parser("delete", aliases=["rm"], help="Delete VM on remote host")
    remote_delete.add_argument("host", help="Remote host (user@hostname)")
    remote_delete.add_argument("vm_name", help="VM name")
    remote_delete.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_delete.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    remote_delete.add_argument("--keep-storage", action="store_true", help="Keep disk images")
    remote_delete.add_argument(
        "--approve",
        action="store_true",
        help="Approve policy-gated operation",
    )
    remote_delete.set_defaults(func=cmd_remote_delete)

    remote_exec = remote_sub.add_parser("exec", help="Execute command in VM on remote host")
    remote_exec.add_argument("host", help="Remote host (user@hostname)")
    remote_exec.add_argument("vm_name", help="VM name")
    remote_exec.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute")
    remote_exec.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_exec.add_argument("-t", "--timeout", type=int, default=30, help="Command timeout")
    remote_exec.set_defaults(func=cmd_remote_exec)

    remote_health = remote_sub.add_parser("health", help="Run health check on remote VM")
    remote_health.add_argument("host", help="Remote host (user@hostname)")
    remote_health.add_argument("vm_name", help="VM name")
    remote_health.add_argument("-u", "--user", action="store_true", help="Use user session on remote")
    remote_health.set_defaults(func=cmd_remote_health)

    args = parser.parse_args()

    if hasattr(args, "func"):
        try:
            args.func(args)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            sys.exit(1)
    else:
        interactive_mode()
