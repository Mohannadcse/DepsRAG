#!/usr/bin/env python3
"""Cross-ecosystem smoke check for dependency graph and native-node persistence.

This script validates one resolvable package per ecosystem by attempting graph
construction and printing key Neo4j metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

from dotenv import load_dotenv

from dependencyrag.neo4j_tools import (
    _http_get,
    construct_dependency_graph_func,
    get_neo4j_connection,
)


@dataclass
class Candidate:
    ecosystem: str
    name: str
    version: str


CANDIDATES: dict[str, list[Candidate]] = {
    "pypi": [Candidate("pypi", "numpy", "1.26.4")],
    "npm": [Candidate("npm", "bcrypt", "5.1.1")],
    "cargo": [
        Candidate("cargo", "ring", "0.17.8"),
        Candidate("cargo", "tokio", "1.37.0"),
    ],
    "go": [
        Candidate("go", "github.com/gin-gonic/gin", "v1.10.0"),
        Candidate("go", "github.com/google/uuid", "v1.6.0"),
        Candidate("go", "github.com/mattn/go-sqlite3", "v1.14.22"),
    ],
}


def _first_line(text: str) -> str:
    lines = text.splitlines()
    return lines[0] if lines else text


def _is_success(status: str) -> bool:
    return "SUCCESS" in status or "Graph already exists" in status


def _query_graph_metrics(name: str, version: str, ecosystem: str) -> dict:
    conn = get_neo4j_connection()

    direct_pkg = conn.execute_query(
        """
        MATCH (p:Package {name:$name, version:$version, ecosystem:$ecosystem})-[r:DEPENDS_ON]->(d:Package)
        RETURN count(r) AS c
        """,
        {"name": name, "version": version, "ecosystem": ecosystem},
    )[0]["c"]

    reachable_pkg = conn.execute_query(
        """
        MATCH (p:Package {name:$name, version:$version, ecosystem:$ecosystem})-[:DEPENDS_ON*]->(d:Package)
        RETURN count(DISTINCT d) AS c
        """,
        {"name": name, "version": version, "ecosystem": ecosystem},
    )[0]["c"]

    native_nodes = conn.execute_query(
        """
        MATCH (p:Package {name:$name, version:$version, ecosystem:$ecosystem})-[:DEPENDS_ON]->(n:Native)
        RETURN count(DISTINCT n) AS c
        """,
        {"name": name, "version": version, "ecosystem": ecosystem},
    )[0]["c"]

    size_row = conn.execute_query(
        """
        MATCH (p:Package {name:$name, version:$version, ecosystem:$ecosystem})
        RETURN p.main_package_size AS main_size, p.total_size AS total_size
        """,
        {"name": name, "version": version, "ecosystem": ecosystem},
    )
    main_size = size_row[0].get("main_size") if size_row else None
    total_size = size_row[0].get("total_size") if size_row else None

    return {
        "direct_pkg_edges": direct_pkg,
        "reachable_pkg": reachable_pkg,
        "native_nodes": native_nodes,
        "main_size": main_size,
        "total_size": total_size,
    }


def _run_candidates(candidates: Iterable[Candidate]) -> dict:
    last_failure = {
        "package": None,
        "version": None,
        "status": "No candidates provided",
        "direct_pkg_edges": 0,
        "reachable_pkg": 0,
        "native_nodes": 0,
        "main_size": None,
        "total_size": None,
    }

    for candidate in candidates:
        result = construct_dependency_graph_func(
            package_name=candidate.name,
            package_version=candidate.version,
            package_type=candidate.ecosystem,
        )
        status = _first_line(result)

        if _is_success(status):
            metrics = _query_graph_metrics(candidate.name, candidate.version, candidate.ecosystem)
            return {
                "package": candidate.name,
                "version": candidate.version,
                "status": status,
                **metrics,
            }

        last_failure = {
            "package": candidate.name,
            "version": candidate.version,
            "status": status,
            "direct_pkg_edges": 0,
            "reachable_pkg": 0,
            "native_nodes": 0,
            "main_size": None,
            "total_size": None,
        }

    return last_failure


def _depsdev_go_candidate_exists(candidate: Candidate) -> bool:
    """Check whether deps.dev has dependency data for a Go candidate."""
    url = (
        "https://api.deps.dev/v3alpha/systems/go/packages/"
        f"{quote(candidate.name, safe='')}/versions/"
        f"{quote(candidate.version, safe='')}:dependencies"
    )
    response = _http_get(url, timeout=20)
    return response.status_code == 200


def _run_go_candidates(candidates: Iterable[Candidate]) -> dict:
    """Run Go candidates, preferring those that are resolvable via deps.dev."""
    resolvable: list[Candidate] = []
    for candidate in candidates:
        try:
            if _depsdev_go_candidate_exists(candidate):
                resolvable.append(candidate)
        except Exception:
            continue

    if not resolvable:
        return {
            "package": None,
            "version": None,
            "status": "✗ FAILED: No deps.dev-resolvable Go candidate found in configured list.",
            "direct_pkg_edges": 0,
            "reachable_pkg": 0,
            "native_nodes": 0,
            "main_size": None,
            "total_size": None,
        }

    return _run_candidates(resolvable)


def main() -> None:
    load_dotenv(".env")

    print(
        "ecosystem,package,version,status,direct_pkg_edges,reachable_pkg,native_nodes,main_size,total_size"
    )

    for ecosystem, candidates in CANDIDATES.items():
        row = _run_go_candidates(candidates) if ecosystem == "go" else _run_candidates(candidates)
        print(
            f"{ecosystem},{row['package']},{row['version']},{row['status']},"
            f"{row['direct_pkg_edges']},{row['reachable_pkg']},{row['native_nodes']},"
            f"{row['main_size']},{row['total_size']}"
        )


if __name__ == "__main__":
    main()
