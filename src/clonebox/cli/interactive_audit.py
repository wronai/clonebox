#!/usr/bin/env python3
"""
Interactive audit log functions.
"""

import questionary
from rich.console import Console

from clonebox.cli.utils import console, custom_style


def interactive_audit_menu():
    """Audit log menu."""
    console.print("\n[bold cyan]Audit Log[/]\n")
    
    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("📋 List recent entries", value="list"),
            questionary.Choice("🔍 Search log", value="search"),
            questionary.Choice("❌ Show failures", value="failures"),
            questionary.Choice("📤 Export log", value="export"),
            questionary.Choice("🔙 Back", value="back"),
        ],
        style=custom_style,
    ).ask()
    
    if choice == "back":
        return
    
    if choice == "list":
        from clonebox.cli.policy_audit_commands import cmd_audit_list
        args = type('Args', (), {
            'event_type': None,
            'outcome': None,
            'user': None,
            'vm_name': None,
            'since': None,
            'limit': 20
        })()
        cmd_audit_list(args)
        
    elif choice == "search":
        query = questionary.text(
            "Search query:",
            style=custom_style,
        ).ask()
        
        if query:
            from clonebox.cli.policy_audit_commands import cmd_audit_search
            args = type('Args', (), {
                'query': query,
                'event_type': None,
                'limit': 50
            })()
            cmd_audit_search(args)
            
    elif choice == "failures":
        from clonebox.cli.policy_audit_commands import cmd_audit_failures
        args = type('Args', (), {'since': None, 'limit': 20})()
        cmd_audit_failures(args)
        
    elif choice == "export":
        output_path = questionary.text(
            "Output file:",
            style=custom_style,
        ).ask()
        
        if output_path:
            format_choice = questionary.select(
                "Export format:",
                choices=[
                    questionary.Choice("JSON", value="json"),
                    questionary.Choice("CSV", value="csv"),
                ],
                default="json",
                style=custom_style,
            ).ask()
            
            from clonebox.cli.policy_audit_commands import cmd_audit_export
            args = type('Args', (), {
                'output': output_path,
                'since': None,
                'until': None,
                'event_type': None,
                'format': format_choice
            })()
            cmd_audit_export(args)
