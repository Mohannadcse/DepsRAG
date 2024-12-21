import os
import requests
import json
import subprocess
import tarfile
import zipfile
import glob
import shutil
import re
from typing import Any, Dict, List, Optional

# Configuration
ecosystem: str = "pypi"
api_base_url: str = "https://api.deps.dev/v3alpha/systems"
workspace_dir: str = "dependency_workspace"

# Ensure the workspace directory exists
if not os.path.exists(workspace_dir):
    os.makedirs(workspace_dir)


def fetch_dependencies(
    system: str, package_name: str, package_version: str
) -> Dict[str, Any]:
    """
    Fetches the dependencies of a given package from the API.
    """
    url = f"{api_base_url}/{system}/packages/{package_name}/versions/{package_version}:dependencies"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(
            f"Failed to fetch data: {response.status_code}, {response.text}"
        )


def download_package(
    package_name: str, package_version: str, download_dir: str
) -> Optional[str]:
    """
    Downloads the specified package from PyPI.
    """
    try:
        with open(os.devnull, "w") as devnull:
            subprocess.run(
                [
                    "pip",
                    "download",
                    f"{package_name}=={package_version}",
                    "--dest",
                    download_dir,
                ],
                check=True,
                stdout=devnull,
                stderr=devnull,
            )
        # files = glob.glob(os.path.join(download_dir, f"*{package_version}*"))
        # Extract major and minor version for matching
        major_minor_version = ".".join(package_version.split(".")[:2])

        # Normalize the package name for the file pattern (replace '-' with '_')
        normalized_package_name = package_name.replace("-", "_")

        # Find matching files
        files = glob.glob(
            os.path.join(
                download_dir, f"{normalized_package_name}-{major_minor_version}*.whl"
            )
        )

        for file in files:
            if file.endswith(".whl") or file.endswith(".tar.gz"):
                return os.path.abspath(file)
    except subprocess.CalledProcessError as e:
        print(f"Error downloading {package_name}=={package_version}: {e}")
    return None


def extract_package(file_path: str, extract_dir: str) -> Optional[str]:
    """
    Extracts the contents of a downloaded package file.
    """
    try:
        if file_path.endswith(".tar.gz"):
            with tarfile.open(file_path, "r:gz") as tar:
                tar.extractall(path=extract_dir)
        elif file_path.endswith(".whl"):
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
        return extract_dir
    except Exception as e:
        print(f"Error extracting {file_path}: {e}")
        return None


def find_native_modules(directory: str) -> List[str]:
    """
    Searches for native modules (e.g., `.so`, `.c`) in the extracted package directory.
    """
    native_extensions = (".c", ".cpp", ".dylib")
    native_files = []

    # Regular expression for Linux shared object files (.so and versioned .so.X.Y)
    so_pattern = re.compile(r".*\.so(\.\d+)*$")

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(native_extensions) or so_pattern.match(file):
                native_files.append(os.path.join(root, file))
    return native_files


def get_file_size(file_path):
    """Return the size of the main package file in a human-readable format."""
    size_bytes = os.path.getsize(file_path)  # Only the main .whl file
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def get_total_size(download_dir):
    """Return the total size of all downloaded .whl and .tar.gz files in the directory."""
    # print(f"Calculating total size of all downloaded files in: {download_dir}")
    total_size = 0
    # Find all .whl and .tar.gz files in the directory
    files = glob.glob(os.path.join(download_dir, "*.whl")) + glob.glob(
        os.path.join(download_dir, "*.tar.gz")
    )

    for file in files:
        total_size += os.path.getsize(file)  # Sum the sizes of all files

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if total_size < 1024:
            return f"{total_size:.2f} {unit}"
        total_size /= 1024
    return f"{total_size:.2f} TB"


def process_dependency(
    system: str, package_name: str, package_version: str
) -> Dict[str, Any]:
    """
    Processes a package: fetch dependencies, download, extract, and analyze.
    """
    print(f"Processing {package_name}=={package_version}...")

    # Download the package
    downloaded_file = download_package(package_name, package_version, workspace_dir)
    if not downloaded_file:
        return {
            "package_name": package_name,
            "package_version": package_version,
            "error": "Download failed",
        }

    # Get the main package size
    main_package_size = get_file_size(downloaded_file)

    # Get the total size of all downloaded files
    total_size = get_total_size(workspace_dir)

    # Extract the package
    extract_dir = os.path.join(workspace_dir, f"{package_name}-{package_version}")
    if not extract_package(downloaded_file, extract_dir):
        return {
            "package_name": package_name,
            "package_version": package_version,
            "error": "Extraction failed",
        }

    # Analyze native modules
    native_modules = find_native_modules(extract_dir)

    # Cleanup extracted files
    shutil.rmtree(workspace_dir)

    # Return the analysis result
    return {
        "package_name": package_name,
        "package_version": package_version,
        "package_ecosystem": system,
        "main_package_size": main_package_size,
        "total_size": total_size,
        "native_modules": native_modules,
    }


def recursive_fetch_dependencies(
    ecosystem: str, package_name: str, package_version: str
) -> List[Dict[str, Any]]:
    """
    Recursively fetches dependencies for a package and performs analysis.

    Args:
        ecosystem (str): The system or platform for package management.
        package_name (str): The name of the package to analyze.
        package_version (str): The version of the package to analyze.

    Returns:
        List[Dict[str, Any]]: A list of processed package dependency results.
    """
    fetched_packages = set()  # To avoid processing the same package multiple times
    all_results = []

    def fetch_recursive(current_package_name: str, current_package_version: str):
        key = f"{current_package_name}|{current_package_version}"
        if key in fetched_packages:
            return
        fetched_packages.add(key)

        # Fetch dependencies
        try:
            data = fetch_dependencies(
                ecosystem, current_package_name, current_package_version
            )
            nodes = data.get("nodes", [])
            edges = data.get("edges", [])  # Edges represent dependencies between nodes

            if not nodes:
                print(
                    f"No nodes found for {current_package_name}=={current_package_version}."
                )
                return

            # Process the current package using `process_dependency`
            package_result = process_dependency(
                ecosystem, current_package_name, current_package_version
            )
            package_result["edges"] = []  # Edges will include detailed dependencies
            package_result["root"] = (
                current_package_name == package_name
            )  # Mark as root if it's the original package
            all_results.append(package_result)

            # Process edges to determine dependencies
            for edge in edges:
                from_index = edge.get("fromNode")
                to_index = edge.get("toNode")
                requirement = edge.get(
                    "requirement", "unknown"
                )  # Fetch requirement, default to "unknown"

                # Ensure the edge indices are valid
                if 0 <= from_index < len(nodes) and 0 <= to_index < len(nodes):
                    from_node = nodes[from_index]
                    to_node = nodes[to_index]

                    # Extract names and versions for the edge
                    from_name = from_node["versionKey"]["name"]
                    from_version = from_node["versionKey"]["version"]
                    to_name = to_node["versionKey"]["name"]
                    to_version = to_node["versionKey"]["version"]

                    # Add the edge to the edges list
                    package_result["edges"].append(
                        {
                            "from": {"name": from_name, "version": from_version},
                            "to": {"name": to_name, "version": to_version},
                            "requirement": requirement,
                        }
                    )

                    # Recurse for the "to" node
                    fetch_recursive(to_name, to_version)
        except Exception as e:
            print(
                f"Error fetching dependencies for {current_package_name}=={current_package_version}: {e}"
            )

    fetch_recursive(package_name, package_version)
    return all_results


def save_to_json(data: List[Dict[str, Any]], file_path: str) -> None:
    """
    Saves dependency data to a JSON file.
    """
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)


'''
def upload_to_pasters(file_path: str) -> str | None:
    """
    Uploads a file to paste.rs for anonymous hosting and returns the public URL.

    This function checks if the specified file exists and is readable, then
    uploads it to paste.rs. If successful, it returns the raw URL to the uploaded file.
    In case of errors, it returns None.

    Args:
        file_path (str): The path to the file to upload.

    Returns:
        str | None: The public URL of the hosted file if successful, or None if an error occurs.
    """
    # Check if the file exists
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        return None

    # Check if the file is readable
    try:
        with open(file_path, "rb") as file:
            file_content = file.read()
            if not file_content:
                print(f"Error: File '{file_path}' is empty.")
                return None
    except Exception as e:
        print(f"Error reading file '{file_path}': {e}")
        return None

    # Upload the file to paste.rs
    try:
        with open(file_path, "rb") as file:
            response = requests.post(
                "https://paste.rs", data=file, timeout=30
            )  # 30-second timeout
        if response.status_code in {
            200,
            201,
        }:  # Accept 200 and 201 as successful responses
            raw_url = response.text.strip()
            print(f"File uploaded successfully! Raw URL: {raw_url}")
            return raw_url
        else:
            print(f"Failed to upload file. Status code: {response.status_code}")
            print(response.text)
            return None
    except requests.RequestException as e:
        print(f"Error uploading file: {e}")
        return None
'''
