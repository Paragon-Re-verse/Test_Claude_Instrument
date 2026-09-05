"""Codegen-слой: JSON-модель проекта -> валидные .rpy файлы + раскладка ассетов.

Ren'Py-специфичные детали (метки, menu:, if/else, image-объявления) изолированы
здесь, чтобы модель проекта (vnstudio.models) и GUI поверх неё ничего не знали
про синтаксис Ren'Py.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from vnstudio.models import (
    ChoiceNode,
    ConditionNode,
    DialogueNode,
    ProjectBundle,
    Scene,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


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


def _compile_dialogue(node: DialogueNode, scene: Scene, characters: dict) -> dict:
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


def _compile_condition(node: ConditionNode, scene: Scene) -> dict:
    return {
        "kind": "condition",
        "label": node_label(scene.id, node.id),
        "expr": f"{node.var} {node.op} {_render_literal(node.value)}",
        "then_stmt": _jump_stmt(node.then, scene.id),
        "else_stmt": _jump_stmt(node.else_, scene.id),
    }


def _compile_scene(scene: Scene, characters: dict, audio: dict) -> dict:
    compiled_nodes = []
    for node in scene.nodes.values():
        if isinstance(node, DialogueNode):
            compiled_nodes.append(_compile_dialogue(node, scene, characters))
        elif isinstance(node, ChoiceNode):
            compiled_nodes.append(_compile_choice(node, scene))
        elif isinstance(node, ConditionNode):
            compiled_nodes.append(_compile_condition(node, scene))
    music_file = f"audio/{audio[scene.music].file}" if scene.music else None
    return {
        "id": scene.id,
        "background": scene.background,
        "music": music_file,
        "start_label": node_label(scene.id, scene.start),
        "nodes": compiled_nodes,
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
    (script_dir / "images.rpy").write_text(
        env.get_template("images.rpy.j2").render(characters=characters, backgrounds=backgrounds),
        encoding="utf-8",
    )
    (script_dir / "variables.rpy").write_text(
        env.get_template("variables.rpy.j2").render(variables=variables), encoding="utf-8"
    )
    (script_dir / "main.rpy").write_text(
        env.get_template("main.rpy.j2").render(project=bundle.meta), encoding="utf-8"
    )

    scenes_out = script_dir / "scenes"
    scenes_out.mkdir(exist_ok=True)
    scene_template = env.get_template("scene.rpy.j2")
    for scene in bundle.scenes.values():
        compiled = _compile_scene(scene, bundle.characters, bundle.audio)
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
