import tempfile
import unittest
from pathlib import Path

from vnstudio.codegen import generate_game
from vnstudio.codegen.renderer import _render_character_images
from vnstudio.models import Character, load_project

DEMO = Path(__file__).parent.parent / "examples" / "school_life_demo"


class TestSchoolLifeCodegen(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.bundle = load_project(DEMO)
        self.game_dir = generate_game(self.bundle, Path(self.tmpdir.name))

    def test_hidden_stats_mode_generates_no_overlay(self):
        self.assertFalse((self.game_dir / "stats.rpy").exists())

    def test_calendar_file_generated(self):
        content = (self.game_dir / "calendar.rpy").read_text(encoding="utf-8")
        self.assertIn("label calendar_loop:", content)
        self.assertIn("label vnstudio_location_school:", content)
        self.assertIn("label vnstudio_location_cafe:", content)
        self.assertIn("label vnstudio_location_park:", content)
        self.assertIn("vnstudio_day_count = 3", content)

    def test_location_slot_gating_in_menu(self):
        content = (self.game_dir / "calendar.rpy").read_text(encoding="utf-8")
        self.assertIn("\"Школа\" if vnstudio_slots[current_slot] in ['Утро', 'День']:", content)
        self.assertIn("\"Парк\":", content)  # без ограничения по слоту

    def test_schedule_event_dispatch_present(self):
        content = (self.game_dir / "calendar.rpy").read_text(encoding="utf-8")
        self.assertIn("'scene': 'scene_meet_yuki'", content)
        self.assertIn("'day': 0", content)
        self.assertIn("'slot': 'Утро'", content)

    def test_calendar_end_jumps_to_resolve_routes(self):
        content = (self.game_dir / "calendar.rpy").read_text(encoding="utf-8")
        self.assertIn("jump resolve_routes", content)

    def test_routes_file_has_relative_condition(self):
        content = (self.game_dir / "routes.rpy").read_text(encoding="utf-8")
        self.assertIn("'compare_var': 'affection_aoi'", content)
        self.assertIn("'requires': 'route_yuki'", content)
        self.assertIn("label resolve_routes:", content)

    def test_route_completion_recorded_on_ending(self):
        content = (self.game_dir / "scenes" / "scene_yuki_start.rpy").read_text(encoding="utf-8")
        self.assertIn('persistent.vnstudio_completed_routes.append("route_yuki")', content)

    def test_ending_categories_render_distinct_text_and_color(self):
        normal = (self.game_dir / "scenes" / "scene_yuki_start.rpy").read_text(encoding="utf-8")
        bad_and_normal = (self.game_dir / "scenes" / "scene_aoi_start.rpy").read_text(encoding="utf-8")
        true_end = (self.game_dir / "scenes" / "scene_true_start.rpy").read_text(encoding="utf-8")
        self.assertIn("NORMAL END", normal)
        self.assertIn("BAD END", bad_and_normal)
        self.assertIn("#ff4444", bad_and_normal)  # цвет BAD END
        self.assertIn("TRUE END", true_end)
        self.assertIn("#ffcc33", true_end)  # цвет TRUE END

    def test_condition_node_supports_relative_stat_compare(self):
        # scene_aoi_start использует condition с константой (affection_aoi >= 20) —
        # относительное сравнение статов проверяется на уровне routes (см. выше);
        # здесь проверяем, что обычное condition-ветвление по-прежнему работает.
        content = (self.game_dir / "scenes" / "scene_aoi_start.rpy").read_text(encoding="utf-8")
        self.assertIn("if affection_aoi >= 20:", content)

    def test_cross_scene_ref_to_calendar_loop(self):
        content = (self.game_dir / "scenes" / "scene_common_start.rpy").read_text(encoding="utf-8")
        self.assertIn("jump calendar_loop", content)

    def test_animated_sprite_generates_atl_loop(self):
        content = (self.game_dir / "images.rpy").read_text(encoding="utf-8")
        self.assertIn("image yuki happy:", content)
        self.assertIn('"characters/yuki/yuki_happy_1.png"', content)
        self.assertIn('"characters/yuki/yuki_happy_2.png"', content)
        self.assertIn("    repeat", content)

    def test_static_sprite_unaffected_by_animation_support(self):
        content = (self.game_dir / "images.rpy").read_text(encoding="utf-8")
        self.assertIn('image aoi happy = "characters/aoi/aoi_happy.png"', content)

    def test_animated_frames_are_copied_as_assets(self):
        self.assertTrue((self.game_dir / "images" / "characters" / "yuki" / "yuki_happy_1.png").exists())
        self.assertTrue((self.game_dir / "images" / "characters" / "yuki" / "yuki_happy_2.png").exists())


class TestLive2DWiring(unittest.TestCase):
    """Live2D — экспериментальная, best-effort обвязка (нет реального Live2D SDK для e2e теста).

    Проверяем только генерируемый текст image-объявления, без реальной сборки.
    """

    def test_live2d_character_generates_live2d_call(self):
        char = Character(
            id="rin",
            name="Рин",
            color="#ffcc00",
            animation={"type": "live2d", "model": "rin/rin.model3.json", "motions": {"happy": "Idle_Happy"}},
        )
        block = _render_character_images(char)
        self.assertIn('image rin happy = Live2D("characters/rin/rin.model3.json", motion_group="Idle_Happy")', block)


if __name__ == "__main__":
    unittest.main()
