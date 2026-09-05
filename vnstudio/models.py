"""Модель проекта визуальной новеллы.

Формат хранения — набор JSON-файлов на диске (см. README.md, раздел
"Формат проекта"). Этот модуль читает их, проверяет и превращает в
Python-объекты, которыми дальше пользуется codegen-слой.

Валидация написана вручную (без внешней jsonschema-зависимости), чтобы
инструмент оставался легковесным для конечного пользователя — единственная
внешняя зависимость всего пакета это Jinja2 (нужна только codegen-слою).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTENSIONS = {".ogg", ".mp3", ".wav", ".opus"}
CONDITION_OPS = {">", "<", ">=", "<=", "==", "!="}
EFFECT_OPS = {"=", "+=", "-=", "*=", "/="}
VARIABLE_TYPES = {"int", "float", "bool", "str"}


class ProjectValidationError(ValueError):
    """Ошибка в данных проекта, которую должен увидеть и исправить пользователь."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectValidationError(message)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectValidationError(f"Некорректный JSON в {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Персонажи
# ---------------------------------------------------------------------------


@dataclass
class Character:
    id: str
    name: str
    color: str = "#ffffff"
    sprites: dict[str, str] = field(default_factory=dict)  # emotion -> относительный путь к файлу

    def validate(self) -> None:
        _require(bool(self.id), "У персонажа отсутствует id")
        _require(bool(self.name), f"У персонажа '{self.id}' отсутствует имя")
        _require(
            self.color.startswith("#") and len(self.color) in (4, 7),
            f"Некорректный цвет реплик у персонажа '{self.id}': {self.color!r}",
        )


def _scan_character_sprites(characters_dir: Path) -> dict[str, dict[str, str]]:
    """Автоопределение спрайтов по имени файла: alice_happy.png -> alice/happy."""
    sprites: dict[str, dict[str, str]] = {}
    if not characters_dir.is_dir():
        return sprites
    for f in sorted(characters_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        stem = f.stem
        if "_" not in stem:
            continue
        char_id, emotion = stem.split("_", 1)
        sprites.setdefault(char_id, {})[emotion] = f.name
    return sprites


def load_characters(characters_dir: Path) -> dict[str, Character]:
    sprites_by_char = _scan_character_sprites(characters_dir)
    meta_path = characters_dir / "characters.json"
    meta_by_id: dict[str, dict[str, Any]] = {}
    if meta_path.exists():
        raw = _load_json(meta_path)
        _require(isinstance(raw, list), f"{meta_path} должен содержать список персонажей")
        for entry in raw:
            _require("id" in entry, f"Запись персонажа без id в {meta_path}: {entry}")
            meta_by_id[entry["id"]] = entry

    all_ids = set(sprites_by_char) | set(meta_by_id)
    characters: dict[str, Character] = {}
    for char_id in sorted(all_ids):
        meta = meta_by_id.get(char_id, {})
        char = Character(
            id=char_id,
            name=meta.get("name", char_id),
            color=meta.get("color", "#ffffff"),
            sprites=sprites_by_char.get(char_id, {}),
        )
        char.validate()
        characters[char_id] = char
    return characters


# ---------------------------------------------------------------------------
# Фоны
# ---------------------------------------------------------------------------


@dataclass
class Background:
    id: str
    file: str

    def validate(self) -> None:
        _require(bool(self.id), "У фона отсутствует id")
        _require(bool(self.file), f"У фона '{self.id}' не указан файл")


def load_backgrounds(backgrounds_dir: Path) -> dict[str, Background]:
    meta_path = backgrounds_dir / "backgrounds.json"
    backgrounds: dict[str, Background] = {}

    if meta_path.exists():
        raw = _load_json(meta_path)
        _require(isinstance(raw, list), f"{meta_path} должен содержать список фонов")
        for entry in raw:
            _require("id" in entry and "file" in entry, f"Некорректная запись фона в {meta_path}: {entry}")
            bg = Background(id=entry["id"], file=entry["file"])
            bg.validate()
            backgrounds[bg.id] = bg
        return backgrounds

    if not backgrounds_dir.is_dir():
        return backgrounds

    for f in sorted(backgrounds_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            bg = Background(id=f.stem, file=f.name)
            bg.validate()
            backgrounds[bg.id] = bg
    return backgrounds


# ---------------------------------------------------------------------------
# Аудио
# ---------------------------------------------------------------------------


@dataclass
class AudioAsset:
    id: str
    file: str
    kind: str = "sfx"  # "music" | "sfx"

    def validate(self) -> None:
        _require(bool(self.id), "У аудио-ассета отсутствует id")
        _require(self.kind in ("music", "sfx"), f"Некорректный kind у аудио '{self.id}': {self.kind}")


def load_audio(audio_dir: Path) -> dict[str, AudioAsset]:
    meta_path = audio_dir / "audio.json"
    assets: dict[str, AudioAsset] = {}

    if meta_path.exists():
        raw = _load_json(meta_path)
        _require(isinstance(raw, list), f"{meta_path} должен содержать список аудио")
        for entry in raw:
            _require("id" in entry and "file" in entry, f"Некорректная запись аудио в {meta_path}: {entry}")
            asset = AudioAsset(id=entry["id"], file=entry["file"], kind=entry.get("type", "sfx"))
            asset.validate()
            assets[asset.id] = asset
        return assets

    if not audio_dir.is_dir():
        return assets

    for f in sorted(audio_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
            kind = "music" if f.parent.name == "music" else "sfx"
            asset = AudioAsset(id=f.stem, file=f.name, kind=kind)
            asset.validate()
            assets[asset.id] = asset
    return assets


# ---------------------------------------------------------------------------
# Переменные (статы)
# ---------------------------------------------------------------------------


@dataclass
class Variable:
    name: str
    type: str = "int"
    default: Any = 0

    def validate(self) -> None:
        _require(self.name.isidentifier(), f"Имя переменной должно быть Python-идентификатором: {self.name!r}")
        _require(self.type in VARIABLE_TYPES, f"Неизвестный тип переменной '{self.name}': {self.type}")


def load_variables(variables_dir: Path) -> dict[str, Variable]:
    path = variables_dir / "variables.json"
    variables: dict[str, Variable] = {}
    if not path.exists():
        return variables
    raw = _load_json(path)
    _require(isinstance(raw, list), f"{path} должен содержать список переменных")
    for entry in raw:
        _require("name" in entry, f"Переменная без имени в {path}: {entry}")
        var = Variable(name=entry["name"], type=entry.get("type", "int"), default=entry.get("default", 0))
        var.validate()
        variables[var.name] = var
    return variables


# ---------------------------------------------------------------------------
# Граф сцены
# ---------------------------------------------------------------------------

NodeRef = Optional[str]  # id узла в этой же сцене, "@другая_сцена" для перехода между сценами, или None (конец)


@dataclass
class DialogueNode:
    id: str
    text: str
    character: Optional[str] = None  # id персонажа или None для рассказчика
    emotion: Optional[str] = None
    next: NodeRef = None
    type: str = "dialogue"


@dataclass
class ChoiceOption:
    text: str
    next: NodeRef = None
    effects: list[dict[str, Any]] = field(default_factory=list)  # [{var, op, value}]


@dataclass
class ChoiceNode:
    id: str
    options: list[ChoiceOption]
    prompt: Optional[str] = None
    type: str = "choice"


@dataclass
class ConditionNode:
    id: str
    var: str
    op: str
    value: Any
    then: NodeRef
    else_: NodeRef
    type: str = "condition"


SceneNode = Union[DialogueNode, ChoiceNode, ConditionNode]


@dataclass
class Scene:
    id: str
    nodes: dict[str, SceneNode]
    start: str
    background: Optional[str] = None
    music: Optional[str] = None

    def validate(self, characters: dict[str, Character], backgrounds: dict[str, Background],
                 audio: dict[str, AudioAsset], variables: dict[str, Variable]) -> None:
        _require(bool(self.id), "У сцены отсутствует id")
        _require(self.start in self.nodes, f"Сцена '{self.id}': стартовый узел '{self.start}' не найден")
        if self.background is not None:
            _require(self.background in backgrounds,
                      f"Сцена '{self.id}': фон '{self.background}' не найден в backgrounds/")
        if self.music is not None:
            _require(self.music in audio and audio[self.music].kind == "music",
                      f"Сцена '{self.id}': музыка '{self.music}' не найдена среди audio/ (type=music)")

        def check_ref(ref: NodeRef, where: str) -> None:
            if ref is None or (isinstance(ref, str) and ref.startswith("@")):
                return
            _require(ref in self.nodes, f"Сцена '{self.id}', {where}: ссылка на несуществующий узел '{ref}'")

        for node in self.nodes.values():
            if isinstance(node, DialogueNode):
                if node.character is not None:
                    _require(node.character in characters,
                              f"Сцена '{self.id}', узел '{node.id}': персонаж '{node.character}' не найден")
                    char = characters[node.character]
                    if node.emotion is not None:
                        _require(node.emotion in char.sprites,
                                  f"Сцена '{self.id}', узел '{node.id}': у персонажа '{char.id}' "
                                  f"нет спрайта для эмоции '{node.emotion}'")
                check_ref(node.next, f"узел '{node.id}'")
            elif isinstance(node, ChoiceNode):
                _require(len(node.options) >= 1, f"Сцена '{self.id}', узел '{node.id}': нет вариантов выбора")
                for i, opt in enumerate(node.options):
                    check_ref(opt.next, f"узел '{node.id}', вариант {i}")
                    for eff in opt.effects:
                        _require(eff.get("var") in variables,
                                  f"Сцена '{self.id}', узел '{node.id}': эффект ссылается на "
                                  f"неизвестную переменную '{eff.get('var')}'")
                        _require(eff.get("op") in EFFECT_OPS,
                                  f"Сцена '{self.id}', узел '{node.id}': неизвестный оператор эффекта "
                                  f"'{eff.get('op')}'")
            elif isinstance(node, ConditionNode):
                _require(node.var in variables,
                          f"Сцена '{self.id}', узел '{node.id}': условие ссылается на "
                          f"неизвестную переменную '{node.var}'")
                _require(node.op in CONDITION_OPS,
                          f"Сцена '{self.id}', узел '{node.id}': неизвестный оператор условия '{node.op}'")
                check_ref(node.then, f"узел '{node.id}' (then)")
                check_ref(node.else_, f"узел '{node.id}' (else)")


def _parse_node(raw: dict[str, Any], scene_id: str) -> SceneNode:
    _require("id" in raw and "type" in raw, f"Сцена '{scene_id}': узел без id/type: {raw}")
    node_id = raw["id"]
    node_type = raw["type"]
    if node_type == "dialogue":
        _require("text" in raw, f"Сцена '{scene_id}', узел '{node_id}': нет текста реплики")
        return DialogueNode(
            id=node_id,
            text=raw["text"],
            character=raw.get("character"),
            emotion=raw.get("emotion"),
            next=raw.get("next"),
        )
    if node_type == "choice":
        options = [
            ChoiceOption(text=opt["text"], next=opt.get("next"), effects=opt.get("effects", []))
            for opt in raw.get("options", [])
        ]
        return ChoiceNode(id=node_id, options=options, prompt=raw.get("text"))
    if node_type == "condition":
        cond = raw.get("condition", {})
        _require({"var", "op", "value"} <= cond.keys(),
                  f"Сцена '{scene_id}', узел '{node_id}': условие должно содержать var/op/value")
        return ConditionNode(
            id=node_id,
            var=cond["var"],
            op=cond["op"],
            value=cond["value"],
            then=raw.get("then"),
            else_=raw.get("else"),
        )
    raise ProjectValidationError(f"Сцена '{scene_id}', узел '{node_id}': неизвестный тип узла '{node_type}'")


def load_scenes(scenes_dir: Path) -> dict[str, Scene]:
    scenes: dict[str, Scene] = {}
    if not scenes_dir.is_dir():
        return scenes
    for f in sorted(scenes_dir.glob("*.json")):
        raw = _load_json(f)
        scene_id = raw.get("id", f.stem)
        raw_nodes = raw.get("nodes", [])
        _require(len(raw_nodes) > 0, f"Сцена '{scene_id}' ({f}): нет узлов")
        nodes = {n["id"]: _parse_node(n, scene_id) for n in raw_nodes}
        start = raw.get("start", raw_nodes[0]["id"])
        scene = Scene(
            id=scene_id,
            nodes=nodes,
            start=start,
            background=raw.get("background"),
            music=raw.get("music"),
        )
        scenes[scene_id] = scene
    return scenes


# ---------------------------------------------------------------------------
# Проект целиком
# ---------------------------------------------------------------------------


@dataclass
class ProjectMeta:
    name: str
    resolution: tuple[int, int] = (1920, 1080)
    language: str = "ru"
    start_scene: str = ""

    def validate(self) -> None:
        _require(bool(self.name), "У проекта не указано название (name)")
        _require(len(self.resolution) == 2, "resolution должно быть парой [ширина, высота]")
        _require(bool(self.start_scene), "У проекта не указана стартовая сцена (start_scene)")


@dataclass
class ProjectBundle:
    root: Path
    meta: ProjectMeta
    characters: dict[str, Character]
    backgrounds: dict[str, Background]
    audio: dict[str, AudioAsset]
    variables: dict[str, Variable]
    scenes: dict[str, Scene]

    def validate(self) -> None:
        self.meta.validate()
        _require(self.meta.start_scene in self.scenes,
                  f"Стартовая сцена '{self.meta.start_scene}' не найдена в scenes/")
        for scene in self.scenes.values():
            scene.validate(self.characters, self.backgrounds, self.audio, self.variables)
        # Проверяем перекрёстные ссылки "@другая_сцена" между сценами.
        for scene in self.scenes.values():
            for node in scene.nodes.values():
                for ref in _cross_scene_refs(node):
                    _require(ref in self.scenes,
                              f"Сцена '{scene.id}': ссылка на несуществующую сцену '@{ref}'")


def _cross_scene_refs(node: SceneNode) -> list[str]:
    refs: list[NodeRef] = []
    if isinstance(node, DialogueNode):
        refs = [node.next]
    elif isinstance(node, ChoiceNode):
        refs = [opt.next for opt in node.options]
    elif isinstance(node, ConditionNode):
        refs = [node.then, node.else_]
    return [r[1:] for r in refs if isinstance(r, str) and r.startswith("@")]


def load_project(project_dir: Union[str, Path]) -> ProjectBundle:
    root = Path(project_dir)
    project_json = root / "project.json"
    _require(project_json.exists(), f"Не найден {project_json}")
    raw = _load_json(project_json)
    meta = ProjectMeta(
        name=raw.get("name", root.name),
        resolution=tuple(raw.get("resolution", [1920, 1080])),
        language=raw.get("language", "ru"),
        start_scene=raw.get("start_scene", ""),
    )

    bundle = ProjectBundle(
        root=root,
        meta=meta,
        characters=load_characters(root / "characters"),
        backgrounds=load_backgrounds(root / "backgrounds"),
        audio=load_audio(root / "audio"),
        variables=load_variables(root / "variables"),
        scenes=load_scenes(root / "scenes"),
    )
    bundle.validate()
    return bundle
