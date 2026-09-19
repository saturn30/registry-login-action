import copy
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

spec = importlib.util.spec_from_file_location("update_images", Path(__file__).parents[1] / "update-manifests/update_images.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UpdateImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "manifests/app"
        self.folder.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.image = "registry.example:5000/team/app"
        self.deploy = {
            "apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "app"},
            "spec": {"template": {"spec": {
                "containers": [{"name": "app", "image": self.image + ":v1", "env": [{"name": "KEEP", "value": "yes"}]},
                               {"name": "sidecar", "image": "redis:7"}],
                "initContainers": [{"name": "init", "image": self.image + "@sha256:123"}],
                "imagePullSecrets": [{"name": "keep-me"}],
            }}},
        }
        self.job = copy.deepcopy(self.deploy)
        self.job.update(apiVersion="batch/v1", kind="Job")
        self.job["metadata"]["name"] = "migration"
        self.write("workloads.yaml", [self.deploy, self.job])
        self.write("service.yaml", [{"kind": "Service", "metadata": {"name": "app"}}])

    def write(self, filename, docs):
        p = self.folder / filename
        p.write_text(yaml.safe_dump_all(docs, sort_keys=False))
        subprocess.run(["git", "add", "--", str(p)], cwd=self.root, check=True)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.folder.iterdir()}

    def test_updates_deployment_job_and_init_containers_preserving_other_fields(self):
        before = self.snapshot()
        changed = module.update_manifests(self.root, "manifests/app", [self.image], "v2")
        self.assertEqual([p.name for p in changed], ["workloads.yaml"])
        expected = [copy.deepcopy(self.deploy), copy.deepcopy(self.job)]
        for doc in expected:
            pod = doc["spec"]["template"]["spec"]
            pod["containers"][0]["image"] = self.image + ":v2"
            pod["initContainers"][0]["image"] = self.image + ":v2"
        self.assertEqual(list(yaml.safe_load_all((self.folder / "workloads.yaml").read_text())), expected)
        self.assertEqual(self.snapshot()["service.yaml"], before["service.yaml"])
        after = self.snapshot()
        self.assertEqual(module.update_manifests(self.root, "manifests/app", [self.image], "v2"), [])
        self.assertEqual(self.snapshot(), after)

    def test_missing_image_or_invalid_yaml_prevents_partial_writes(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "not found"):
            module.update_manifests(self.root, "manifests/app", [self.image, "other.example/no-match"], "v2")
        self.assertEqual(self.snapshot(), before)
        p = self.folder / "zzz.yaml"
        p.write_text("[invalid")
        subprocess.run(["git", "add", str(p)], cwd=self.root, check=True)
        before = self.snapshot()
        with self.assertRaises(yaml.YAMLError):
            module.update_manifests(self.root, "manifests/app", [self.image], "v2")
        self.assertEqual(self.snapshot(), before)

    def test_rejects_paths_tags_and_tagged_image_inputs(self):
        before = self.snapshot()
        for path, images, tag in [("../escape", [self.image], "v2"), (".", [self.image], "v2"),
                                   ("manifests/app", [self.image], "v2;echo"),
                                   ("manifests/app", [self.image + ":v2"], "v2")]:
            with self.subTest(path=path, images=images, tag=tag), self.assertRaises(ValueError):
                module.update_manifests(self.root, path, images, tag)
        self.assertEqual(self.snapshot(), before)

    def test_updates_cronjob_and_rejects_symlink(self):
        cron = {"kind": "CronJob", "spec": {"jobTemplate": {"spec": copy.deepcopy(self.job["spec"])}}}
        self.write("cron.yaml", [cron])
        module.update_manifests(self.root, "manifests/app", [self.image], "v2")
        doc = yaml.safe_load((self.folder / "cron.yaml").read_text())
        self.assertEqual(doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["image"], self.image + ":v2")
        link = self.folder / "link.yaml"
        link.symlink_to(self.folder / "workloads.yaml")
        subprocess.run(["git", "add", str(link)], cwd=self.root, check=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            module.update_manifests(self.root, "manifests/app", [self.image], "v3")


if __name__ == "__main__":
    unittest.main()
