"""Validate the calling workflow and emit public connection settings."""

import os
from pathlib import Path
import re
import sys

CLIENTS = {
    "saturn30": "Tp211JVNe211CNTRL-kEXytXFUZC21CNTRL",
    "bluesoft9999": "Tp211JVNe211CNTRL-kVRUeu2Wr111CNTRL",
}


def validate_context():
    if os.environ.get("RUNNER_OS") != "Linux":
        raise ValueError("This action requires a Linux runner")
    if os.environ.get("GITHUB_REPOSITORY_OWNER") not in CLIENTS:
        raise ValueError("Repository owner is not allowed")
    if not re.fullmatch(r"refs/tags/v[a-zA-Z0-9_.-]{0,127}", os.environ.get("GITHUB_REF", "")):
        raise ValueError("OIDC authentication requires a v* ref valid as a Docker tag")


def registry_host():
    host = os.environ.get("DOCKER_REGISTRY_HOST", "")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?", host):
        raise ValueError("DOCKER_REGISTRY_HOST must be a hostname without scheme, path or whitespace")
    if ":" in host and not 1 <= int(host.rsplit(":", 1)[1]) <= 65535:
        raise ValueError("DOCKER_REGISTRY_HOST has an invalid port")
    return host


if __name__ == "__main__":
    try:
        validate_context()
        if "--settings" in sys.argv:
            host = registry_host()
            if not os.environ.get("DOCKER_REGISTRY_PASSWORD"):
                raise ValueError("DOCKER_REGISTRY_PASSWORD is missing from Infisical github-ci/prod")
            client = CLIENTS[os.environ["GITHUB_REPOSITORY_OWNER"]]
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(f"registry={host}\nclient-id={client}\naudience=api.tailscale.com/{client}\n")
    except ValueError as error:
        sys.exit(str(error))
