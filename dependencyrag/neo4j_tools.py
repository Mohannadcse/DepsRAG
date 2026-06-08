"""
Neo4j tools for Agno agents.
Provides tools for interacting with Neo4j graph database.
"""

import glob
import os
import re
import subprocess
import tarfile
import tempfile
import time
import zipfile
from collections import deque
from typing import Optional, Dict
from urllib.parse import quote

from neo4j import GraphDatabase
from pyvis.network import Network
import requests


class Neo4jConnection:
    """Neo4j database connection manager."""
    
    def __init__(self, uri: str, username: str, password: str, database: str = "neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.database = database
    
    def close(self):
        """Close the database connection."""
        if self.driver:
            self.driver.close()
    
    def execute_query(self, query: str, parameters: Optional[Dict] = None):
        """Execute a Cypher query."""
        with self.driver.session(database=self.database) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]


# Global Neo4j connection (will be initialized when needed)
_neo4j_connection: Optional[Neo4jConnection] = None


_SUPPORTED_SYSTEMS = {"pypi", "npm", "go", "cargo"}
_HTTP_RETRY_ATTEMPTS = 3
_HTTP_RETRY_BACKOFF_SECONDS = 0.5
_HTTP_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def _depsdev_dependencies_url(system: str, package_name: str, package_version: str) -> str:
    """Build deps.dev API URL for package dependencies."""
    return (
        "https://api.deps.dev/v3alpha/systems/"
        f"{quote(system, safe='')}/packages/"
        f"{quote(package_name, safe='')}/versions/"
        f"{quote(package_version, safe='')}:dependencies"
    )


def _http_get(
    url: str,
    *,
    timeout: int,
    stream: bool = False,
    headers: Optional[Dict[str, str]] = None,
):
    """HTTP GET with lightweight retry/backoff for transient failures."""
    last_exception: Optional[requests.RequestException] = None
    last_response = None

    for attempt in range(_HTTP_RETRY_ATTEMPTS):
        try:
            response = requests.get(url, timeout=timeout, stream=stream, headers=headers)
            last_response = response
            should_retry = response.status_code in _HTTP_RETRY_STATUS_CODES
        except requests.RequestException as exc:
            last_exception = exc
            should_retry = True

        if not should_retry:
            return response

        if attempt < _HTTP_RETRY_ATTEMPTS - 1:
            time.sleep(_HTTP_RETRY_BACKOFF_SECONDS * (2**attempt))

    if last_exception is not None:
        raise last_exception
    return last_response


def _human_readable_size(size_bytes: int) -> str:
    """Convert byte size to a human-readable string."""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def _pick_downloaded_artifact(download_dir: str) -> Optional[str]:
    """Pick a wheel/tarball artifact from a pip download directory."""
    wheel_files = sorted(glob.glob(os.path.join(download_dir, "*.whl")))
    tar_files = sorted(glob.glob(os.path.join(download_dir, "*.tar.gz")))
    candidates = wheel_files + tar_files
    return candidates[0] if candidates else None


def _download_file(url: str, output_path: str) -> None:
    """Download a file to disk with streaming to avoid high memory use."""
    # Some registries (for example crates.io) require a user-agent and may
    # reject generic requests.
    headers = {
        "User-Agent": "DepsRAG/1.0 (+https://github.com/depsrag)",
        "Accept": "*/*",
    }
    response = _http_get(url, timeout=45, stream=True, headers=headers)
    response.raise_for_status()
    with open(output_path, "wb") as handle:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                handle.write(chunk)


def _extract_package_artifact(file_path: str, extract_dir: str) -> bool:
    """Extract a wheel or tar.gz package artifact."""
    if (
        file_path.endswith(".tar.gz")
        or file_path.endswith(".tgz")
        or file_path.endswith(".crate")
    ):
        with tarfile.open(file_path, "r:gz") as tar:
            tar.extractall(path=extract_dir)
        return True
    if file_path.endswith(".whl"):
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        return True
    if file_path.endswith(".zip"):
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        return True
    return False


def _find_native_modules(directory: str, ecosystem: str = "pypi") -> list[str]:
    """Find likely native module files in extracted package contents."""
    system = ecosystem.lower()
    ecosystem_extensions = {
        "pypi": (".c", ".cpp", ".dylib", ".dll"),
        "npm": (".c", ".cc", ".cpp", ".h", ".node", ".dylib", ".dll"),
        "cargo": (".c", ".cc", ".cpp", ".h", ".a", ".dylib", ".dll"),
        "go": (".c", ".cc", ".cpp", ".h", ".syso", ".a", ".dylib", ".dll"),
    }
    native_extensions = ecosystem_extensions.get(system, ecosystem_extensions["pypi"])
    so_pattern = re.compile(r".*\.so(\.\d+)*$")

    native_files: list[str] = []
    for root, _, files in os.walk(directory):
        for file_name in files:
            if file_name.endswith(native_extensions) or so_pattern.match(file_name):
                native_files.append(os.path.join(root, file_name))

    # Keep output compact and stable for graph properties.
    return sorted({os.path.basename(path) for path in native_files})


def _analyze_pypi_root_artifact(package_name: str, package_version: str) -> Dict:
    """Analyze root PyPI package artifact size and native modules."""
    with tempfile.TemporaryDirectory(prefix="depsrag_artifact_") as workspace:
        download_dir = os.path.join(workspace, "download")
        extract_dir = os.path.join(workspace, "extract")
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(extract_dir, exist_ok=True)

        try:
            with open(os.devnull, "w", encoding="utf-8") as devnull:
                subprocess.run(
                    [
                        "pip",
                        "download",
                        "--no-deps",
                        f"{package_name}=={package_version}",
                        "--dest",
                        download_dir,
                    ],
                    check=True,
                    stdout=devnull,
                    stderr=devnull,
                )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            return {"error": f"Artifact download failed: {exc}"}

        artifact_path = _pick_downloaded_artifact(download_dir)
        if artifact_path is None:
            return {"error": "No downloadable wheel/tar.gz artifact found"}

        all_downloaded = glob.glob(os.path.join(download_dir, "*"))
        total_size_bytes = sum(os.path.getsize(path) for path in all_downloaded)
        main_size_bytes = os.path.getsize(artifact_path)

        native_modules: list[str] = []
        try:
            if _extract_package_artifact(artifact_path, extract_dir):
                native_modules = _find_native_modules(extract_dir, ecosystem="pypi")
        except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
            return {
                "main_package_size": _human_readable_size(main_size_bytes),
                "total_size": _human_readable_size(total_size_bytes),
                "native_modules": [],
                "error": f"Artifact extraction failed: {exc}",
            }

        return {
            "main_package_size": _human_readable_size(main_size_bytes),
            "total_size": _human_readable_size(total_size_bytes),
            "native_modules": native_modules,
        }


def _analyze_remote_root_artifact(
    ecosystem: str,
    package_name: str,
    package_version: str,
    artifact_url: str,
    artifact_suffix: str,
) -> Dict:
    """Analyze a non-PyPI artifact fetched from a remote registry."""
    with tempfile.TemporaryDirectory(prefix="depsrag_artifact_") as workspace:
        download_dir = os.path.join(workspace, "download")
        extract_dir = os.path.join(workspace, "extract")
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(extract_dir, exist_ok=True)

        artifact_file = os.path.join(
            download_dir,
            f"{package_name.replace('/', '_')}-{package_version}{artifact_suffix}",
        )

        try:
            _download_file(artifact_url, artifact_file)
        except requests.RequestException as exc:
            return {"error": f"Artifact download failed: {exc}"}

        all_downloaded = glob.glob(os.path.join(download_dir, "*"))
        total_size_bytes = sum(os.path.getsize(path) for path in all_downloaded)
        main_size_bytes = os.path.getsize(artifact_file)

        native_modules: list[str] = []
        try:
            if _extract_package_artifact(artifact_file, extract_dir):
                native_modules = _find_native_modules(extract_dir, ecosystem=ecosystem)
        except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
            return {
                "main_package_size": _human_readable_size(main_size_bytes),
                "total_size": _human_readable_size(total_size_bytes),
                "native_modules": [],
                "error": f"Artifact extraction failed: {exc}",
            }

        return {
            "main_package_size": _human_readable_size(main_size_bytes),
            "total_size": _human_readable_size(total_size_bytes),
            "native_modules": native_modules,
        }


def _analyze_npm_root_artifact(package_name: str, package_version: str) -> Dict:
    """Analyze npm package tarball for native modules."""
    metadata_url = (
        "https://registry.npmjs.org/"
        f"{quote(package_name, safe='')}/"
        f"{quote(package_version, safe='')}"
    )
    try:
        response = _http_get(metadata_url, timeout=20)
        response.raise_for_status()
        metadata = response.json()
        tarball_url = metadata.get("dist", {}).get("tarball")
        if not tarball_url:
            return {"error": "No tarball URL found in npm metadata"}
    except (requests.RequestException, ValueError) as exc:
        return {"error": f"Failed to fetch npm metadata: {exc}"}

    return _analyze_remote_root_artifact(
        ecosystem="npm",
        package_name=package_name,
        package_version=package_version,
        artifact_url=tarball_url,
        artifact_suffix=".tgz",
    )


def _analyze_cargo_root_artifact(package_name: str, package_version: str) -> Dict:
    """Analyze crates.io package artifact for native modules."""
    artifact_url = (
        "https://crates.io/api/v1/crates/"
        f"{quote(package_name, safe='')}/"
        f"{quote(package_version, safe='')}/download"
    )
    result = _analyze_remote_root_artifact(
        ecosystem="cargo",
        package_name=package_name,
        package_version=package_version,
        artifact_url=artifact_url,
        artifact_suffix=".crate",
    )

    # Fallback to static URL shape used by crates CDN when API endpoint is blocked.
    if isinstance(result, dict) and "403" in str(result.get("error", "")):
        fallback_url = (
            "https://static.crates.io/crates/"
            f"{quote(package_name, safe='')}/"
            f"{quote(package_name, safe='')}-{quote(package_version, safe='')}.crate"
        )
        return _analyze_remote_root_artifact(
            ecosystem="cargo",
            package_name=package_name,
            package_version=package_version,
            artifact_url=fallback_url,
            artifact_suffix=".crate",
        )

    return result


def _analyze_go_root_artifact(package_name: str, package_version: str) -> Dict:
    """Analyze Go module archive for native modules."""
    artifact_url = (
        "https://proxy.golang.org/"
        f"{quote(package_name, safe='')}/@v/"
        f"{quote(package_version, safe='')}.zip"
    )
    return _analyze_remote_root_artifact(
        ecosystem="go",
        package_name=package_name,
        package_version=package_version,
        artifact_url=artifact_url,
        artifact_suffix=".zip",
    )


def _analyze_root_artifact(ecosystem: str, package_name: str, package_version: str) -> Dict:
    """Dispatch ecosystem-specific root artifact/native analysis."""
    if ecosystem == "pypi":
        return _analyze_pypi_root_artifact(package_name, package_version)
    if ecosystem == "npm":
        return _analyze_npm_root_artifact(package_name, package_version)
    if ecosystem == "cargo":
        return _analyze_cargo_root_artifact(package_name, package_version)
    if ecosystem == "go":
        return _analyze_go_root_artifact(package_name, package_version)
    return {"error": f"Native artifact analysis not supported for ecosystem: {ecosystem}"}


def _fetch_dependencies_json(system: str, package_name: str, package_version: str) -> Dict:
    """Fetch dependencies JSON from deps.dev and raise for non-success."""
    url = _depsdev_dependencies_url(system, package_name, package_version)
    response = _http_get(url, timeout=20)
    if response.status_code == 404:
        raise ValueError(
            f"Dependency data not found in deps.dev for {package_name} "
            f"{package_version} ({system.upper()})."
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"deps.dev returned HTTP {response.status_code} for {package_name} "
            f"{package_version} ({system.upper()})."
        )
    return response.json()


def _extract_nodes_and_edges(current_system: str, deps_payload: Dict) -> tuple[dict, list[Dict]]:
    """Extract normalized package nodes and edges from deps.dev payload."""
    nodes = deps_payload.get("nodes", [])
    edges = deps_payload.get("edges", [])

    index_to_node: dict[int, tuple[str, str, str]] = {}
    package_nodes: dict[tuple[str, str, str], Dict] = {}

    for idx, node in enumerate(nodes):
        version_key = node.get("versionKey", {})
        node_system = str(version_key.get("system") or current_system).lower()
        node_name = version_key.get("name")
        node_version = version_key.get("version")
        if not node_name or not node_version:
            continue

        key = (node_system, node_name, node_version)
        index_to_node[idx] = key
        package_nodes[key] = {
            "ecosystem": node_system,
            "name": node_name,
            "version": node_version,
            "package_name": node_name,
            "package_version": node_version,
            "native_modules": [],
            "root": False,
        }

    normalized_edges: list[Dict] = []
    for edge in edges:
        from_index = edge.get("fromNode")
        to_index = edge.get("toNode")
        if from_index not in index_to_node or to_index not in index_to_node:
            continue

        from_key = index_to_node[from_index]
        to_key = index_to_node[to_index]
        normalized_edges.append(
            {
                "from": {
                    "ecosystem": from_key[0],
                    "name": from_key[1],
                    "version": from_key[2],
                },
                "to": {
                    "ecosystem": to_key[0],
                    "name": to_key[1],
                    "version": to_key[2],
                },
                "requirement": edge.get("requirement", ""),
            }
        )

    return package_nodes, normalized_edges


def _collect_recursive_dependency_data(
    root_system: str,
    root_name: str,
    root_version: str,
    max_packages: int = 180,
) -> tuple[list[Dict], list[Dict], bool]:
    """Recursively collect dependency data across ecosystems using deps.dev."""
    root_key = (root_system, root_name, root_version)
    queue = deque([root_key])
    processed: set[tuple[str, str, str]] = set()

    nodes_map: dict[tuple[str, str, str], Dict] = {}
    edge_keys: set[tuple] = set()
    edges: list[Dict] = []
    truncated = False

    while queue:
        current_key = queue.popleft()
        if current_key in processed:
            continue
        if len(processed) >= max_packages:
            truncated = True
            break

        system, name, version = current_key
        processed.add(current_key)

        try:
            payload = _fetch_dependencies_json(system, name, version)
        except Exception as exc:  # pragma: no cover - network/path dependent
            nodes_map.setdefault(
                current_key,
                {
                    "ecosystem": system,
                    "name": name,
                    "version": version,
                    "package_name": name,
                    "package_version": version,
                    "native_modules": [],
                    "root": False,
                    "error": str(exc),
                },
            )
            continue

        extracted_nodes, extracted_edges = _extract_nodes_and_edges(system, payload)

        for key, node in extracted_nodes.items():
            if key not in nodes_map:
                nodes_map[key] = node

        for edge in extracted_edges:
            from_tuple = (
                edge["from"]["ecosystem"],
                edge["from"]["name"],
                edge["from"]["version"],
            )
            to_tuple = (
                edge["to"]["ecosystem"],
                edge["to"]["name"],
                edge["to"]["version"],
            )
            edge_key = (from_tuple, to_tuple, edge.get("requirement", ""))
            if edge_key not in edge_keys:
                edge_keys.add(edge_key)
                edges.append(edge)

            if to_tuple not in processed:
                queue.append(to_tuple)

    root_node = nodes_map.setdefault(
        root_key,
        {
            "ecosystem": root_system,
            "name": root_name,
            "version": root_version,
            "package_name": root_name,
            "package_version": root_version,
            "native_modules": [],
            "root": True,
        },
    )
    root_node["root"] = True

    return list(nodes_map.values()), edges, truncated


def _build_native_entries(packages: list[Dict]) -> list[Dict]:
    """Build flattened native-module records from package metadata."""
    native_entries = []
    for pkg in packages:
        modules = pkg.get("native_modules") or []
        for module_name in modules:
            native_entries.append(
                {
                    "package_name": pkg.get("name"),
                    "package_version": pkg.get("version"),
                    "package_ecosystem": pkg.get("ecosystem"),
                    "module": module_name,
                }
            )

    return native_entries


def _upload_graph_once(
        conn: Neo4jConnection,
        packages: list[Dict],
        edges: list[Dict],
) -> tuple[int, int, int]:
        """Upload assembled graph snapshot in one atomic Neo4j write query."""
        native_entries = _build_native_entries(packages)

        upload_query = """
        CALL () {
            WITH $packages AS packages
            UNWIND packages AS pkg
            MERGE (p:Package {name: pkg.name, version: pkg.version, ecosystem: pkg.ecosystem})
            SET p.package_name = pkg.package_name,
                    p.package_version = pkg.package_version,
                    p.root = coalesce(pkg.root, false),
                    p.error = pkg.error,
                    p.main_package_size = pkg.main_package_size,
                    p.total_size = pkg.total_size,
                    p.native_modules = coalesce(pkg.native_modules, [])
            RETURN count(*) AS numPackages
        }
        CALL () {
            WITH $edges AS edges
            UNWIND CASE WHEN size(edges) = 0 THEN [NULL] ELSE edges END AS edge
            WITH edge WHERE edge IS NOT NULL
            MATCH (from:Package {
                name: edge.from.name,
                version: edge.from.version,
                ecosystem: edge.from.ecosystem
            })
            MATCH (to:Package {
                name: edge.to.name,
                version: edge.to.version,
                ecosystem: edge.to.ecosystem
            })
            MERGE (from)-[rel:DEPENDS_ON]->(to)
            SET rel.requirement = edge.requirement
            RETURN count(*) AS numRels
        }
        CALL () {
            WITH $native_entries AS native_entries
            UNWIND CASE WHEN size(native_entries) = 0 THEN [NULL] ELSE native_entries END AS item
            WITH item WHERE item IS NOT NULL
            MATCH (p:Package {
                name: item.package_name,
                version: item.package_version,
                ecosystem: item.package_ecosystem
            })
            MERGE (n:Native {package_name: item.package_name, module: item.module})
            SET n.name = item.module,
                    n.ecosystem = 'native',
                    n.is_native_module = true
            MERGE (p)-[r:DEPENDS_ON]->(n)
            SET r.requirement = ''
            RETURN count(DISTINCT n) AS numNativeNodes
        }
        RETURN numPackages, numRels, numNativeNodes
        """

        result = conn.execute_query(
                upload_query,
                {
                        "packages": packages,
                        "edges": edges,
                        "native_entries": native_entries,
                },
        )

        if not result:
                return 0, 0, 0

        row = result[0]
        return (
                row.get("numPackages", 0),
                row.get("numRels", 0),
                row.get("numNativeNodes", 0),
        )


def get_neo4j_connection() -> Neo4jConnection:
    """Get or create Neo4j connection."""
    global _neo4j_connection
    
    if _neo4j_connection is None:
        uri = os.getenv("NEO4J_URI")
        username = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        if not all([uri, username, password]):
            raise ValueError(
                "Neo4j credentials not found. Please set NEO4J_URI, "
                "NEO4J_USERNAME, and NEO4J_PASSWORD environment variables."
            )
        
        _neo4j_connection = Neo4jConnection(uri, username, password, database)
    
    return _neo4j_connection


def construct_dependency_graph_func(
    package_name: str,
    package_version: str,
    package_type: str
) -> str:
    """
    Construct the dependency graph for a given package.
    
    Args:
        package_name: Name of the package
        package_version: Version of the package
        package_type: Type/ecosystem of the package (pypi, npm, cargo, go)
    
    Returns:
        str: Status message indicating success or failure
    """
    conn = get_neo4j_connection()
    normalized_package_type = package_type.lower().strip()
    if normalized_package_type not in _SUPPORTED_SYSTEMS:
        return f"✗ FAILED: Unsupported package type: {package_type}. Supported: pypi, npm, go, cargo"

    # Keep explicit PyPI case guidance to avoid ambiguous/incorrect lookups.
    if normalized_package_type == "pypi" and package_name != package_name.lower():
        return (
            f"✗ FAILED: PyPI package names should be lowercase. Received '{package_name}'.\n"
            f"  Please retry with lowercase package name: '{package_name.lower()}'."
        )
    
    # Check if database already exists
    check_db_exist = (
        """
        MATCH (n:Package)
        WHERE n.name = $name AND n.version = $version AND n.ecosystem = $ecosystem
        RETURN n LIMIT 1
        """
    )
    
    try:
        result = conn.execute_query(
            check_db_exist,
            {
                "name": package_name,
                "version": package_version,
                "ecosystem": normalized_package_type,
            }
        )
        
        if result:
            # Graph exists, but verify it has dependencies
            count_query = """
            MATCH (root:Package {name: $name, version: $version, ecosystem: $ecosystem})
            OPTIONAL MATCH (root)-[:DEPENDS_ON*]->(pkgDep:Package)
            WITH root, count(DISTINCT pkgDep) AS packageDepCount
            OPTIONAL MATCH (root)-[:DEPENDS_ON]->(nativeDep:Native)
            WITH root, packageDepCount, count(DISTINCT nativeDep) AS nativeDepCount
            OPTIONAL MATCH (root)-[r:DEPENDS_ON]->()
            RETURN
              count(DISTINCT root) AS packages,
              count(r) AS rels,
              packageDepCount AS totalPackageDeps,
              nativeDepCount AS totalNativeDeps
            """
            stats = conn.execute_query(
                count_query,
                {
                    "name": package_name,
                    "version": package_version,
                    "ecosystem": normalized_package_type,
                },
            )
            
            if stats and len(stats) > 0:
                stat = stats[0]
                num_rels = stat.get('rels', 0)
                total_package_deps = stat.get('totalPackageDeps', 0)
                total_native_deps = stat.get('totalNativeDeps', 0)
                total_deps = total_package_deps + total_native_deps
                
                if num_rels > 0 or total_deps > 0:
                    return (
                        f"✓ Graph already exists for {package_name} version {package_version}\n"
                        f"  - Found existing dependency graph with {total_package_deps} package dependencies\n"
                        f"  - Found existing dependency graph with {total_native_deps} native dependencies\n"
                        f"  - Found {num_rels} direct DEPENDS_ON relationships from the root\n"
                        f"  - Ready for queries"
                    )
                else:
                    return (
                        f"⚠ Warning: Graph exists for {package_name} version {package_version} but has no dependencies.\n"
                        f"  This may indicate the package has no dependencies or the graph creation previously failed.\n"
                        f"  You can still query basic package information."
                    )
            
            return f"✓ Graph already exists for {package_name} version {package_version}"

        # Fast pre-check for missing deps.dev package/version data.
        # Run only when graph is not already present to avoid extra latency.
        depsdev_url = _depsdev_dependencies_url(
            normalized_package_type,
            package_name,
            package_version,
        )
        try:
            response = requests.get(depsdev_url, timeout=15)
            if response.status_code == 404:
                return (
                    f"✗ FAILED: Dependency data not found in deps.dev for {package_name} "
                    f"version {package_version} ({package_type.upper()}).\n"
                    f"  This is not a Neo4j/APOC issue. The package/version may exist in the registry\n"
                    f"  but is currently unavailable in deps.dev.\n"
                    f"  Please try a different version and retry."
                )
            if response.status_code >= 400:
                return (
                    f"✗ FAILED: deps.dev returned HTTP {response.status_code} for "
                    f"{package_name} version {package_version} ({package_type.upper()}).\n"
                    f"  Please try again later or use a different version."
                )
        except requests.RequestException:
            # Pre-check should not block graph construction; Neo4j APOC may still reach deps.dev.
            pass
        
        # Build recursive dependency data across ecosystems.
        packages, edges, truncated = _collect_recursive_dependency_data(
            root_system=normalized_package_type,
            root_name=package_name,
            root_version=package_version,
        )

        if not packages:
            return (
                f"✗ FAILED: Could not create dependency graph for {package_name} version {package_version}.\n"
                f"  Reason: No dependency records were collected from deps.dev.\n"
                f"  Please verify the package exists and try again."
            )

        # Optional artifact/native-module analysis for the root package.
        artifact_meta = _analyze_root_artifact(
            normalized_package_type,
            package_name,
            package_version,
        )
        for pkg in packages:
            if (
                pkg.get("name") == package_name
                and pkg.get("version") == package_version
                and pkg.get("ecosystem") == normalized_package_type
            ):
                pkg.update(artifact_meta)
                break

        num_packages, num_rels, num_native_nodes = _upload_graph_once(conn, packages, edges)

        if num_packages <= 0:
            return (
                f"✗ FAILED: Could not create dependency graph for {package_name} version {package_version}.\n"
                f"  Reason: No package nodes were written to Neo4j."
            )

        truncated_note = (
            "\n  - Warning: Graph expansion was truncated at safety limit; "
            "results may be partial"
            if truncated
            else ""
        )
        return (
            f"✓ SUCCESS: Dependency graph created for {package_name} version {package_version}!\n"
            f"  - Created/updated {num_packages} package nodes\n"
            f"  - Created/updated {num_rels} dependency relationships\n"
            f"  - Created/updated {num_native_nodes} native-module nodes"
            f"{truncated_note}"
        )
            
    except Exception as e:
        error_msg = str(e)
        return (
            f"✗ ERROR: Failed to construct dependency graph for {package_name} version {package_version}.\n"
            f"  Error: {error_msg}\n"
            f"  Please check your Neo4j connection and try again."
        )


def execute_cypher_query_func(query: str) -> str:
    """
    Execute a Cypher query on the Neo4j database.
    
    Args:
        query: The Cypher query to execute
    
    Returns:
        str: Query results as a formatted string
    """
    conn = get_neo4j_connection()
    
    try:
        result = conn.execute_query(query)
        
        if not result:
            return "Query executed successfully but returned no results."
        
        # Format results
        formatted_results = []
        for record in result:
            formatted_results.append(str(record))
        
        return "\n".join(formatted_results)
        
    except Exception as e:
        return f"Error executing query: {str(e)}"


def get_graph_schema_func() -> str:
    """
    Get the schema of the Neo4j graph database.
    
    Returns:
        str: Database schema information
    """
    conn = get_neo4j_connection()
    
    try:
        # Get node labels
        labels_query = "CALL db.labels()"
        labels_result = conn.execute_query(labels_query)
        labels = [record['label'] for record in labels_result]
        
        # Get relationship types
        rels_query = "CALL db.relationshipTypes()"
        rels_result = conn.execute_query(rels_query)
        rel_types = [record['relationshipType'] for record in rels_result]
        
        # Get property keys
        props_query = "CALL db.propertyKeys()"
        props_result = conn.execute_query(props_query)
        properties = [record['propertyKey'] for record in props_result]
        
        schema_info = f"""
Graph Schema:
- Node Labels: {', '.join(labels) if labels else 'None'}
- Relationship Types: {', '.join(rel_types) if rel_types else 'None'}
- Property Keys: {', '.join(properties) if properties else 'None'}
"""
        return schema_info.strip()
        
    except Exception as e:
        return f"Error retrieving schema: {str(e)}"


def visualize_dependency_graph_func(
    package_name: str,
    package_version: str,
    output_file: str = "dependency_graph.html"
) -> str:
    """
    Visualize the dependency graph.
    
    Args:
        package_name: Name of the package
        package_version: Version of the package
        output_file: Output HTML file path
    
    Returns:
        str: Status message and file path
    """
    conn = get_neo4j_connection()
    
    try:
        query = """
        MATCH (n)
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN n, r, m
        """
        
        result = conn.execute_query(query)
        
        if not result:
            return "No graph data found to visualize."
        
        nt = Network(notebook=False, height="750px", width="100%", directed=True)
        node_set = set()
        
        for record in result:
            # Process node 'n'
            if "n" in record and record["n"] is not None:
                node = record["n"]
                node_name = node.get("name", "Unknown Node")
                node_version = node.get("version", "N/A")
                node_id = f"{node_name}@{node_version}"
                node_title = f"Version: {node_version}"
                node_color = "blue"
                
                if node_id not in node_set:
                    nt.add_node(
                        node_id,
                        label=node_name,
                        title=node_title,
                        color=node_color,
                    )
                    node_set.add(node_id)
            
            # Process relationships
            if (
                "r" in record and record["r"] is not None
                and "m" in record and record["m"] is not None
            ):
                source = record["n"]
                target = record["m"]
                
                source_name = source.get("name", "Unknown Node")
                source_version = source.get("version", "N/A")
                source_id = f"{source_name}@{source_version}"
                
                target_name = target.get("name", "Unknown Node")
                target_version = target.get("version", "N/A")
                target_id = f"{target_name}@{target_version}"
                
                if target_id not in node_set:
                    target_title = f"Version: {target_version}"
                    nt.add_node(
                        target_id,
                        label=target_name,
                        title=target_title,
                        color="blue",
                    )
                    node_set.add(target_id)
                
                nt.add_edge(source_id, target_id)
        
        nt.save_graph(output_file)
        return f"Graph visualization saved to {output_file}"
        
    except Exception as e:
        return f"Error visualizing graph: {str(e)}"
