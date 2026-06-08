#!/usr/bin/env python3
"""
Unit tests for native dependency utility functions.

These tests do not require Neo4j or network access.
"""

import tarfile
import zipfile

from dependencyrag import neo4j_tools
from dependencyrag.neo4j_tools import _build_native_entries, _find_native_modules


def test_find_native_modules_detects_expected_extensions(tmp_path):
    """Detect .c/.cpp/.dylib/.so* files and ignore non-native files."""
    native_files = [
        "mod.c",
        "algo.cpp",
        "libx.dylib",
        "core.so",
        "core.so.1",
        "core.so.2.3",
    ]
    ignored_files = ["README.md", "data.txt", "module.py", "binary.pyd"]

    for name in native_files + ignored_files:
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")

    detected = _find_native_modules(str(tmp_path))

    # _find_native_modules returns sorted basenames
    for name in native_files:
        assert name in detected, f"Expected native file to be detected: {name}"
    for name in ignored_files:
        assert name not in detected, f"Did not expect non-native file: {name}"


def test_build_native_entries_collects_all_packages():
    """Ensure native entries are built across all packages, not just the first."""
    packages = [
        {
            "name": "pkg_a",
            "version": "1.0.0",
            "ecosystem": "pypi",
            "native_modules": ["a.so", "a_helper.c"],
        },
        {
            "name": "pkg_b",
            "version": "2.0.0",
            "ecosystem": "pypi",
            "native_modules": ["b.so"],
        },
        {
            "name": "pkg_c",
            "version": "3.0.0",
            "ecosystem": "pypi",
            "native_modules": [],
        },
    ]

    entries = _build_native_entries(packages)

    assert len(entries) == 3

    expected = {
        ("pkg_a", "1.0.0", "pypi", "a.so"),
        ("pkg_a", "1.0.0", "pypi", "a_helper.c"),
        ("pkg_b", "2.0.0", "pypi", "b.so"),
    }
    actual = {
        (
            e["package_name"],
            e["package_version"],
            e["package_ecosystem"],
            e["module"],
        )
        for e in entries
    }

    assert actual == expected


def test_find_native_modules_detects_npm_node_files(tmp_path):
    """npm native modules should include .node binaries."""
    native_files = ["addon.node", "binding.cc"]
    ignored_files = ["index.js", "package.json"]

    for name in native_files + ignored_files:
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")

    detected = _find_native_modules(str(tmp_path), ecosystem="npm")

    assert "addon.node" in detected
    assert "binding.cc" in detected
    assert "index.js" not in detected
    assert "package.json" not in detected


def test_find_native_modules_detects_go_syso_files(tmp_path):
    """go native modules should include .syso files used by cgo/linking."""
    native_files = ["runtime.syso", "bridge.c"]
    ignored_files = ["main.go", "go.mod"]

    for name in native_files + ignored_files:
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")

    detected = _find_native_modules(str(tmp_path), ecosystem="go")

    assert "runtime.syso" in detected
    assert "bridge.c" in detected
    assert "main.go" not in detected
    assert "go.mod" not in detected


def test_http_get_retries_transient_errors(monkeypatch):
    """_http_get should retry transient status codes and then return success."""

    class _FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    calls = {"count": 0}

    def _fake_get(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            return _FakeResponse(503)
        return _FakeResponse(200)

    monkeypatch.setattr(neo4j_tools.requests, "get", _fake_get)
    monkeypatch.setattr(neo4j_tools.time, "sleep", lambda *_: None)

    response = neo4j_tools._http_get("https://example.test", timeout=5)

    assert response.status_code == 200
    assert calls["count"] == 3


def test_analyze_go_root_artifact_dispatches_to_remote_analyzer(monkeypatch):
    """Go analyzer should dispatch with go ecosystem and .zip artifact suffix."""
    captured = {}

    def _fake_remote(ecosystem, package_name, package_version, artifact_url, artifact_suffix):
        captured["ecosystem"] = ecosystem
        captured["package_name"] = package_name
        captured["package_version"] = package_version
        captured["artifact_url"] = artifact_url
        captured["artifact_suffix"] = artifact_suffix
        return {"native_modules": ["sqlite3-binding.c"], "main_package_size": "1.00 KB", "total_size": "1.00 KB"}

    monkeypatch.setattr(neo4j_tools, "_analyze_remote_root_artifact", _fake_remote)

    result = neo4j_tools._analyze_go_root_artifact("github.com/mattn/go-sqlite3", "v1.14.22")

    assert result["native_modules"] == ["sqlite3-binding.c"]
    assert captured["ecosystem"] == "go"
    assert captured["artifact_suffix"] == ".zip"
    assert "/@v/" in captured["artifact_url"]
    assert "%2F" not in captured["artifact_url"], "Module path separators should not be percent-encoded"


def test_extract_package_artifact_blocks_zip_path_traversal(tmp_path):
    """Zip extraction should reject members that escape the extraction directory."""
    archive = tmp_path / "bad.zip"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    with zipfile.ZipFile(archive, "w") as zip_ref:
        zip_ref.writestr("../evil.txt", "pwn")

    try:
        neo4j_tools._extract_package_artifact(str(archive), str(extract_dir))
        assert False, "Expected ValueError for unsafe zip member path"
    except ValueError as exc:
        assert "Unsafe zip member path" in str(exc)


def test_extract_package_artifact_blocks_tar_path_traversal(tmp_path):
    """Tar extraction should reject members that escape the extraction directory."""
    archive = tmp_path / "bad.tar.gz"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    outside_file = tmp_path / "payload.txt"
    outside_file.write_text("pwn", encoding="utf-8")

    with tarfile.open(archive, "w:gz") as tar:
        tar.add(outside_file, arcname="../evil.txt")

    try:
        neo4j_tools._extract_package_artifact(str(archive), str(extract_dir))
        assert False, "Expected ValueError for unsafe tar member path"
    except ValueError as exc:
        assert "Unsafe tar member path" in str(exc)


def test_enrich_packages_with_artifact_metadata_applies_to_all_nodes(monkeypatch):
    """Artifact/native enrichment should run for every package node."""
    packages = [
        {"ecosystem": "pypi", "name": "a", "version": "1.0.0", "native_modules": []},
        {"ecosystem": "npm", "name": "b", "version": "2.0.0", "native_modules": []},
        {"ecosystem": "cargo", "name": "c", "version": "3.0.0", "native_modules": []},
    ]
    calls = []

    def _fake_analyze(ecosystem, package_name, package_version):
        calls.append((ecosystem, package_name, package_version))
        return {
            "main_package_size": "1.00 KB",
            "total_size": "1.00 KB",
            "native_modules": [f"{package_name}.native"],
        }

    monkeypatch.setattr(neo4j_tools, "_analyze_root_artifact", _fake_analyze)

    neo4j_tools._enrich_packages_with_artifact_metadata(packages)

    assert calls == [
        ("pypi", "a", "1.0.0"),
        ("npm", "b", "2.0.0"),
        ("cargo", "c", "3.0.0"),
    ]
    assert packages[0]["native_modules"] == ["a.native"]
    assert packages[1]["native_modules"] == ["b.native"]
    assert packages[2]["native_modules"] == ["c.native"]
