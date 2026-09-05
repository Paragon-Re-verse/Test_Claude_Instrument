"""Модель проекта визуальной новеллы.

Формат хранения — набор JSON-файлов на диске (см. README.md, раздел
"Формат проекта"). Этот модуль читает их, проверяет и превращает в
Python-объекты, которыми дальше пользуется codegen-слой.

Валидация написана вручную (без внешней jsonschema-зависимости), чтобы
инструмент оставался легковесным для конечного пользователя — единственная
внешняя зависимость всего пакета это Jinja2 (нужна только codegen-слою).

Помимо базовой модели (персонажи/фоны/сцены/переменные/аудио) модуль
поддерживает механики, типичные для school-life / dating sim в духе
Type-moon (Fate/stay night):

  - calendar/ + schedule/ + locations/  — календарь дней и тайм-слотов,
    хаб локаций, события, привязанные к (день, слот, локация)
  - routes/                              — маршруты персонажей: авто-расчёт
    по итоговым статам (в т.ч. относительное сравнение "стат A > стат B"),
    последовательная разблокировка (route-gating) через persistent
  - ending-узлы в графе сцены с категорией bad/normal/true
  - visible=false у переменной + project.stats_display="hidden" — скрытые
    очки без видимого счётчика
  - animation-метаданные персонажа (покадровая спрайт-анимация или
    экспериментальная Live2D-обвязка)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTENSIONS = {".ogg", ".mp3", ".wav", ".opus"}
CONDITION_OPS = {">", "<", ">=", "<=", "==", "!="}
EFFECT_OPS = {"=", "+=", "-=", "*=", "/="}
VARIABLE_TYPES = {"int", "float", "bool", "str"}
ENDING_CATEGORIES = {"bad", "normal", "true"}
CHARACTER_ANIMATION_TYPES = {"sprite", "live2d"}

_FRAME_SUFFIX_RE = re.compile(r"^(?P<emotion>.+)_(?P<frame>\d+)$")


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
# Условия (переиспользуются в condition-узлах, маршрутах и расписании)
# ---------------------------------------------------------------------------


def _parse_condition_dict(raw: dict[str, Any], where: str) -> dict[str, Any]:
    _require("var" in raw and "op" in raw, f"{where}: условие должно содержать 'var' и 'op'")
    has_value = "value" in raw
    has_compare = "compare_var" in raw
    _require(has_value != has_compare, f"{where}: условие должно содержать ровно одно из 'value' или 'compare_var'")
    return {
        "var": raw["var"],
        "op": raw["op"],
        "value": raw.get("value"),
        "compare_var": raw.get("compare_var"),
    }


def _validate_condition_refs(cond: dict[str, Any], variables: dict[str, "Variable"], where: str) -> None:
    _require(cond["op"] in CONDITION_OPS, f"{where}: неизвестный оператор условия '{cond['op']}'")
    _require(cond["var"] in variables, f"{where}: условие ссылается на неизвестную переменную '{cond['var']}'")
    if cond["compare_var"] is not None:
        _require(cond["compare_var"] in variables,
                  f"{where}: условие сравнивает с неизвестной переменной '{cond['compare_var']}'")


# ---------------------------------------------------------------------------
# Персонажи
# ---------------------------------------------------------------------------


@dataclass
class Character:
    id: str
    name: str
    color: str = "#ffffff"
    sprites: dict[str, str] = field(default_factory=dict)  # emotion -> файл (статичный портрет)
    animated_sprites: dict[str, list[str]] = field(default_factory=dict)  # emotion -> кадры по порядку
    animation: Optional[dict[str, Any]] = None  # {"type": "sprite"|"live2d", ...}

    def validate(self) -> None:
        _require(bool(self.id), "У персонажа отсутствует id")
        _require(bool(self.name), f"У персонажа '{self.id}' отсутствует имя")
        _require(
            self.color.startswith("#") and len(self.color) in (4, 7),
            f"Некорректный цвет реплик у персонажа '{self.id}': {self.color!r}",
        )
        if self.animation is not None:
            atype = self.animation.get("type")
            _require(atype in CHARACTER_ANIMATION_TYPES,
                      f"Персонаж '{self.id}': animation.type должен быть одним из {CHARACTER_ANIMATION_TYPES}")
            if atype == "live2d":
                _require(bool(self.animation.get("model")),
                          f"Персонаж '{self.id}': для animation.type=live2d нужен путь 'model' "
                          f"(например 'alice/alice.model3.json' относительно characters/)")

    def has_emotion(self, emotion: str) -> bool:
        if self.animation and self.animation.get("type") == "live2d":
            return emotion in (self.animation.get("motions") or {})
        return emotion in self.sprites or emotion in self.animated_sprites

    @property
    def is_live2d(self) -> bool:
        return bool(self.animation and self.animation.get("type") == "live2d")


def _scan_character_sprites(characters_dir: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, list[str]]]]:
    """Автоопределение спрайтов по имени файла.

    alice_happy.png          -> статичный портрет: alice / happy
    alice_happy_1.png, _2.png -> кадры анимации: alice / happy -> [alice_happy_1.png, alice_happy_2.png]
    """
    static: dict[str, dict[str, str]] = {}
    animated_raw: dict[str, dict[str, list[tuple[int, str]]]] = {}

    if not characters_dir.is_dir():
        return static, {}

    for f in sorted(characters_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        stem = f.stem
        if "_" not in stem:
            continue
        char_id, rest = stem.split("_", 1)
        frame_match = _FRAME_SUFFIX_RE.match(rest)
        if frame_match:
            emotion = frame_match.group("emotion")
            frame_no = int(frame_match.group("frame"))
            animated_raw.setdefault(char_id, {}).setdefault(emotion, []).append((frame_no, f.name))
        else:
            static.setdefault(char_id, {})[rest] = f.name

    animated: dict[str, dict[str, list[str]]] = {}
    for char_id, emotions in animated_raw.items():
        animated[char_id] = {
            emotion: [name for _, name in sorted(frames)]
            for emotion, frames in emotions.items()
        }
    return static, animated


def load_characters(characters_dir: Path) -> dict[str, Character]:
    static_sprites, animated_sprites = _scan_character_sprites(characters_dir)
    meta_path = characters_dir / "characters.json"
    meta_by_id: dict[str, dict[str, Any]] = {}
    if meta_path.exists():
        raw = _load_json(meta_path)
        _require(isinstance(raw, list), f"{meta_path} должен содержать список персонажей")
        for entry in raw:
            _require("id" in entry, f"Запись персонажа без id в {meta_path}: {entry}")
            meta_by_id[entry["id"]] = entry

    all_ids = set(static_sprites) | set(animated_sprites) | set(meta_by_id)
    characters: dict[str, Character] = {}
    for char_id in sorted(all_ids):
        meta = meta_by_id.get(char_id, {})
        char = Character(
            id=char_id,
            name=meta.get("name", char_id),
            color=meta.get("color", "#ffffff"),
            sprites=static_sprites.get(char_id, {}),
            animated_sprites=animated_sprites.get(char_id, {}),
            animation=meta.get("animation"),
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
    visible: bool = True  # False = скрытый флаг/очки (японская VN-традиция), не показывается игроку
    label: Optional[str] = None  # отображаемое имя для стат-бара; по умолчанию = name

    def validate(self) -> None:
        _require(self.name.isidentifier(), f"Имя переменной должно быть Python-идентификатором: {self.name!r}")
        _require(self.type in VARIABLE_TYPES, f"Неизвестный тип переменной '{self.name}': {self.type}")

    @property
    def display_label(self) -> str:
        return self.label or self.name


def load_variables(variables_dir: Path) -> dict[str, Variable]:
    path = variables_dir / "variables.json"
    variables: dict[str, Variable] = {}
    if not path.exists():
        return variables
    raw = _load_json(path)
    _require(isinstance(raw, list), f"{path} должен содержать список переменных")
    for entry in raw:
        _require("name" in entry, f"Переменная без имени в {path}: {entry}")
        var = Variable(
            name=entry["name"],
            type=entry.get("type", "int"),
            default=entry.get("default", 0),
            visible=entry.get("visible", True),
            label=entry.get("label"),
        )
        var.validate()
        variables[var.name] = var
    return variables


# ---------------------------------------------------------------------------
# Граф сцены
# ---------------------------------------------------------------------------

NodeRef = Optional[str]  # id узла в этой же сцене, "@другая_сцена" / "@resolve_routes", или None (конец)


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
    then: NodeRef
    else_: NodeRef
    value: Any = None
    compare_var: Optional[str] = None
    type: str = "condition"


@dataclass
class EndingNode:
    id: str
    category: str  # "bad" | "normal" | "true"
    title: Optional[str] = None  # переопределяет стандартный текст экрана концовки
    route: Optional[str] = None  # id маршрута (routes/routes.json) — засчитывается пройденным
    type: str = "ending"


SceneNode = Union[DialogueNode, ChoiceNode, ConditionNode, EndingNode]


@dataclass
class Scene:
    id: str
    nodes: dict[str, SceneNode]
    start: str
    background: Optional[str] = None
    music: Optional[str] = None

    def validate(self, characters: dict[str, Character], backgrounds: dict[str, Background],
                 audio: dict[str, AudioAsset], variables: dict[str, Variable],
                 routes: dict[str, "RouteDef"]) -> None:
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
                        _require(char.has_emotion(node.emotion),
                                  f"Сцена '{self.id}', узел '{node.id}': у персонажа '{char.id}' "
                                  f"нет эмоции/спрайта '{node.emotion}'")
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
                cond = {"var": node.var, "op": node.op, "value": node.value, "compare_var": node.compare_var}
                _validate_condition_refs(cond, variables, f"Сцена '{self.id}', узел '{node.id}'")
                check_ref(node.then, f"узел '{node.id}' (then)")
                check_ref(node.else_, f"узел '{node.id}' (else)")
            elif isinstance(node, EndingNode):
                _require(node.category in ENDING_CATEGORIES,
                          f"Сцена '{self.id}', узел '{node.id}': category должна быть одной из {ENDING_CATEGORIES}")
                if node.route is not None:
                    _require(node.route in routes,
                              f"Сцена '{self.id}', узел '{node.id}': маршрут '{node.route}' не найден "
                              f"в routes/routes.json")


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
        cond_raw = raw.get("condition", {})
        cond = _parse_condition_dict(cond_raw, f"Сцена '{scene_id}', узел '{node_id}'")
        return ConditionNode(
            id=node_id,
            var=cond["var"],
            op=cond["op"],
            value=cond["value"],
            compare_var=cond["compare_var"],
            then=raw.get("then"),
            else_=raw.get("else"),
        )
    if node_type == "ending":
        _require("category" in raw, f"Сцена '{scene_id}', узел '{node_id}': у концовки нет category")
        return EndingNode(id=node_id, category=raw["category"], title=raw.get("title"), route=raw.get("route"))
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


def _cross_scene_refs(node: SceneNode) -> list[str]:
    refs: list[NodeRef] = []
    if isinstance(node, DialogueNode):
        refs = [node.next]
    elif isinstance(node, ChoiceNode):
        refs = [opt.next for opt in node.options]
    elif isinstance(node, ConditionNode):
        refs = [node.then, node.else_]
    return [r[1:] for r in refs if isinstance(r, str) and r.startswith("@")]


# ---------------------------------------------------------------------------
# Маршруты (routes) — авто-расчёт по итоговым статам + последовательная
# разблокировка (route-gating), в духе Fate/stay night
# ---------------------------------------------------------------------------


@dataclass
class RouteDef:
    id: str
    name: str
    start_scene: str
    requires: Optional[str] = None  # id маршрута, который должен быть уже пройден (persistent)
    condition: Optional[dict[str, Any]] = None  # {var, op, value|compare_var} или None = без доп. условия

    def validate(self, variables: dict[str, Variable], scenes: dict[str, Scene], routes: dict[str, "RouteDef"]) -> None:
        _require(bool(self.id), "У маршрута отсутствует id")
        _require(bool(self.name), f"У маршрута '{self.id}' не указано имя")
        _require(self.start_scene in scenes,
                  f"Маршрут '{self.id}': стартовая сцена '{self.start_scene}' не найдена")
        if self.requires is not None:
            _require(self.requires in routes,
                      f"Маршрут '{self.id}': requires ссылается на неизвестный маршрут '{self.requires}'")
        if self.condition is not None:
            _validate_condition_refs(self.condition, variables, f"Маршрут '{self.id}'")


def load_routes(routes_dir: Path) -> dict[str, RouteDef]:
    path = routes_dir / "routes.json"
    routes: dict[str, RouteDef] = {}
    if not path.exists():
        return routes
    raw = _load_json(path)
    _require(isinstance(raw, list), f"{path} должен содержать список маршрутов")
    for entry in raw:
        _require("id" in entry and "start_scene" in entry, f"Некорректная запись маршрута в {path}: {entry}")
        condition = None
        if "condition" in entry:
            condition = _parse_condition_dict(entry["condition"], f"Маршрут '{entry['id']}'")
        route = RouteDef(
            id=entry["id"],
            name=entry.get("name", entry["id"]),
            start_scene=entry["start_scene"],
            requires=entry.get("requires"),
            condition=condition,
        )
        routes[route.id] = route
    return routes


def _check_route_requires_acyclic(routes: dict[str, RouteDef]) -> None:
    for start_id, route in routes.items():
        seen = {start_id}
        current = route.requires
        while current is not None:
            _require(current not in seen, f"Маршрут '{start_id}': цикл в цепочке requires (через '{current}')")
            seen.add(current)
            current = routes[current].requires


# ---------------------------------------------------------------------------
# Календарь / тайм-слоты / локации / расписание
# ---------------------------------------------------------------------------


@dataclass
class CalendarConfig:
    day_names: list[str]
    slots: list[str]
    day_count: int
    on_end: Optional[str] = None  # id сцены, куда прыгать по окончании календаря; None -> "@resolve_routes"

    def validate(self) -> None:
        _require(len(self.day_names) > 0, "calendar/calendar.json: day_names не может быть пустым")
        _require(len(self.slots) > 0, "calendar/calendar.json: slots не может быть пустым")
        _require(len(self.slots) == len(set(self.slots)), "calendar/calendar.json: имена слотов должны быть уникальны")
        _require(self.day_count > 0, "calendar/calendar.json: day_count должен быть положительным")


def load_calendar(calendar_dir: Path) -> Optional[CalendarConfig]:
    path = calendar_dir / "calendar.json"
    if not path.exists():
        return None
    raw = _load_json(path)
    cal = CalendarConfig(
        day_names=raw.get("day_names", []),
        slots=raw.get("slots", []),
        day_count=raw.get("day_count", 0),
        on_end=raw.get("on_end"),
    )
    cal.validate()
    return cal


@dataclass
class Location:
    id: str
    name: str
    background: Optional[str] = None
    available_slots: Optional[list[str]] = None  # None = доступна в любой тайм-слот

    def validate(self, backgrounds: dict[str, Background], calendar: Optional[CalendarConfig]) -> None:
        _require(bool(self.id), "У локации отсутствует id")
        _require(bool(self.name), f"У локации '{self.id}' не указано имя")
        if self.background is not None:
            _require(self.background in backgrounds, f"Локация '{self.id}': фон '{self.background}' не найден")
        if self.available_slots is not None:
            _require(calendar is not None,
                      f"Локация '{self.id}': available_slots требует настроенного calendar/calendar.json")
            for slot in self.available_slots:
                _require(slot in calendar.slots, f"Локация '{self.id}': неизвестный тайм-слот '{slot}'")


def load_locations(locations_dir: Path) -> dict[str, Location]:
    path = locations_dir / "locations.json"
    locations: dict[str, Location] = {}
    if not path.exists():
        return locations
    raw = _load_json(path)
    _require(isinstance(raw, list), f"{path} должен содержать список локаций")
    for entry in raw:
        _require("id" in entry, f"Локация без id в {path}: {entry}")
        loc = Location(
            id=entry["id"],
            name=entry.get("name", entry["id"]),
            background=entry.get("background"),
            available_slots=entry.get("available_slots"),
        )
        locations[loc.id] = loc
    return locations


@dataclass
class ScheduleEvent:
    id: str
    location: str
    scene: str
    day: Union[int, str] = "any"  # "any" или абсолютный индекс дня (0-based)
    slot: Union[int, str] = "any"  # "any" или имя тайм-слота из calendar.slots
    once: bool = True
    priority: int = 0
    condition: Optional[dict[str, Any]] = None

    def validate(self, locations: dict[str, Location], scenes: dict[str, Scene],
                 variables: dict[str, Variable], calendar: Optional[CalendarConfig]) -> None:
        _require(bool(self.id), "У события расписания отсутствует id")
        _require(calendar is not None, f"Событие '{self.id}': нужен настроенный calendar/calendar.json")
        _require(self.location in locations, f"Событие '{self.id}': локация '{self.location}' не найдена")
        _require(self.scene in scenes, f"Событие '{self.id}': сцена '{self.scene}' не найдена")
        if self.day != "any":
            _require(isinstance(self.day, int) and 0 <= self.day < calendar.day_count,
                      f"Событие '{self.id}': day должен быть 'any' или числом от 0 до {calendar.day_count - 1}")
        if self.slot != "any":
            _require(self.slot in calendar.slots,
                      f"Событие '{self.id}': slot должен быть 'any' или одним из {calendar.slots}")
        if self.condition is not None:
            _validate_condition_refs(self.condition, variables, f"Событие '{self.id}'")


def load_schedule(schedule_dir: Path) -> dict[str, ScheduleEvent]:
    path = schedule_dir / "events.json"
    events: dict[str, ScheduleEvent] = {}
    if not path.exists():
        return events
    raw = _load_json(path)
    _require(isinstance(raw, list), f"{path} должен содержать список событий")
    for entry in raw:
        _require("id" in entry and "location" in entry and "scene" in entry,
                  f"Некорректная запись события в {path}: {entry}")
        condition = None
        if "condition" in entry:
            condition = _parse_condition_dict(entry["condition"], f"Событие '{entry['id']}'")
        event = ScheduleEvent(
            id=entry["id"],
            location=entry["location"],
            scene=entry["scene"],
            day=entry.get("day", "any"),
            slot=entry.get("slot", "any"),
            once=entry.get("once", True),
            priority=entry.get("priority", 0),
            condition=condition,
        )
        events[event.id] = event
    return events


# ---------------------------------------------------------------------------
# Проект целиком
# ---------------------------------------------------------------------------


@dataclass
class ProjectMeta:
    name: str
    resolution: tuple[int, int] = (1920, 1080)
    language: str = "ru"
    start_scene: str = ""
    stats_display: str = "bar"  # "bar" — видимый стат-бар; "hidden" — скрытые очки без счётчика

    def validate(self) -> None:
        _require(bool(self.name), "У проекта не указано название (name)")
        _require(len(self.resolution) == 2, "resolution должно быть парой [ширина, высота]")
        _require(bool(self.start_scene), "У проекта не указана стартовая сцена (start_scene)")
        _require(self.stats_display in ("bar", "hidden"),
                  f"project.json: stats_display должен быть 'bar' или 'hidden', получено {self.stats_display!r}")


@dataclass
class ProjectBundle:
    root: Path
    meta: ProjectMeta
    characters: dict[str, Character]
    backgrounds: dict[str, Background]
    audio: dict[str, AudioAsset]
    variables: dict[str, Variable]
    scenes: dict[str, Scene]
    routes: dict[str, RouteDef] = field(default_factory=dict)
    calendar: Optional[CalendarConfig] = None
    locations: dict[str, Location] = field(default_factory=dict)
    schedule: dict[str, ScheduleEvent] = field(default_factory=dict)

    def validate(self) -> None:
        self.meta.validate()
        _require(self.meta.start_scene in self.scenes,
                  f"Стартовая сцена '{self.meta.start_scene}' не найдена в scenes/")

        for scene in self.scenes.values():
            scene.validate(self.characters, self.backgrounds, self.audio, self.variables, self.routes)

        for scene in self.scenes.values():
            for node in scene.nodes.values():
                for ref in _cross_scene_refs(node):
                    if ref == "resolve_routes":
                        _require(len(self.routes) > 0,
                                  f"Сцена '{scene.id}': ссылка на '@resolve_routes', но routes/routes.json пуст")
                    elif ref == "calendar_loop":
                        _require(self.calendar is not None,
                                  f"Сцена '{scene.id}': ссылка на '@calendar_loop', но calendar/calendar.json не настроен")
                    else:
                        _require(ref in self.scenes, f"Сцена '{scene.id}': ссылка на несуществующую сцену '@{ref}'")

        for route in self.routes.values():
            route.validate(self.variables, self.scenes, self.routes)
        if self.routes:
            _check_route_requires_acyclic(self.routes)

        for loc in self.locations.values():
            loc.validate(self.backgrounds, self.calendar)

        for event in self.schedule.values():
            event.validate(self.locations, self.scenes, self.variables, self.calendar)

        if self.calendar is not None:
            if self.calendar.on_end is not None:
                _require(self.calendar.on_end in self.scenes,
                          f"calendar.json: on_end ссылается на несуществующую сцену '{self.calendar.on_end}'")
            else:
                _require(len(self.routes) > 0,
                          "calendar.json: не задан on_end и не определены routes/routes.json — по окончании "
                          "календаря игре некуда перейти")


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
        stats_display=raw.get("stats_display", "bar"),
    )

    bundle = ProjectBundle(
        root=root,
        meta=meta,
        characters=load_characters(root / "characters"),
        backgrounds=load_backgrounds(root / "backgrounds"),
        audio=load_audio(root / "audio"),
        variables=load_variables(root / "variables"),
        scenes=load_scenes(root / "scenes"),
        routes=load_routes(root / "routes"),
        calendar=load_calendar(root / "calendar"),
        locations=load_locations(root / "locations"),
        schedule=load_schedule(root / "schedule"),
    )
    bundle.validate()
    return bundle
