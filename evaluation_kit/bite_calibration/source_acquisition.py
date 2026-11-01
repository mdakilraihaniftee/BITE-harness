"""Allowlisted, approval-gated and checksum-verified dataset acquisition."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

from jsonschema import validate


APPROVAL_VERSION = "bite.source_acquisition_approval.v1"
ACQUISITION_VERSION = "bite.source_acquisition.v1"
ALLOWLIST = {
    "odinw13:AerialMaritimeDrone_large",
    "odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco",
}
ALLOWED_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".json", ".txt",
    ".yaml", ".yml", ".csv", ".md", ".license",
}
APPROVAL_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "approval_id", "approval_authority", "approved_by",
        "approved_at", "researcher_attestation", "intended_use", "redistribution",
        "sources", "terms_reviewed", "destination_root",
    ],
    "properties": {
        "schema_version": {"const": APPROVAL_VERSION},
        "approval_id": {"type": "string", "minLength": 1},
        "approval_authority": {"const": "researcher"},
        "approved_by": {"type": "string", "minLength": 1},
        "approved_at": {"type": "string", "minLength": 1},
        "researcher_attestation": {"const": True},
        "intended_use": {"const": "internal_non_redistributed_research_calibration"},
        "redistribution": {"const": False},
        "sources": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["source_id", "url", "expected_bytes", "expected_sha256"],
            "properties": {
                "source_id": {"type": "string"}, "url": {"type": "string"},
                "expected_bytes": {"type": "integer", "minimum": 1},
                "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
        }},
        "terms_reviewed": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "destination_root": {"type": "string", "minLength": 1},
    },
}


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source(registry, source_id):
    if source_id not in ALLOWLIST:
        raise ValueError(f"Source is not in the acquisition allowlist: {source_id}")
    matches = [item for item in registry.get("sources", []) if item.get("source_id") == source_id]
    if len(matches) != 1:
        raise ValueError(f"Registered source is missing or duplicated: {source_id}")
    source = matches[0]
    archive = source.get("archive")
    if not isinstance(archive, dict) or not archive.get("url") or not archive.get("sha256"):
        raise ValueError(f"Source lacks an exact registered archive: {source_id}")
    parsed = urlsplit(archive["url"])
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Registered archive URL must be credential-free canonical HTTPS")
    return source


def approval_request(registry, source_ids, destination_root):
    root = str(Path(destination_root).resolve())
    sources = []
    for source_id in source_ids:
        source = _source(registry, source_id)
        archive = source["archive"]
        sources.append({
            "source_id": source_id, "publisher_url": source["publisher_url"],
            "archive_url": archive["url"], "expected_bytes": archive["bytes"],
            "expected_sha256": archive["sha256"],
            "declared_license": source["license_access"].get("local_export_metadata_claim"),
            "destination_root": root, "redistribution_planned": False,
            "intended_use": "internal_non_redistributed_research_calibration",
        })
    return {
        "schema_version": "bite.source_acquisition_approval_request.v1",
        "status": "AWAITING_RESEARCHER_APPROVAL", "sources": sources,
        "destination_root": root,
        "approval_record_template": {
            "schema_version": APPROVAL_VERSION, "approval_id": "<researcher-supplied-id>",
            "approval_authority": "researcher", "approved_by": "<researcher name or stable ID>",
            "approved_at": "<ISO-8601 timestamp>", "researcher_attestation": True,
            "intended_use": "internal_non_redistributed_research_calibration", "redistribution": False,
            "sources": [{"source_id": item["source_id"], "url": item["archive_url"],
                         "expected_bytes": item["expected_bytes"], "expected_sha256": item["expected_sha256"]}
                        for item in sources],
            "terms_reviewed": ["<publisher and license URLs reviewed by researcher>"],
            "destination_root": root,
        },
    }


def validate_approval(approval, source, destination_root):
    validate(approval, APPROVAL_SCHEMA)
    if approval["approved_by"].strip().casefold() in {"assistant", "codex", "openai", "ai"}:
        raise ValueError("An assistant-generated approval is not researcher approval")
    expected_root = str(Path(destination_root).resolve())
    if str(Path(approval["destination_root"]).resolve()) != expected_root:
        raise ValueError("Approval destination does not match the requested destination")
    archive = source["archive"]
    expected = {
        "source_id": source["source_id"], "url": archive["url"],
        "expected_bytes": archive["bytes"], "expected_sha256": archive["sha256"],
    }
    matches = [item for item in approval["sources"] if item.get("source_id") == source["source_id"]]
    if matches != [expected]:
        raise ValueError("Approval does not exactly match the registered source archive")
    return {"valid": True, "approval_id": approval["approval_id"], "approval_sha256": canonical_sha256(approval)}


def acquisition_plan(registry, source_id, destination_root, approval=None):
    source = _source(registry, source_id)
    archive = source["archive"]
    destination_root = Path(destination_root).resolve()
    archive_path = destination_root / "archives" / Path(urlsplit(archive["url"]).path).name
    extraction_path = destination_root / "extracted" / source_id.split(":", 1)[1]
    approval_status = "not_supplied"
    approval_facts = None
    if approval is not None:
        approval_facts = validate_approval(approval, source, destination_root)
        approval_status = "valid"
    return {
        "schema_version": ACQUISITION_VERSION, "mode": "dry_run", "network_requested": False,
        "source_id": source_id, "registered_url": archive["url"],
        "expected_bytes": archive["bytes"], "expected_sha256": archive["sha256"],
        "archive_path": str(archive_path), "extraction_path": str(extraction_path),
        "approval_status": approval_status, "approval": approval_facts,
        "preserve_verified_archive": True, "mirror_fallback": False,
    }


def _zip_member_path(info):
    name = info.filename
    if not name or "\x00" in name or "\\" in name:
        raise ValueError(f"Unsafe ZIP member name: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"ZIP path traversal or absolute path: {name}")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"ZIP drive path is forbidden: {name}")
    return path


def inspect_zip(path, *, max_members=50000, max_expanded_bytes=10 * 1024**3,
                max_member_bytes=2 * 1024**3, max_compression_ratio=1000):
    seen = {}
    total = 0
    members = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > max_members:
            raise ValueError("Archive member count exceeds safety limit")
        for info in infos:
            member = _zip_member_path(info)
            key = member.as_posix().casefold().rstrip("/")
            if key in seen:
                raise ValueError(f"Duplicate or case-conflicting ZIP path: {info.filename}")
            seen[key] = info.filename
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK:
                raise ValueError(f"ZIP symlink is forbidden: {info.filename}")
            if file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError(f"Unexpected ZIP member type: {info.filename}")
            if info.flag_bits & 1:
                raise ValueError(f"Encrypted ZIP members are unsupported: {info.filename}")
            is_directory = info.is_dir()
            if not is_directory and member.suffix.casefold() not in ALLOWED_SUFFIXES:
                raise ValueError(f"Unexpected archive file type: {info.filename}")
            if info.file_size > max_member_bytes:
                raise ValueError(f"Archive member exceeds size limit: {info.filename}")
            if info.file_size and info.compress_size == 0:
                raise ValueError(f"Invalid compressed size for member: {info.filename}")
            if info.compress_size and info.file_size / info.compress_size > max_compression_ratio:
                raise ValueError(f"Archive member compression ratio exceeds safety limit: {info.filename}")
            total += info.file_size
            if total > max_expanded_bytes:
                raise ValueError("Archive expanded size exceeds safety limit")
            members.append({"path": member.as_posix(), "bytes": info.file_size, "directory": is_directory})
    return {"member_count": len(members), "expanded_bytes": total, "members": members}


def safe_extract_zip(archive_path, extraction_path, **limits):
    archive_path = Path(archive_path).resolve()
    extraction_path = Path(extraction_path).resolve()
    if extraction_path.exists():
        raise FileExistsError(f"Extraction destination already exists: {extraction_path}")
    inspection = inspect_zip(archive_path, **limits)
    extraction_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".extract-", dir=extraction_path.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                relative = _zip_member_path(info)
                target = (temporary / Path(*relative.parts)).resolve()
                if temporary != target and temporary not in target.parents:
                    raise ValueError(f"ZIP extraction escaped destination: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                os.chmod(target, 0o600)
        temporary.replace(extraction_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {**inspection, "extraction_path": str(extraction_path)}


def _hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def acquire_source(registry, source_id, destination_root, approval, *, existing="error", opener=urlopen):
    source = _source(registry, source_id)
    approval_facts = validate_approval(approval, source, destination_root)
    plan = acquisition_plan(registry, source_id, destination_root, approval)
    archive_path = Path(plan["archive_path"])
    extraction_path = Path(plan["extraction_path"])
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        if existing != "reuse_verified":
            raise FileExistsError(f"Archive already exists: {archive_path}")
        size, digest = _hash_file(archive_path)
        if size != plan["expected_bytes"] or digest != plan["expected_sha256"]:
            raise ValueError("Existing archive does not match the registered size and SHA-256")
    else:
        temporary = None
        try:
            handle, name = tempfile.mkstemp(prefix=".download-", suffix=".part", dir=archive_path.parent)
            os.close(handle)
            temporary = Path(name)
            digest = hashlib.sha256()
            size = 0
            request = Request(plan["registered_url"], headers={"User-Agent": "OpenVLHarness-BITE-source-acquisition/1"})
            with opener(request, timeout=60) as response, temporary.open("wb") as destination:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > plan["expected_bytes"]:
                        raise ValueError("Downloaded archive exceeds registered byte length")
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if size != plan["expected_bytes"]:
                raise ValueError("Interrupted or incomplete transfer: byte length mismatch")
            if digest.hexdigest() != plan["expected_sha256"]:
                raise ValueError("Downloaded archive SHA-256 mismatch")
            temporary.replace(archive_path)
            os.chmod(archive_path, 0o600)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    extraction = safe_extract_zip(archive_path, extraction_path)
    return {
        **plan, "mode": "executed", "network_requested": True,
        "approval": approval_facts, "verified_bytes": plan["expected_bytes"],
        "verified_sha256": plan["expected_sha256"], "extraction": extraction,
    }
