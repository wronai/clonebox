#!/usr/bin/env python3
"""
Policy and audit commands for CloneBox CLI.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.table import Table

from clonebox.policies import PolicyEngine, PolicyValidationError, PolicyViolationError
from clonebox.audit import get_audit_logger, AuditQuery, AuditEventType, AuditOutcome
from clonebox.cli.utils import console, custom_style, load_clonebox_config, CLONEBOX_CONFIG_FILE


def cmd_policy_validate(args):
    """Validate configuration against policies."""
    config_path = Path(args.config) if args.config else Path.cwd() / CLONEBOX_CONFIG_FILE
    
    if not config_path.exists():
        console.print(f"[red]❌ Config not found: {config_path}[/]")
        return
    
    config = load_clonebox_config(config_path)
    
    # Load policy engine
    policy_engine = PolicyEngine()
    
    try:
        # Validate VM configuration
        vm_config = config.get("vm", {})
        violations = policy_engine.validate_vm_config(vm_config)
        
        if violations:
            console.print(f"[red]❌ Policy violations found:[/]")
            for violation in violations:
                console.print(f"  • {violation}")
        else:
            console.print("[green]✅ VM configuration complies with policies[/]")
        
        # Validate resource limits
        resources = config.get("resources", {})
        resource_violations = policy_engine.validate_resources(resources)
        
        if resource_violations:
            console.print(f"\n[red]❌ Resource policy violations:[/]")
            for violation in resource_violations:
                console.print(f"  • {violation}")
        elif resources:
            console.print("[green]✅ Resource limits comply with policies[/]")
            
    except PolicyValidationError as e:
        console.print(f"[red]❌ Policy validation error: {e}[/]")


def cmd_policy_apply(args):
    """Apply policy to configuration."""
    config_path = Path(args.config) if args.config else Path.cwd() / CLONEBOX_CONFIG_FILE
    
    if not config_path.exists():
        console.print(f"[red]❌ Config not found: {config_path}[/]")
        return
    
    config = load_clonebox_config(config_path)
    
    # Load policy engine
    policy_engine = PolicyEngine()
    
    try:
        # Apply policies to configuration
        updated_config = policy_engine.apply_policies(config)
        
        # Save updated configuration
        backup_path = config_path.with_suffix(f".backup.{int(datetime.now().timestamp())}")
        config_path.rename(backup_path)
        
        with open(config_path, "w") as f:
            import yaml
            yaml.dump(updated_config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        console.print(f"[green]✅ Policies applied to configuration[/]")
        console.print(f"[dim]Backup saved to: {backup_path}[/]")
        
        # Show changes
        changes = policy_engine.get_changes(config, updated_config)
        if changes:
            console.print("\n[bold]Applied changes:[/]")
            for change in changes:
                console.print(f"  • {change}")
                
    except PolicyValidationError as e:
        console.print(f"[red]❌ Policy application error: {e}[/]")


def cmd_audit_list(args):
    """List audit log entries."""
    audit_logger = get_audit_logger()
    
    # Build query
    query = AuditQuery()
    
    if args.event_type:
        try:
            event_type = AuditEventType(args.event_type)
            query.event_type(event_type)
        except ValueError:
            console.print(f"[red]❌ Invalid event type: {args.event_type}[/]")
            return
    
    if getattr(args, 'outcome', None):
        try:
            outcome = AuditOutcome(args.outcome)
            query.outcome(outcome)
        except ValueError:
            console.print(f"[red]❌ Invalid outcome: {args.outcome}[/]")
            return
    
    if getattr(args, 'user', None):
        query.user(args.user)
    
    if getattr(args, 'vm_name', None):
        query.vm_name(args.vm_name)
    
    if getattr(args, 'since', None):
        query.since(datetime.fromisoformat(args.since))
    
    if getattr(args, 'limit', None):
        query.limit(args.limit)
    
    # Execute query
    entries = audit_logger.query(query)
    
    if not entries:
        console.print("[dim]No audit entries found[/]")
        return
    
    # Display results
    table = Table(title="Audit Log")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Event", style="green")
    table.add_column("User", style="yellow")
    table.add_column("VM", style="blue")
    table.add_column("Outcome", style="magenta")
    table.add_column("Details", style="dim")
    
    for entry in entries:
        timestamp = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        event = entry["event_type"].value
        user = entry.get("user", "-")
        vm = entry.get("vm_name", "-")
        outcome = entry["outcome"].value
        outcome_style = "green" if entry["outcome"] == AuditOutcome.SUCCESS else "red"
        details = entry.get("details", "")[:50]
        
        table.add_row(
            timestamp,
            event,
            user,
            vm,
            f"[{outcome_style}]{outcome}[/{outcome_style}]",
            details,
        )
    
    console.print(table)


def cmd_audit_show(args):
    """Show detailed audit entry."""
    audit_logger = get_audit_logger()
    
    entry = audit_logger.get_entry(args.entry_id)
    
    if not entry:
        console.print(f"[red]❌ Audit entry not found: {args.entry_id}[/]")
        return
    
    from rich.panel import Panel
    from rich.table import Table
    
    # Create details table
    table = Table(show_header=False)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("ID", entry["id"])
    table.add_row("Timestamp", entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S"))
    table.add_row("Event Type", entry["event_type"].value)
    table.add_row("User", entry.get("user", "-"))
    table.add_row("VM Name", entry.get("vm_name", "-"))
    table.add_row("Outcome", entry["outcome"].value)
    
    if entry.get("duration"):
        table.add_row("Duration", f"{entry['duration']:.2f}s")
    
    console.print(Panel(table, title=f"Audit Entry: {entry['id']}"))
    
    # Show details
    if entry.get("details"):
        console.print("\n[bold]Details:[/]")
        if args.json:
            console.print(json.dumps(entry["details"], indent=2))
        else:
            console.print(entry["details"])
    
    # Show errors if any
    if entry.get("error"):
        console.print("\n[bold red]Error:[/]")
        console.print(entry["error"])


def cmd_audit_failures(args):
    """Show recent audit failures."""
    audit_logger = get_audit_logger()
    
    query = AuditQuery()
    query.outcome(AuditOutcome.FAILURE)
    query.limit(args.limit or 20)
    
    if args.since:
        query.since(datetime.fromisoformat(args.since))
    
    entries = audit_logger.query(query)
    
    if not entries:
        console.print("[dim]No audit failures found[/]")
        return
    
    # Display results
    table = Table(title="Recent Audit Failures")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Event", style="green")
    table.add_column("User", style="yellow")
    table.add_column("VM", style="blue")
    table.add_column("Error", style="red")
    
    for entry in entries:
        timestamp = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        event = entry["event_type"].value
        user = entry.get("user", "-")
        vm = entry.get("vm_name", "-")
        error = entry.get("error", "Unknown error")[:50]
        
        table.add_row(timestamp, event, user, vm, error)
    
    console.print(table)


def cmd_audit_search(args):
    """Search audit log."""
    audit_logger = get_audit_logger()
    
    entries = audit_logger.search(
        query=args.query,
        event_type=args.event_type,
        limit=args.limit or 50,
    )
    
    if not entries:
        console.print("[dim]No matching audit entries found[/]")
        return
    
    # Display results
    table = Table(title=f"Audit Search Results: '{args.query}'")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Event", style="green")
    table.add_column("User", style="yellow")
    table.add_column("VM", style="blue")
    table.add_column("Match", style="yellow")
    
    for entry in entries:
        timestamp = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        event = entry["event_type"].value
        user = entry.get("user", "-")
        vm = entry.get("vm_name", "-")
        match = entry.get("match", "")[:50]
        
        table.add_row(timestamp, event, user, vm, match)
    
    console.print(table)


def cmd_audit_export(args):
    """Export audit log to file."""
    audit_logger = get_audit_logger()
    
    # Build query
    query = AuditQuery()
    
    if args.since:
        query.since(datetime.fromisoformat(args.since))
    
    if args.until:
        query.until(datetime.fromisoformat(args.until))
    
    if args.event_type:
        try:
            event_type = AuditEventType(args.event_type)
            query.event_type(event_type)
        except ValueError:
            console.print(f"[red]❌ Invalid event type: {args.event_type}[/]")
            return
    
    # Export entries
    entries = audit_logger.export(query)
    
    # Write to file
    output_path = Path(args.output)
    
    if args.format == "json":
        with open(output_path, "w") as f:
            json.dump(entries, f, indent=2, default=str)
    else:  # csv
        import csv
        
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "event_type", "user", "vm_name", "outcome", "details"])
            
            for entry in entries:
                writer.writerow([
                    entry["timestamp"].isoformat(),
                    entry["event_type"].value,
                    entry.get("user", ""),
                    entry.get("vm_name", ""),
                    entry["outcome"].value,
                    entry.get("details", ""),
                ])
    
    console.print(f"[green]✅ Audit log exported to: {output_path}[/]")
    console.print(f"[dim]Exported {len(entries)} entries[/]")
