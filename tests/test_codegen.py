import tempfile
import unittest
from pathlib import Path

from vnstudio.codegen import generate_game
from vnstudio.models import load_project

DEMO = Path(__file__).parent.parent / "examples" / "dating_sim_demo"


class TestCodegen(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.bundle = load_project(DEMO)
        self.game_dir = generate_game(self.bundle, Path(self.tmpdir.name))

    def test_generates_expected_files(self):
        for name in ("main.rpy", "characters.rpy", "variables.rpy", "images.rpy"):
            self.assertTrue((self.game_dir / name).exists(), name)
        for scene_id in ("scene_intro", "scene_good", "scene_bad"):
            self.assertTrue((self.game_dir / "scenes" / f"{scene_id}.rpy").exists())

    def test_assets_are_copied(self):
        self.assertTrue((self.game_dir / "images" / "characters" / "alice" / "alice_happy.png").exists())
        self.assertTrue((self.game_dir / "images" / "backgrounds" / "park.png").exists())
        self.assertTrue((self.game_dir / "audio" / "theme.ogg").exists())

    def test_character_definition(self):
        content = (self.game_dir / "characters.rpy").read_text(encoding="utf-8")
        self.assertIn('define alice = Character("Алиса", color="#ff6699")', content)

    def test_variable_default(self):
        content = (self.game_dir / "variables.rpy").read_text(encoding="utf-8")
        self.assertIn("default affection_alice = 0", content)

    def test_linear_dialogue_chain(self):
        content = (self.game_dir / "scenes" / "scene_intro.rpy").read_text(encoding="utf-8")
        self.assertIn("label scene_intro__n1:", content)
        self.assertIn('"Ты приходишь в парк на первое свидание."', content)
        self.assertIn("jump scene_intro__n2", content)
        self.assertIn("show alice happy", content)

    def test_choice_with_stat_effects(self):
        content = (self.game_dir / "scenes" / "scene_intro.rpy").read_text(encoding="utf-8")
        self.assertIn("menu:", content)
        self.assertIn("$ affection_alice += 20", content)
        self.assertIn("$ affection_alice -= 10", content)

    def test_condition_branches_to_other_scenes(self):
        content = (self.game_dir / "scenes" / "scene_intro.rpy").read_text(encoding="utf-8")
        self.assertIn("if affection_alice >= 15:", content)
        self.assertIn("jump scene_good", content)
        self.assertIn("jump scene_bad", content)

    def test_terminal_dialogue_node_returns(self):
        content = (self.game_dir / "scenes" / "scene_good.rpy").read_text(encoding="utf-8")
        self.assertIn("    return", content)

    def test_scene_label_sets_background_and_music(self):
        content = (self.game_dir / "scenes" / "scene_intro.rpy").read_text(encoding="utf-8")
        self.assertIn("label scene_intro:", content)
        self.assertIn("scene bg park", content)
        self.assertIn('play music "audio/theme.ogg"', content)


if __name__ == "__main__":
    unittest.main()
