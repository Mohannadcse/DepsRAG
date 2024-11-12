import os
import subprocess
import tarfile
import zipfile
import glob
import shutil
import re
import json
import fnmatch
import time


def download_package(package_name, package_version, download_dir):
    """Download the specified package from PyPI into a specific directory, suppressing output, with progress messages."""
    print(f"Starting download for package: {package_name}=={package_version}")

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
                stdout=devnull,  # Redirect stdout to null
                stderr=devnull,  # Redirect stderr to null
            )
        print(f"Download completed for package: {package_name}=={package_version}")
    except subprocess.CalledProcessError as e:
        print(f"Error downloading package: {e}")
        return None

    # Find the downloaded file (either .tar.gz or .whl) with looser matching on the version
    files = glob.glob(os.path.join(download_dir, f"*{package_version}*"))

    # Check for downloaded file and print progress
    if not files:
        print(
            f"Downloaded file not found for package: {package_name}=={package_version}"
        )
        return None

    print(f"Found downloaded file(s) for {package_name}=={package_version}: {files}")

    # Try to find a matching .whl or .tar.gz file
    for file in files:
        if file.endswith(".whl") or file.endswith(".tar.gz"):
            print(f"Selected file for extraction: {file}")
            # Return the full path of the matching file
            return os.path.abspath(file)

    print(
        f"No suitable .whl or .tar.gz file found for {package_name}=={package_version}"
    )
    return None


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
    print(f"Calculating total size of all downloaded files in: {download_dir}")
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


def extract_package(file_path, extract_dir):
    """Extract the package contents into the specified directory."""
    print(f"Extracting package: {file_path} to {extract_dir}")

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return None

    # Double-check the file permissions and existence
    try:
        with open(file_path, "rb") as f:
            pass
    except Exception as e:
        print(f"Error reading file: {e}")
        return None

    # Small delay to ensure the filesystem has finished writing the file
    time.sleep(1)

    # Create extract_dir only if needed, do not remove it before checking
    if not os.path.exists(extract_dir):
        os.makedirs(extract_dir)

    if file_path.endswith(".tar.gz"):
        with tarfile.open(file_path, "r:gz") as tar:
            tar.extractall(path=extract_dir)
        print(f"Extraction completed for .tar.gz package: {file_path}")
    elif file_path.endswith(".whl"):
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        print(f"Extraction completed for .whl package: {file_path}")
    else:
        print("Unsupported file format.")
        return None

    return extract_dir


def find_native_modules(directory):
    """Find and return a list of native C library files in the extracted package."""
    print(f"Searching for native modules in: {directory}")
    native_extensions = (".c", ".cpp", ".dylib")
    native_files = []

    # Regular expression to match shared object files, even if they have suffixes
    so_pattern = re.compile(r".*\.so(\.\d+)*$")

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(native_extensions) or so_pattern.match(file):
                native_files.append(os.path.join(root, file))

    if native_files:
        print(f"Native modules found: {native_files}")
    else:
        print("No native modules found.")

    return native_files


def save_results_to_json(result, output_file):
    """Save the result to a JSON file, appending if the file already exists."""
    print(f"Saving results to: {output_file}")
    if os.path.exists(output_file):
        # Read the existing data
        with open(output_file, "r") as json_file:
            data = json.load(json_file)
    else:
        # Create a new list if the file doesn't exist
        data = []

    # Append the new result
    data.append(result)

    # Write the updated data back to the file
    with open(output_file, "w") as json_file:
        json.dump(data, json_file, indent=4)
    print(f"Results saved successfully to: {output_file}")


def clean_up_files(directory):
    """Clean up the downloaded and extracted files by removing the workspace directory."""
    print(f"Cleaning up workspace directory: {directory}")
    if os.path.exists(directory):
        shutil.rmtree(directory)


def list_downloaded_files(download_dir):
    """Return a list of downloaded files before the new download begins."""
    return set(glob.glob(os.path.join(download_dir, "*")))


def main():
    package_name = input("Enter the package name: ")
    package_version = input("Enter the package version: ")

    # Specify a directory for both downloads and extraction
    workspace_dir = "package_workspace"

    # Ensure the workspace directory exists
    if not os.path.exists(workspace_dir):
        os.makedirs(workspace_dir)

    # List all files before download
    print(f"Listing files before download in: {workspace_dir}")
    files_before_download = list_downloaded_files(workspace_dir)

    # Step 1: Download the package
    downloaded_file = download_package(package_name, package_version, workspace_dir)
    if not downloaded_file:
        return

    # Get the size of the main package
    print(f"Calculating size for main package: {downloaded_file}")
    main_package_size = get_file_size(downloaded_file)

    # Get the total size of all downloaded files
    total_size = get_total_size(workspace_dir)

    # Step 2: Extract the package
    extracted_dir = extract_package(downloaded_file, workspace_dir)
    if not extracted_dir:
        return

    # Step 3: Find all native C modules
    native_files = find_native_modules(extracted_dir)

    # Create JSON object with results
    result = {
        "package_name": package_name,
        "package_version": package_version,
        "main_package_size": main_package_size,
        "total_size": total_size,
        "native_modules": native_files,
    }

    # Save results to a JSON file
    output_file = "package_analysis_results.json"
    save_results_to_json(result, output_file)

    # Clean up the workspace directory
    clean_up_files(workspace_dir)


if __name__ == "__main__":
    main()
