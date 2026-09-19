"""Update exact image names in tracked Kubernetes workloads, validating before writing."""

import argparse
import os
from pathlib import Path
import re
import subprocess

import yaml


def image_name(reference: str) -> str:
    name = reference.split("@", 1)[0]
    if ":" in name.rsplit("/", 1)[-1]:
        name = name.rsplit(":", 1)[0]
    return name


def pod_spec(document):
    if not isinstance(document, dict):
        return None
    kind = document.get("kind")
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        return document.get("spec", {}).get("template", {}).get("spec", {})
    if kind == "CronJob":
        return document.get("spec", {}).get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec", {})
    return None


def update_manifests(root: Path, manifest_path: str, images: list[str], tag: str) -> list[Path]:
    root = root.resolve()
    relative = Path(manifest_path)
    directory = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not directory.is_relative_to(root) or directory == root:
        raise ValueError("manifest-path must be a directory inside the repository")
    if not directory.is_dir():
        raise ValueError("Manifest directory does not exist")
    if not re.fullmatch(r"v[a-zA-Z0-9_.-]{0,127}", tag):
        raise ValueError("Expected a v* release tag valid as a Docker tag")
    if not images or len(images) != len(set(images)):
        raise ValueError("Provide distinct image names, one per line")
    for name in images:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*(?::[0-9]+)?/[a-z0-9][a-z0-9._/-]*", name) or any(p in {"", ".", ".."} for p in name.split("/")):
            raise ValueError("images must contain fully qualified image names without tags or digests")

    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", manifest_path], cwd=root
    ).decode().split("\0")
    matched = set()
    updates = []
    for filename in tracked:
        path = root / filename
        if path.suffix not in {".yaml", ".yml"}:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise ValueError("Manifest files must stay inside manifest-path without symlinks")
        documents = list(yaml.safe_load_all(path.read_text()))
        changed = False
        for document in documents:
            spec = pod_spec(document)
            if spec is None:
                continue
            for container in spec.get("containers", []) + spec.get("initContainers", []):
                current = container.get("image", "")
                name = image_name(current)
                if name in images:
                    matched.add(name)
                    new = f"{name}:{tag}"
                    if current != new:
                        container["image"] = new
                        changed = True
        if changed:
            content = yaml.safe_dump_all(documents, sort_keys=False, allow_unicode=True)
            updates.append((path, content))

    if missing := set(images) - matched:
        raise ValueError("Some requested images were not found in the manifest directory")
    # Missing targets or invalid YAML must fail before any file is changed.
    for path, content in updates:
        path.write_text(content)
    return [path for path, _ in updates]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("manifest_path")
    parser.add_argument("tag")
    args = parser.parse_args()
    images = [line.strip() for line in os.environ.get("IMAGES", "").splitlines() if line.strip()]
    changed = update_manifests(args.repo_root, args.manifest_path, images, args.tag)
    if changed:
        subprocess.run(["git", "add", "--", *map(str, changed)], cwd=args.repo_root, check=True)
    print(f"Updated {len(changed)} manifest file(s)")
