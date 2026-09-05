import json
import shutil
import tempfile
import unittest
from pathlib import Path

from vnstudio.models import ProjectValidationError, load_project

DEMO = Path(__file__).parent.parent / "examples" / "school_life_demo"


class TestSchoolLifeDemo(unittest.TestCase):
    def test_loads_full_bundle(self):
        bundle = load_project(DEMO)
        self.assertEqual(bundle.meta.stats_display, "hidden")
        self.assertIn("affection_yuki", bundle.variables)
        self.assertFalse(bundle.variables["affection_yuki"].visible)
        self.assertIsNotNone(bundle.calendar)
        self.assertEqual(bundle.calendar.day_count, 3)
        self.assertEqual({"school", "cafe", "park"}, set(bundle.locations))
        self.assertEqual({"ev_yuki", "ev_aoi", "ev_walk"}, set(bundle.schedule))
        self.assertEqual({"route_yuki", "route_aoi", "route_true"}, set(bundle.routes))

    def test_route_condition_uses_relative_compare(self):
        bundle = load_project(DEMO)
        cond = bundle.routes["route_yuki"].condition
        self.assertEqual(cond["compare_var"], "affection_aoi")
        self.assertIsNone(cond["value"])

    def test_route_gating_via_requires(self):
        bundle = load_project(DEMO)
        self.assertEqual(bundle.routes["route_true"].requires, "route_yuki")

    def test_ending_categories_present(self):
        bundle = load_project(DEMO)
        from vnstudio.models import EndingNode
        endings = [n for s in bundle.scenes.values() for n in s.nodes.values() if isinstance(n, EndingNode)]
        categories = {e.category for e in endings}
        self.assertEqual(categories, {"normal", "bad", "true"})


def _copy_demo(tmp: Path) -> Path:
    proj = tmp / "proj"
    shutil.copytree(DEMO, proj)
    return proj


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


class TestRouteValidation(unittest.TestCase):
    def test_route_requires_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            routes_path = proj / "routes" / "routes.json"
            routes = json.loads(routes_path.read_text(encoding="utf-8"))
            # Замыкаем requires в цикл: route_yuki <- route_true <- route_yuki
            for r in routes:
                if r["id"] == "route_yuki":
                    r["requires"] = "route_true"
            _write_json(routes_path, routes)
            with self.assertRaises(ProjectValidationError):
                load_project(proj)

    def test_route_condition_unknown_compare_var_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            routes_path = proj / "routes" / "routes.json"
            routes = json.loads(routes_path.read_text(encoding="utf-8"))
            routes[0]["condition"]["compare_var"] = "does_not_exist"
            _write_json(routes_path, routes)
            with self.assertRaises(ProjectValidationError):
                load_project(proj)

    def test_ending_referencing_unknown_route_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            scene_path = proj / "scenes" / "scene_yuki_start.json"
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
            scene["nodes"][-1]["route"] = "no_such_route"
            _write_json(scene_path, scene)
            with self.assertRaises(ProjectValidationError):
                load_project(proj)

    def test_ending_unknown_category_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            scene_path = proj / "scenes" / "scene_yuki_start.json"
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
            scene["nodes"][-1]["category"] = "secret"
            _write_json(scene_path, scene)
            with self.assertRaises(ProjectValidationError):
                load_project(proj)


class TestCalendarValidation(unittest.TestCase):
    def test_resolve_routes_ref_without_routes_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            shutil.rmtree(proj / "routes")
            with self.assertRaises(ProjectValidationError):
                load_project(proj)

    def test_calendar_loop_ref_without_calendar_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            shutil.rmtree(proj / "calendar")
            with self.assertRaises(ProjectValidationError):
                load_project(proj)

    def test_location_available_slots_unknown_slot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            loc_path = proj / "locations" / "locations.json"
            locs = json.loads(loc_path.read_text(encoding="utf-8"))
            locs[0]["available_slots"] = ["Полночь"]
            _write_json(loc_path, locs)
            with self.assertRaises(ProjectValidationError):
                load_project(proj)

    def test_schedule_event_unknown_location_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            ev_path = proj / "schedule" / "events.json"
            events = json.loads(ev_path.read_text(encoding="utf-8"))
            events[0]["location"] = "moon_base"
            _write_json(ev_path, events)
            with self.assertRaises(ProjectValidationError):
                load_project(proj)


class TestProjectMetaValidation(unittest.TestCase):
    def test_invalid_stats_display_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _copy_demo(Path(tmp))
            meta_path = proj / "project.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["stats_display"] = "sparkly"
            _write_json(meta_path, meta)
            with self.assertRaises(ProjectValidationError):
                load_project(proj)


if __name__ == "__main__":
    unittest.main()
