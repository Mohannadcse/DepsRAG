#!/usr/bin/env python3
"""
DepsRAG - Dependency Analysis Chatbot (Agno Version)

Multi-agent chatbot for analyzing software dependencies using Neo4j knowledge graphs.

Run:
    python dependencyrag/main.py
    
Or with options:
    python dependencyrag/main.py --model gpt-4o --debug
"""

import os
import sys
import json
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from dependencyrag.depsrag_team import create_depsrag_team

console = Console()


def get_team_name(team) -> str:
    """Return display name from the created team object."""
    name = getattr(team, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return type(team).__name__


def get_responder_name(response, team) -> str:
    """Return the exact responder name from response metadata when available."""
    for attr in ("agent_name", "from_name", "name", "role"):
        value = getattr(response, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return get_team_name(team)


def _normalize_member_id(name: str) -> str:
    """Normalize a member name to the delegate member_id format."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def get_delegated_member_names(response, team) -> list[str]:
    """Extract delegated member names from tool-call traces in a team response."""
    members = getattr(team, "members", []) or []
    id_to_name = {}
    for member in members:
        member_name = getattr(member, "name", None)
        if isinstance(member_name, str) and member_name.strip():
            id_to_name[_normalize_member_id(member_name)] = member_name.strip()

    delegated = []
    for message in getattr(response, "messages", []) or []:
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue

            function_data = call.get("function") or {}
            if function_data.get("name") != "delegate_task_to_member":
                continue

            raw_args = function_data.get("arguments")
            if not isinstance(raw_args, str):
                continue

            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                continue

            member_id = parsed.get("member_id")
            if not isinstance(member_id, str) or not member_id.strip():
                continue

            resolved_name = id_to_name.get(member_id.strip().lower(), member_id.strip())
            if resolved_name not in delegated:
                delegated.append(resolved_name)

    return delegated


def check_environment(provider: Optional[str] = None) -> bool:
    """Check if required environment variables are set.
    
    Args:
        provider: Specific provider to check ("openai", "azure", "google") or None for auto-detect
    """
    # Check for LLM API keys based on provider
    has_openai_key = os.getenv("OPENAI_API_KEY") is not None
    has_azure_key = os.getenv("AZURE_OPENAI_API_KEY") is not None
    has_google_key = os.getenv("GOOGLE_API_KEY") is not None
    
    # If specific provider requested, check only that one
    if provider == "openai" and not has_openai_key:
        console.print("[bold red]Error: Missing OPENAI_API_KEY[/bold red]")
        console.print("\n[blue]See .env-template for configuration.[/blue]")
        return False
    elif provider == "azure" and not has_azure_key:
        console.print("[bold red]Error: Missing Azure OpenAI configuration[/bold red]")
        console.print("  Required: AZURE_OPENAI_API_KEY")
        console.print("  Also set: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT")
        console.print("\n[blue]See .env-template for configuration.[/blue]")
        return False
    elif provider == "google" and not has_google_key:
        console.print("[bold red]Error: Missing GOOGLE_API_KEY[/bold red]")
        console.print("\n[blue]See .env-template for configuration.[/blue]")
        return False
    elif not provider and not (has_openai_key or has_azure_key or has_google_key):
        # Auto-detect mode: need at least one key
        console.print("[bold red]Error: Missing LLM API key[/bold red]")
        console.print("  Please set one of:")
        console.print("    - OPENAI_API_KEY (for OpenAI)")
        console.print("    - AZURE_OPENAI_API_KEY (for Azure OpenAI)")
        console.print("    - GOOGLE_API_KEY (for Google Gemini)")
        console.print("\n[yellow]For Azure, also set:[/yellow]")
        console.print("  - AZURE_OPENAI_ENDPOINT")
        console.print("  - AZURE_OPENAI_DEPLOYMENT")
        console.print("\n[blue]See .env-template for configuration.[/blue]")
        return False
    
    # Check for required Neo4j variables
    required_vars = [
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEO4J_PASSWORD",
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        console.print(
            f"[bold red]Error: Missing required environment variables:[/bold red]"
        )
        for var in missing_vars:
            console.print(f"  - {var}")
        console.print(
            "\n[yellow]Please set these variables in your .env file or environment.[/yellow]"
        )
        console.print(
            "\n[blue]See .env-template for an example configuration.[/blue]"
        )
        return False
    
    return True


def main():
    """
    DepsRAG - Dependency Analysis Chatbot.
    
    Analyze software dependencies using a multi-agent system with Neo4j knowledge graphs.
    """
    # Parse simple command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="DepsRAG - Dependency Analysis Chatbot")
    parser.add_argument("--model", default="gpt-4o", help="Model ID to use")
    parser.add_argument("--provider", choices=["openai", "azure", "google"], 
                        help="LLM provider (auto-detects from env if not specified)")
    parser.add_argument("--db-file", default="depsrag.db", help="SQLite database file")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming")
    args = parser.parse_args()
    
    model = args.model
    db_file = args.db_file
    debug = args.debug
    stream = not args.no_stream
    
    # Load environment variables
    load_dotenv()
    
    # Check environment
    if not check_environment(provider=args.provider):
        sys.exit(1)
    
    # Display welcome message
    console.print(
        Panel.fit(
            """[bold cyan]Welcome to DepsRAG - Dependency Analysis Chatbot![/bold cyan]
            
[yellow]Powered by Agno Multi-Agent System[/yellow]

This chatbot helps you analyze software dependencies by:
• Building dependency graphs using Neo4j
• Answering questions about dependencies
• Checking for security vulnerabilities
• Searching the web for package information

[green]To get started:[/green]
1. Provide package name, version, and ecosystem
2. Ask questions about the dependencies
3. Get comprehensive, validated answers

[dim]Type 'exit', 'quit', or press Ctrl+C to exit[/dim]""",
            border_style="cyan",
        )
    )
    
    try:
        # Create the DepsRAG team
        console.print("\n[cyan]Initializing DepsRAG multi-agent system...[/cyan]")
        team = create_depsrag_team(
            model_id=model,
            provider=args.provider,
            db_file=db_file,
        )
        console.print("[green]✓ DepsRAG team initialized successfully![/green]\n")
        team_name = get_team_name(team)
        
        # Interactive loop
        console.print(
            f"[yellow]{team_name}:[/yellow] Hello! I'm here to help you analyze "
            "software dependencies.\n"
        )
        console.print(
            f"[yellow]{team_name}:[/yellow] Please provide:\n"
            "  • Package name\n"
            "  • Package version\n"
            "  • Package ecosystem (PyPI, NPM, Cargo, or Go)\n"
        )
        
        while True:
            try:
                # Get user input
                user_input = console.input("\n[bold green]You:[/bold green] ")
                
                # Check for exit commands
                if user_input.lower().strip() in ["exit", "quit", "q", "x"]:
                    console.print(
                        "\n[cyan]Thank you for using DepsRAG! Goodbye![/cyan]"
                    )
                    break
                
                if not user_input.strip():
                    continue
                
                # Process the input with the team
                console.print()
                
                if stream:
                    # Streaming response
                    team.print_response(user_input, stream=True)
                else:
                    # Non-streaming response
                    response = team.run(user_input)
                    responder_name = get_responder_name(response, team)
                    delegated_members = get_delegated_member_names(response, team)
                    if delegated_members:
                        console.print(
                            f"[dim]Team: {get_team_name(team)} | Member: {', '.join(delegated_members)}[/dim]"
                        )
                    else:
                        console.print(
                            f"[dim]Team: {get_team_name(team)} | Member: {responder_name}[/dim]"
                        )
                    console.print(
                        f"\n[yellow]{responder_name}:[/yellow] {response.content}"
                    )
                
            except KeyboardInterrupt:
                console.print(
                    "\n\n[cyan]Interrupted. Type 'exit' to quit or continue chatting.[/cyan]"
                )
                continue
            except Exception as e:
                console.print(f"\n[red]Error:[/red] {str(e)}")
                if debug:
                    import traceback
                    console.print(f"\n[dim]{traceback.format_exc()}[/dim]")
                console.print("\n[yellow]Please try again or type 'exit' to quit.[/yellow]")
    
    except Exception as e:
        console.print(f"\n[bold red]Fatal error:[/bold red] {str(e)}")
        if debug:
            import traceback
            console.print(f"\n[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
