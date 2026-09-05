"""Codegen-слой: JSON-модель проекта -> валидные .rpy файлы + раскладка ассетов.

Ren'Py-специфичные детали (метки, menu:, if/else, image-объявления,
persistent-хранилище для route-gating, встроенный питон для календаря)
изолированы здесь, чтобы модель проекта (vnstudio.models) и GUI поверх
неё ничего не знали про синтаксис Ren'Py.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from vnstudio.models import (
    Character,
    ChoiceNode,
    ConditionNode,
    DialogueNode,
    EndingNode,
    Location,
    ProjectBundle,
    RouteDef,
    Scene,
    ScheduleEvent,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

_ENDING_DISPLAY = {
    "bad": {"text": "BAD END", "color": "#ff4444"},
    "normal": {"text": "NORMAL END", "color": "#ffffff"},
    "true": {"text": "TRUE END", "color": "#ffcc33"},
}


def _render_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)
    return f'"{value}"'


def _jump_stmt(ref: str | None, scene_id: str) -> str:
    if ref is None:
        return "return"
    if isinstance(ref, str) and ref.startswith("@"):
        return f"jump {ref[1:]}"
    return f"jump {node_label(scene_id, ref)}"


def node_label(scene_id: str, node_id: str) -> str:
    return f"{scene_id}__{node_id}"


def _compile_dialogue(node: DialogueNode, scene: Scene) -> dict:
    show_stmt = None
    if node.character and node.emotion:
        show_stmt = f"{node.character} {node.emotion}"
    return {
        "kind": "dialogue",
        "label": node_label(scene.id, node.id),
        "character": node.character,
        "text": node.text,
        "show_stmt": show_stmt,
        "next_stmt": _jump_stmt(node.next, scene.id),
    }


def _compile_choice(node: ChoiceNode, scene: Scene) -> dict:
    options = []
    for opt in node.options:
        effect_stmts = [f"{eff['var']} {eff['op']} {_render_literal(eff['value'])}" for eff in opt.effects]
        options.append({
            "text": opt.text,
            "effect_stmts": effect_stmts,
            "next_stmt": _jump_stmt(opt.next, scene.id),
        })
    return {
        "kind": "choice",
        "label": node_label(scene.id, node.id),
        "prompt": node.prompt,
        "options": options,
    }


def _condition_expr(var: str, op: str, value: Any, compare_var: str | None) -> str:
    rhs = compare_var if compare_var else _render_literal(value)
    return f"{var} {op} {rhs}"


def _compile_condition(node: ConditionNode, scene: Scene) -> dict:
    return {
        "kind": "condition",
        "label": node_label(scene.id, node.id),
        "expr": _condition_expr(node.var, node.op, node.value, node.compare_var),
        "then_stmt": _jump_stmt(node.then, scene.id),
        "else_stmt": _jump_stmt(node.else_, scene.id),
    }


def _compile_ending(node: EndingNode, scene: Scene) -> dict:
    display = _ENDING_DISPLAY[node.category]
    return {
        "kind": "ending",
        "label": node_label(scene.id, node.id),
        "route": node.route,
        "text": node.title or display["text"],
        "color": display["color"],
    }


def _compile_scene(scene: Scene, audio: dict) -> dict:
    compiled_nodes = []
    for node in scene.nodes.values():
        if isinstance(node, DialogueNode):
            compiled_nodes.append(_compile_dialogue(node, scene))
        elif isinstance(node, ChoiceNode):
            compiled_nodes.append(_compile_choice(node, scene))
        elif isinstance(node, ConditionNode):
            compiled_nodes.append(_compile_condition(node, scene))
        elif isinstance(node, EndingNode):
            compiled_nodes.append(_compile_ending(node, scene))
    music_file = f"audio/{audio[scene.music].file}" if scene.music else None
    return {
        "id": scene.id,
        "background": scene.background,
        "music": music_file,
        "start_label": node_label(scene.id, scene.start),
        "nodes": compiled_nodes,
    }


def _render_character_images(char: Character) -> str:
    """Ren'Py image-объявления для одного персонажа.

    Три режима, в зависимости от того, что предоставил автор:
      - статичный портрет (обычный case)               -> `image X = "путь.png"`
      - покадровая анимация (авто-detected _1/_2/...)   -> ATL-цикл show/repeat
      - Live2D (animation.type == "live2d", best-effort) -> Live2D(...)
    """
    lines: list[str] = []
    is_live2d = char.is_live2d
    animation = char.animation or {}
    motions: dict[str, str] = animation.get("motions", {}) if is_live2d else {}
    model_rel = animation.get("model") if is_live2d else None
    fps = animation.get("fps", 2) if animation else 2
    frame_delay = round(1 / fps, 4) if fps else 0.5

    emotions = sorted(set(char.sprites) | set(char.animated_sprites) | set(motions))
    for emotion in emotions:
        image_name = f"{char.id} {emotion}"
        if is_live2d:
            motion = motions.get(emotion)
            motion_kwarg = f', motion_group="{motion}"' if motion else ""
            lines.append(f'image {image_name} = Live2D("characters/{model_rel}"{motion_kwarg})')
        elif emotion in char.animated_sprites:
            frames = char.animated_sprites[emotion]
            lines.append(f"image {image_name}:")
            for frame_file in frames:
                lines.append(f'    "characters/{char.id}/{frame_file}"')
                lines.append(f"    {frame_delay}")
            lines.append("    repeat")
        else:
            file = char.sprites[emotion]
            lines.append(f'image {image_name} = "characters/{char.id}/{file}"')
    return "\n".join(lines)


def _routes_literal(routes: dict[str, RouteDef]) -> str:
    data = [
        {"id": r.id, "requires": r.requires, "condition": r.condition, "start_scene": r.start_scene}
        for r in routes.values()
    ]
    return repr(data)


def _schedule_literal(schedule: dict[str, ScheduleEvent]) -> str:
    data = [
        {
            "id": e.id,
            "location": e.location,
            "scene": e.scene,
            "day": e.day,
            "slot": e.slot,
            "once": e.once,
            "priority": e.priority,
            "condition": e.condition,
        }
        for e in schedule.values()
    ]
    return repr(data)


def _compile_location(loc: Location) -> dict:
    return {
        "id": loc.id,
        "name": loc.name,
        "background": loc.background,
        "slot_filter": repr(loc.available_slots) if loc.available_slots is not None else None,
    }


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def generate_game(bundle: ProjectBundle, output_dir: Path) -> Path:
    """Раскладывает bundle в стандартную структуру Ren'Py-проекта под output_dir.

    Возвращает путь к output_dir/game — это и есть каталог, который затем
    передаётся headless-сборке Ren'Py (см. vnstudio.build).
    """
    output_dir = Path(output_dir)
    game_dir = output_dir / "game"
    script_dir = game_dir  # .rpy файлы кладём прямо в game/, как это делает Ren'Py по умолчанию

    game_dir.mkdir(parents=True, exist_ok=True)

    env = _make_env()

    characters = list(bundle.characters.values())
    backgrounds = list(bundle.backgrounds.values())
    variables = [
        {"name": v.name, "default_literal": _render_literal(v.default)}
        for v in bundle.variables.values()
    ]

    (script_dir / "characters.rpy").write_text(
        env.get_template("characters.rpy.j2").render(characters=characters), encoding="utf-8"
    )

    character_image_blocks = [
        _render_character_images(c) for c in characters if c.sprites or c.animated_sprites or c.is_live2d
    ]
    (script_dir / "images.rpy").write_text(
        env.get_template("images.rpy.j2").render(
            character_image_blocks=character_image_blocks,
            backgrounds=backgrounds,
            has_live2d=any(c.is_live2d for c in characters),
        ),
        encoding="utf-8",
    )

    (script_dir / "variables.rpy").write_text(
        env.get_template("variables.rpy.j2").render(variables=variables), encoding="utf-8"
    )
    (script_dir / "main.rpy").write_text(
        env.get_template("main.rpy.j2").render(project=bundle.meta), encoding="utf-8"
    )

    if bundle.meta.stats_display == "bar":
        visible_vars = [v for v in bundle.variables.values() if v.visible]
        if visible_vars:
            (script_dir / "stats.rpy").write_text(
                env.get_template("stats.rpy.j2").render(
                    visible_variables=[{"name": v.name, "label": v.display_label} for v in visible_vars]
                ),
                encoding="utf-8",
            )

    if bundle.routes or bundle.calendar is not None:
        (script_dir / "runtime.rpy").write_text(env.get_template("runtime.rpy.j2").render(), encoding="utf-8")

    if bundle.routes:
        (script_dir / "routes.rpy").write_text(
            env.get_template("routes.rpy.j2").render(routes_literal=_routes_literal(bundle.routes)),
            encoding="utf-8",
        )

    if bundle.calendar is not None:
        on_end_target = bundle.calendar.on_end or "resolve_routes"
        (script_dir / "calendar.rpy").write_text(
            env.get_template("calendar.rpy.j2").render(
                day_names_literal=repr(bundle.calendar.day_names),
                slots_literal=repr(bundle.calendar.slots),
                day_count=bundle.calendar.day_count,
                schedule_literal=_schedule_literal(bundle.schedule),
                locations=[_compile_location(loc) for loc in bundle.locations.values()],
                on_end_target=on_end_target,
            ),
            encoding="utf-8",
        )

    scenes_out = script_dir / "scenes"
    scenes_out.mkdir(exist_ok=True)
    scene_template = env.get_template("scene.rpy.j2")
    for scene in bundle.scenes.values():
        compiled = _compile_scene(scene, bundle.audio)
        (scenes_out / f"{scene.id}.rpy").write_text(scene_template.render(scene=compiled), encoding="utf-8")

    _layout_assets(bundle, game_dir)
    return game_dir


def _layout_assets(bundle: ProjectBundle, game_dir: Path) -> None:
    images_dir = game_dir / "images"
    audio_dir = game_dir / "audio"

    for char in bundle.characters.values():
        char_dir = images_dir / "characters" / char.id
        char_dir.mkdir(parents=True, exist_ok=True)
        for filename in char.sprites.values():
            src = bundle.root / "characters" / filename
            if src.exists():
                shutil.copy2(src, char_dir / filename)
        for frames in char.animated_sprites.values():
            for filename in frames:
                src = bundle.root / "characters" / filename
                if src.exists():
                    shutil.copy2(src, char_dir / filename)
        if char.is_live2d:
            model_rel = (char.animation or {}).get("model")
            if model_rel:
                src_dir = (bundle.root / "characters" / model_rel).parent
                if src_dir.exists():
                    dst_dir = images_dir / "characters" / Path(model_rel).parent
                    shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)

    bg_dir = images_dir / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)
    for bg in bundle.backgrounds.values():
        src = bundle.root / "backgrounds" / bg.file
        if src.exists():
            shutil.copy2(src, bg_dir / bg.file)

    audio_dir.mkdir(parents=True, exist_ok=True)
    for asset in bundle.audio.values():
        src = bundle.root / "audio" / asset.file
        if src.exists():
            shutil.copy2(src, audio_dir / asset.file)
