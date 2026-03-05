#!/usr/bin/env python3
"""
Example script demonstrating DepsRAG usage.

This script shows how to:
1. Create the DepsRAG team
2. Build a dependency graph
3. Ask questions about dependencies
4. Check for vulnerabilities
"""

import os
from dotenv import load_dotenv
from dependencyrag import create_depsrag_team

# Load environment variables
load_dotenv()

def main():
    """Run example queries with DepsRAG."""
    
    print("=" * 80)
    print("DepsRAG Example - Analyzing Chainlit Package Dependencies")
    print("=" * 80)
    
    # Create the DepsRAG team
    print("\n1. Initializing DepsRAG team...")
    team = create_depsrag_team(model_id="gpt-4o", db_file="example.db")
    print("✓ Team initialized!\n")
    
    # Example 1: Build the dependency graph
    print("2. Building dependency graph for Chainlit 2.8.0 (PyPI)...")
    print("-" * 80)
    
    response1 = team.run(
        """Please construct the dependency graph for:
        - Package name: chainlit
        - Version: 1.1.200
        - Ecosystem: PyPI
        """
    )
    print(f"\nResponse: {response1.content}\n")
    
    # Example 2: Ask about direct dependencies
    print("\n3. Asking: What are the direct dependencies?")
    print("-" * 80)
    
    response2 = team.run("What are the direct dependencies of chainlit 2.8.0?")
    print(f"\nResponse: {response2.content}\n")
    
    # Example 3: Check for a specific dependency
    print("\n4. Asking: Is there a dependency on a specific package?")
    print("-" * 80)
    
    response3 = team.run("Is there any dependency on fastapi? If yes, what version?")
    print(f"\nResponse: {response3.content}\n")
    
    # Example 4: Check for vulnerabilities
    print("\n5. Checking for vulnerabilities...")
    print("-" * 80)
    
    response4 = team.run(
        "Are there any known vulnerabilities in chainlit version 2.8.0?"
    )
    print(f"\nResponse: {response4.content}\n")
    
    # Example 5: Complex question
    print("\n6. Asking a complex question...")
    print("-" * 80)
    
    response5 = team.run(
        """Which packages have the most dependencies relying on them 
        (i.e., which nodes have the highest in-degree in the graph)?"""
    )
    print(f"\nResponse: {response5.content}\n")
    
    print("=" * 80)
    print("Example completed!")
    print("=" * 80)


if __name__ == "__main__":
    main()
