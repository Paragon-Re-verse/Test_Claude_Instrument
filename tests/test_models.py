import unittest
from pathlib import Path

from vnstudio.models import ProjectValidationError, load_project

DEMO = Path(__file__).parent.parent / "examples" / "dating_sim_demo"


class TestLoadProject(unittest.TestCase):
    def test_loads_demo_project(self):
        bundle = load_project(DEMO)
        self.assertEqual(bundle.meta.name, "Свидание в парке")
        self.assertEqual(bundle.meta.start_scene, "scene_intro")
        self.assertIn("alice", bundle.characters)
        self.assertEqual(bundle.characters["alice"].sprites["happy"], "alice_happy.png")
        self.assertIn("affection_alice", bundle.variables)
        self.assertEqual({"scene_intro", "scene_good", "scene_bad"}, set(bundle.scenes))

    def test_missing_project_json(self, tmp_path=None):
        with self.assertRaises(ProjectValidationError):
            load_project(Path(__file__).parent)  # каталог tests/ без project.json

    def test_unknown_character_reference_is_rejected(self):
        import json
        import tempfile
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copytree(DEMO, tmp / "proj")
            proj = tmp / "proj"
            scene_path = proj / "scenes" / "scene_intro.json"
            data = json.loads(scene_path.read_text(encoding="utf-8"))
            data["nodes"][1]["character"] = "bob"  # персонажа bob не существует
            scene_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaises(ProjectValidationError):
                load_project(proj)

    def test_dangling_node_reference_is_rejected(self):
        import json
        import tempfile
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copytree(DEMO, tmp / "proj")
            proj = tmp / "proj"
            scene_path = proj / "scenes" / "scene_intro.json"
            data = json.loads(scene_path.read_text(encoding="utf-8"))
            data["nodes"][0]["next"] = "does_not_exist"
            scene_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaises(ProjectValidationError):
                load_project(proj)


if __name__ == "__main__":
    unittest.main()
