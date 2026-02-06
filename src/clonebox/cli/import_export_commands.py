#!/usr/bin/env python3
"""
Import/Export commands for CloneBox CLI.
"""

import os
from pathlib import Path
from typing import Optional

import questionary

from clonebox.exporter import SecureExporter, VMExporter
from clonebox.importer import SecureImporter, VMImporter
from clonebox.cli.utils import console, custom_style, load_clonebox_config, CLONEBOX_CONFIG_FILE, resolve_vm_name


def cmd_export(args):
    """Export VM configuration and data."""
    vm_name = resolve_vm_name(args.name)
    output_path = Path(args.output)
    user_session = getattr(args, "user", False)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    # Check if VM exists
    from clonebox.cloner import SelectiveVMCloner
    cloner = SelectiveVMCloner(user_session=user_session)
    vms = cloner.list_vms()
    
    if not any(vm["name"] == vm_name for vm in vms):
        console.print(f"[red]❌ VM '{vm_name}' not found[/]")
        return
    
    # Export VM
    exporter = VMExporter(user_session=user_session)
    export_path = exporter.export_vm(
        vm_name=vm_name,
        output_path=output_path,
        include_disk=args.include_disk,
        include_memory=args.include_memory,
        compress=args.compress,
        console=console,
    )
    
    console.print(f"[green]✅ VM exported to: {export_path}[/]")


def cmd_import(args):
    """Import VM from exported archive."""
    import_path = Path(args.import_path)
    new_name = args.name
    user_session = getattr(args, "user", False)
    
    if not import_path.exists():
        console.print(f"[red]❌ Import file not found: {import_path}[/]")
        return
    
    # Import VM
    importer = VMImporter(user_session=user_session)
    vm_name = importer.import_vm(
        import_path=import_path,
        new_name=new_name,
        start=args.start,
        console=console,
    )
    
    console.print(f"[green]✅ VM imported as: {vm_name}[/]")


def cmd_export_encrypted(args):
    """Export VM with encryption."""
    vm_name = args.name
    output_path = Path(args.output)
    user_session = getattr(args, "user", False)
    vm_name = resolve_vm_name(vm_name)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    # Get encryption password
    if args.password:
        password = args.password
    else:
        password = questionary.password(
            "Enter encryption password:", style=custom_style
        ).ask()
        
        if not password:
            console.print("[red]❌ No password provided[/]")
            return
        
        if not questionary.confirm("Confirm password?", style=custom_style).ask():
            return
    
    # Export with encryption
    exporter = SecureExporter(user_session=user_session)
    export_path = exporter.export_encrypted(
        vm_name=vm_name,
        output_path=output_path,
        password=password,
        include_disk=args.include_disk,
        console=console,
    )
    
    console.print(f"[green]✅ VM exported encrypted to: {export_path}[/]")


def cmd_import_encrypted(args):
    """Import VM from encrypted archive."""
    import_path = Path(args.import_path)
    new_name = args.name
    user_session = getattr(args, "user", False)
    
    if not import_path.exists():
        console.print(f"[red]❌ Import file not found: {import_path}[/]")
        return
    
    # Get decryption password
    if args.password:
        password = args.password
    else:
        password = questionary.password(
            "Enter decryption password:", style=custom_style
        ).ask()
        
        if not password:
            console.print("[red]❌ No password provided[/]")
            return
    
    # Import with decryption
    importer = SecureImporter(user_session=user_session)
    vm_name = importer.import_encrypted(
        import_path=import_path,
        password=password,
        new_name=new_name,
        start=args.start,
        console=console,
    )
    
    console.print(f"[green]✅ VM imported as: {vm_name}[/]")


def cmd_export_remote(args):
    """Export VM to remote host."""
    vm_name = args.name
    remote_host = args.remote_host
    remote_path = args.remote_path
    user_session = getattr(args, "user", False)
    
    vm_name = resolve_vm_name(vm_name)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    # Export locally first
    from clonebox.exporter import VMExporter
    exporter = VMExporter(user_session=user_session)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / f"{vm_name}.tar.gz"
        exporter.export_vm(
            vm_name=vm_name,
            output_path=local_path,
            include_disk=args.include_disk,
            compress=True,
            console=console,
        )
        
        # Transfer to remote host
        console.print(f"[cyan]Transferring to {remote_host}...[/]")
        
        cmd = ["scp", str(local_path), f"{remote_host}:{remote_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            console.print(f"[green]✅ VM exported to {remote_host}:{remote_path}[/]")
        else:
            console.print(f"[red]❌ Transfer failed: {result.stderr}[/]")


def cmd_import_remote(args):
    """Import VM from remote host."""
    remote_host = args.remote_host
    remote_path = args.remote_path
    new_name = args.name
    user_session = getattr(args, "user", False)
    
    # Download from remote host
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / Path(remote_path).name
        
        console.print(f"[cyan]Downloading from {remote_host}...[/]")
        
        cmd = ["scp", f"{remote_host}:{remote_path}", str(local_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            console.print(f"[red]❌ Download failed: {result.stderr}[/]")
            return
        
        # Import locally
        from clonebox.importer import VMImporter
        importer = VMImporter(user_session=user_session)
        vm_name = importer.import_vm(
            import_path=local_path,
            new_name=new_name,
            start=args.start,
            console=console,
        )
        
        console.print(f"[green]✅ VM imported as: {vm_name}[/]")


def cmd_sync_key(args):
    """Sync SSH keys with VM."""
    vm_name = args.name
    user_session = getattr(args, "user", False)
    from clonebox import paths as _paths
    conn_uri = _paths.conn_uri(user_session)
    
    vm_name = resolve_vm_name(vm_name)
    if not vm_name:
        console.print("[red]❌ No VM name specified[/]")
        return
    
    # Get public key
    ssh_dir = Path.home() / ".ssh"
    pub_key_path = ssh_dir / "id_rsa.pub"
    
    if not pub_key_path.exists():
        # Try to generate key
        console.print("[yellow]No SSH key found, generating...[/]")
        subprocess.run(["ssh-keygen", "-t", "rsa", "-b", "4096", "-f", str(ssh_dir / "id_rsa"), "-N", ""])
        
        if not pub_key_path.exists():
            console.print("[red]❌ Failed to generate SSH key[/]")
            return
    
    pub_key = pub_key_path.read_text().strip()
    
    # Sync with VM
    from clonebox.cli.utils import _qga_exec
    
    # Create .ssh directory
    _qga_exec(vm_name, conn_uri, "mkdir -p ~/.ssh", timeout=5)
    
    # Add public key to authorized_keys
    auth_keys_cmd = f'echo "{pub_key}" >> ~/.ssh/authorized_keys'
    result = _qga_exec(vm_name, conn_uri, auth_keys_cmd, timeout=5)
    
    if result is not None:
        console.print("[green]✅ SSH key synced with VM[/]")
    else:
        console.print("[red]❌ Failed to sync SSH key[/]")


def cmd_keygen(args):
    """Generate SSH key pair for VM authentication."""
    key_path = Path(args.output) if args.output else Path.cwd() / "clonebox_key"
    
    if key_path.exists() and not args.force:
        console.print(f"[red]❌ Key already exists: {key_path}[/]")
        console.print("[dim]Use --force to overwrite[/]")
        return
    
    # Generate key pair
    from clonebox.secrets import SecretsManager
    
    secrets = SecretsManager()
    key_pair = secrets.generate_ssh_key_pair(key_path)
    
    console.print(f"[green]✅ SSH key pair generated:[/]")
    console.print(f"  Private key: {key_path}")
    console.print(f"  Public key: {key_path}.pub")
    
    if args.copy_to_clipboard:
        import pyperclip
        pyperclip.copy(key_pair.public_key)
        console.print("[green]✅ Public key copied to clipboard[/]")
