import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("ci_context", Path(__file__).parents[1] / "scripts/ci_context.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContextTests(unittest.TestCase):
    def test_accepts_host_with_optional_port_and_rejects_urls(self):
        for host in ["registry.example", "registry.example:443"]:
            with patch.dict(os.environ, {"DOCKER_REGISTRY_HOST": host}):
                self.assertEqual(module.registry_host(), host)
        for host in ["", "https://registry.example", "registry.example/path", "user@registry.example", "registry.example\nEVIL=yes", "registry.example:65536"]:
            with self.subTest(host=host), patch.dict(os.environ, {"DOCKER_REGISTRY_HOST": host}), self.assertRaises(ValueError):
                module.registry_host()

    def test_requires_approved_owner_and_release_ref(self):
        good = {"RUNNER_OS": "Linux", "GITHUB_REPOSITORY_OWNER": "saturn30", "GITHUB_REF": "refs/tags/v1.2.3"}
        with patch.dict(os.environ, good):
            module.validate_context()
        for changes in [{"GITHUB_REPOSITORY_OWNER": "stranger"}, {"GITHUB_REF": "refs/heads/main"}]:
            with patch.dict(os.environ, good | changes), self.assertRaises(ValueError):
                module.validate_context()
