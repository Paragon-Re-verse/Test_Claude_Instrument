# vnstudio — no-code редактор визуальных новелл поверх Ren'Py

GUI-утилита для создания визуальных новелл (включая симуляторы свиданий со
статами) человеком без навыков программирования. Пользователь работает с
персонажами, фонами, графом сцен и переменными; на выходе — собранный
игровой проект (движок: [Ren'Py](https://www.renpy.org/)). Кода и конфигов
Ren'Py пользователь не видит — это внутренний формат инструмента.

## Статус реализации

Репозиторий реализует ТЗ в порядке, рекомендованном в исходном задании:

| Этап | Статус |
|---|---|
| 1. JSON-схема проекта (персонажи, сцены, переменные) | ✅ `vnstudio/models.py` |
| 2. Codegen: JSON → `.rpy` для линейного диалога + выбора + условия | ✅ `vnstudio/codegen/` |
| 3. Headless-вызов Ren'Py CLI (`compile` → `lint` → `distribute`) | ✅ обвязка готова в `vnstudio/build.py`; **не проверено сборкой реального exe** — в этом окружении нет Ren'Py SDK и сети для его загрузки (см. ниже "Как проверить сборку") |
| 4. GUI поверх пайплайна | ⏳ не начат (сознательно, по рекомендованному порядку — пайплайн должен работать первым) |

Слои 1–3 покрыты юнит-тестами (`tests/`, только stdlib `unittest`, без
`pytest`) и рабочим примером проекта (`examples/dating_sim_demo/`) —
линейный диалог, выбор с эффектом на стат (`affection_alice`) и условное
ветвление на две разные сцены.

### School-life / dating sim механики (в духе Type-moon)

Поверх базового графа сцен реализован набор механик, типичных для
жанра school-life dating sim и явно вдохновлённых Fate/stay night:

| Механика | Статус |
|---|---|
| Календарь: день недели + тайм-слот → хаб локаций и события | ✅ `calendar/`, `locations/`, `schedule/` → `calendar.rpy` |
| Маршруты (routes): авто-расчёт по итоговым статам, в т.ч. **относительное** сравнение `статA > статB` | ✅ `routes/routes.json` → `routes.rpy`, `label resolve_routes:` |
| Последовательная разблокировка маршрутов (route-gating) | ✅ `requires` + `persistent.vnstudio_completed_routes` (переживает перезапуск игры) |
| Скрытая система очков без видимого счётчика | ✅ `Variable.visible` + `project.stats_display: "bar"\|"hidden"` |
| Многоуровневые концовки (bad/normal/true) как типизированный узел | ✅ `ending`-узел графа сцены, отдельный экран на категорию |
| Live2D / спрайт-анимация поверх статичных портретов | ⚠️ спрайт-анимация (покадровая, ATL) — полностью рабочая и протестированная; Live2D — **экспериментальная best-effort обвязка**, не проверена реальным Live2D-рантаймом (см. ниже) |

Демонстрационный проект: `examples/school_life_demo/` — 3-дневный
календарь, две героини, две ветки по относительному сравнению статов
+ третий маршрут, открывающийся только после прохождения первого
(route-gating), концовки всех трёх категорий, скрытые статы
(`stats_display: "hidden"` — оверлей со счётчиком вообще не
генерируется), одна героиня с покадровой анимацией портрета.

## Архитектура (3 слоя из ТЗ)

```
project.json, characters/, backgrounds/, scenes/, variables/, audio/   (пользовательская модель, JSON)
              │
              ▼  vnstudio.models.load_project()  — парсинг + валидация ссылок
              │
              ▼  vnstudio.codegen.generate_game() — Jinja2-шаблоны → game/*.rpy + раскладка ассетов
              │
              ▼  vnstudio.build.build_pipeline()  — renpy.sh <project> compile / lint / distribute
              │
              ▼  готовый билд (zip/exe) пользователю
```

GUI-слой (этап 4) будет вызывать те же три функции — `load_project`,
`generate_game`, `build_pipeline` — по нажатию "Собрать игру"; он не
дублирует их логику.

## Формат проекта

```
my_project/
  project.json               # {"name", "resolution": [w, h], "language", "start_scene"}
  characters/
    characters.json          # [{"id", "name", "color"}] — только метаданные, не спрайты
    alice_happy.png           # спрайты автоопределяются по имени файла: <id>_<эмоция>.<ext>
    alice_sad.png
  backgrounds/
    backgrounds.json          # необязательно: [{"id", "file"}]; без файла — id = имя файла без расширения
    park.png
  variables/
    variables.json            # [{"name", "type": int|float|bool|str, "default"}]
  audio/
    audio.json                 # необязательно: [{"id", "file", "type": "music"|"sfx"}]
    theme.ogg
  scenes/
    scene_intro.json           # граф узлов одной сцены (см. ниже)

  # ниже — необязательные каталоги для school-life / dating sim механик
  calendar/
    calendar.json               # {"day_names", "slots", "day_count", "on_end"?}
  locations/
    locations.json               # [{"id", "name", "background"?, "available_slots"?}]
  schedule/
    events.json                   # [{"id", "location", "scene", "day", "slot", "once", "priority", "condition"?}]
  routes/
    routes.json                    # [{"id", "name", "start_scene", "requires"?, "condition"?}]
```

### Граф сцены

Узел одного из трёх типов — это и есть "конструктор условий через
выпадающие списки" из ТЗ на уровне данных (GUI над ним рисует сам
выпадающий список):

```json
{
  "id": "scene_intro",
  "background": "park",
  "music": "theme",
  "start": "n1",
  "nodes": [
    {"id": "n1", "type": "dialogue", "character": "alice", "emotion": "happy",
     "text": "Привет!", "next": "n2"},

    {"id": "n2", "type": "choice", "text": "Что ответить?", "options": [
        {"text": "Привет!", "next": "n3",
         "effects": [{"var": "affection_alice", "op": "+=", "value": 10}]},
        {"text": "...", "next": "n3"}
    ]},

    {"id": "n3", "type": "condition",
     "condition": {"var": "affection_alice", "op": ">", "value": 5},
     "then": "@scene_good", "else": "@scene_bad"}
  ]
}
```

- `next` / `then` / `else`, равный `null`, завершает сцену (`return`).
- Значение вида `"@другая_сцена"` — переход в другую сцену (граф в духе
  Twine, а не просто линейная лента: сцены — узлы более высокого уровня).
- `dialogue` без `"character"` — реплика рассказчика.

Прогрессивное раскрытие сложности (см. "Известное ограничение" в ТЗ) на
уровне модели уже заложено: `condition` — это один визуальный
конструктор (`var op value`), которого хватает на большинство веток; для
редких сложных случаев в будущем можно добавить необязательное поле
`expr` с упрощённым выражением, транслируемым тем же генератором, не
трогая остальную схему.

#### Относительное сравнение статов (`compare_var`)

Условие может сравнивать переменную не только с константой, но и с
**другой переменной** — вместо `"value"` указывается `"compare_var"`:

```json
{"var": "affection_alice", "op": ">", "compare_var": "affection_beth"}
```

Именно так в Fate/stay night решается, чей маршрут запускается — не
`"очки Рин > 50"`, а `"очки Рин > очки Сейбер"` (см. раздел "Маршруты"
ниже). Ровно одно из `value`/`compare_var` должно присутствовать —
конструктор условий в GUI это будет одним переключателем "число ↔
другой стат".

#### Узел "концовка" (`ending`)

Отдельный тип узла для многоуровневых концовок (bad/normal/true, как в
Fate/stay night — множество Bad End, один "лучший по мнению автора"
Good/Normal End и один "канонiчный" True End):

```json
{"id": "n9", "type": "ending", "category": "true", "route": "route_alice", "title": "СВОБОДА"}
```

- `category` — `"bad"` / `"normal"` / `"true"`. Движок сам генерирует
  экран под категорию (крупная надпись "BAD END"/"NORMAL END"/"TRUE
  END" своим цветом, остановка музыки, пауза) — автору не нужно вручную
  вёрстать экран для каждой концовки.
- `title` — необязательно, переопределяет стандартный текст ("СВОБОДА"
  вместо "TRUE END").
- `route` — необязательно, id маршрута из `routes/routes.json`;
  прохождение этой концовки засчитывает маршрут пройденным
  (`persistent`, переживает перезапуск игры) — на этом строится
  route-gating (см. ниже).

## Маршруты (routes) — авто-расчёт по итоговым статам

`routes/routes.json` — список маршрутов, среди которых движок сам (без
меню, без участия игрока) выбирает подходящий по итоговым статам, когда
граф сцены или календарь доходит до `"@resolve_routes"`:

```json
[
  {"id": "route_alice", "name": "Маршрут Алисы", "start_scene": "scene_alice_start",
   "condition": {"var": "affection_alice", "op": ">", "compare_var": "affection_beth"}},

  {"id": "route_beth", "name": "Маршрут Бет", "start_scene": "scene_beth_start",
   "condition": {"var": "affection_beth", "op": ">", "compare_var": "affection_alice"}},

  {"id": "route_true", "name": "Истинный маршрут", "start_scene": "scene_true_start",
   "requires": "route_alice"}
]
```

Алгоритм (`label resolve_routes:` в сгенерированном `routes.rpy`):
берётся первый маршрут в списке, для которого одновременно верно:
`requires` пуст или уже пройден (`persistent`), маршрут ещё не пройден
сам, и `condition` (если задано) истинно. Это напрямую покрывает две
разные вещи из ТЗ одним механизмом:

- **выбор среди одновременно доступных маршрутов** — через `condition`
  с `compare_var` (кто из героинь набрал больше симпатии);
- **последовательная разблокировка больших веток** (route-gating,
  `Prologue → Fate → UBW → Heaven's Feel` — "каждый маршрут открывает
  следующий") — через `requires`: маршрут `route_true` в примере выше
  недостижим, пока не пройден (на *отдельном* прохождении игры)
  `route_alice`; `persistent` целенаправленно выбран вместо обычной
  переменной, так как это состояние должно переживать перезапуск игры,
  как в реальных многопроходных VN.

Сослаться на точку, где считаются маршруты, можно из графа сцены как на
обычную сцену: `"next": "@resolve_routes"`.

## Календарь / тайм-слоты / локации / расписание

Три файла образуют "школьный" геймплейный цикл: день недели + время
суток определяют, какие локации доступны и что там происходит.

```json
// calendar/calendar.json
{"day_names": ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"], "slots": ["Утро","День","Вечер"], "day_count": 14}
```

```json
// locations/locations.json — хаб, который видит игрок каждый тайм-слот
[{"id": "school", "name": "Школа", "background": "classroom", "available_slots": ["Утро","День"]},
 {"id": "park", "name": "Парк", "background": "park"}]
```

```json
// schedule/events.json — что происходит при посещении локации в конкретный (день, слот)
[{"id": "ev1", "location": "school", "scene": "scene_confession", "day": 3, "slot": "День",
  "once": true, "priority": 1, "condition": {"var": "affection_alice", "op": ">=", "value": 30}}]
```

- `available_slots` у локации — она пропадает из меню хаба в
  недоступные тайм-слоты (например, школа закрыта вечером).
- `day`/`slot` события — конкретный день (0-based) / имя слота, либо
  `"any"` для повторяющихся событий.
- Несколько событий могут претендовать на один и тот же (день, слот,
  локация) — побеждает совпавшее `condition` с наибольшим `priority`.
- `once: true` — событие срабатывает не больше одного раза за игру.
- Когда календарь доходит до `day_count`, он прыгает в `calendar.on_end`
  (id сцены) или, если оно не задано, в `"@resolve_routes"` — то есть
  календарь и маршруты состыкованы "из коробки".

Сослаться на вход в хаб можно так же, как на любую сцену:
`"next": "@calendar_loop"`.

## Скрытая система очков ("hidden flags" режим)

У переменной есть `"visible": true|false` (по умолчанию `true`), а у
проекта — `"stats_display": "bar" | "hidden"` (по умолчанию `"bar"`).
Это ровно тот переключаемый режим конструктора статов, который в ТЗ
описан на примере Fate/stay night — очки Рин/Сейбер считаются в фоне и
никогда не показываются игроку:

- `stats_display: "bar"` — генерируется оверлей-экран (`stats.rpy`) со
  всеми переменными, у которых `visible: true`; игрок видит статы
  как в западных dating sim ("Affection: 65/100").
- `stats_display: "hidden"` — оверлей **не генерируется вообще**, вне
  зависимости от `visible` у отдельных переменных; статы по-прежнему
  считаются и участвуют в `condition`/маршрутах — игрок не
  минимаксит, а исследует, как в японской VN-традиции.

`examples/school_life_demo/` использует именно `"hidden"`.

## Анимация персонажей: спрайты и Live2D

Улучшение относительно статичных портретов Ren'Py — два независимых
механизма, автор выбирает по факту наличия ассетов:

**Покадровая спрайт-анимация** (полностью реализована и протестирована)
— автоопределяется по имени файла, как и обычные портреты, но с
номером кадра в конце: `alice_happy_1.png`, `alice_happy_2.png`, ... →
генерируется ATL-цикл (`show`/пауза/`repeat`). Частота кадров —
необязательное `"animation": {"type": "sprite", "fps": 2}` в
`characters.json` (по умолчанию 2 fps).

**Live2D** (`"animation": {"type": "live2d", "model": "rin/rin.model3.json",
"motions": {"happy": "Idle_Happy"}}`) — генерирует
`image rin happy = Live2D("characters/rin/rin.model3.json", motion_group="Idle_Happy")`
на каждую эмоцию из `motions`, и копирует папку с моделью целиком (все
файлы `.moc3`/текстуры рядом с `.model3.json`) в `game/images/characters/`.

⚠️ **Это экспериментальная, best-effort обвязка.** Ren'Py поддерживает
Live2D лицензированным рантаймом, версия API `Live2D(...)`
(в т.ч. поддержка `motion_group`) отличается между версиями Ren'Py, и
у нас нет доступа к Live2D SDK/рантайму в этом окружении, чтобы
собрать и запустить реальный проект с Live2D-моделью — проверен только
факт генерации корректного по синтаксису `image`-объявления
(`tests/test_codegen_advanced.py::TestLive2DWiring`). Перед релизом с
Live2D обязательно проверьте вручную под своей версией Ren'Py.

## Использование (CLI — временный интерфейс до GUI)

```bash
pip install -e .

# Только сгенерировать .rpy-проект, без вызова Ren'Py:
python -m vnstudio codegen examples/dating_sim_demo -o /tmp/vn_out

# School-life демо с календарём, маршрутами, скрытыми статами и анимацией:
python -m vnstudio codegen examples/school_life_demo -o /tmp/vn_school

# Полная сборка (нужен скачанный Ren'Py SDK, см. ниже):
python -m vnstudio build examples/dating_sim_demo -o /tmp/vn_out --renpy-sdk /path/to/renpy-8.x-sdk
```

## Как проверить полную сборку (compile → lint → distribute)

В этом окружении нет Ren'Py SDK и сети для его загрузки, поэтому
`vnstudio.build` проверен только на некорректных входах (нет
`renpy.sh`/`renpy.exe` → понятная ошибка `RenpySDKNotFound`) — реальный
`compile`/`lint`/`distribute` не запускался. Чтобы проверить у себя:

1. Скачать Ren'Py SDK: https://www.renpy.org/latest.html
2. `python -m vnstudio build examples/dating_sim_demo -o /tmp/vn_out --renpy-sdk /путь/к/renpy-sdk`
3. Убедиться, что `/tmp/vn_out` открывается и запускается лаунчером Ren'Py, а `distribute` кладёт архив/exe в `/tmp/vn_out/dists/`.

## Тесты

```bash
python -m unittest discover -s tests -v
```

Зависимостей для тестов не требуется (только stdlib) — специально, чтобы
не тянуть `pytest`/`jsonschema` в минимальную установку конечного
пользователя. `test_models_advanced.py`/`test_codegen_advanced.py`
покрывают именно school-life/dating sim механики: маршруты (в т.ч. цикл
в `requires`, относительное сравнение статов), календарь/расписание,
ending-узлы, скрытые статы, спрайт-анимацию и Live2D-обвязку.

## Решение по стеку GUI (этап 4, ещё не реализован)

Открытый вопрос из ТЗ — **Python + PySide6/Qt**, а не Electron/Tauri+React:

- Codegen- и build-слои уже на Python и работают с файловой системой и
  `subprocess` напрямую — PySide6 использует тот же процесс и интерпретатор,
  без IPC/сериализации между UI и пайплайном сборки.
- Node-граф сцен (в духе Twine) и live-preview диалога отлично ложатся на
  `QGraphicsView`/`QGraphicsScene` (drag&drop узлов, связи-стрелки, зум) —
  готовый примитив под нужный UI, не более сложный, чем эквивалент на web-canvas.
- Дистрибуция для нетехнического пользователя проще: `PyInstaller`
  собирает один exe/app, не нужно тащить рантайм Node/Chromium (Electron)
  или Rust-тулчейн (Tauri) отдельно от Python-пайплайна, который и так
  нужен для вызова Ren'Py CLI.
- Минус — Qt Widgets/QML менее гибки визуально, чем React, но для
  редактора с формами, деревом сцен и превью это не критично; сложные вещи
  (условия, статы) и так закрываются простыми виджетами (выпадающие
  списки, спинбоксы), а не богатой вёрсткой.

Следующий шаг для этапа 4: мастер создания проекта (шаблоны "линейная VN"
/ "симулятор свиданий") → менеджер персонажей/фонов (drag&drop файлов в
`characters/`/`backgrounds/`, с автоопределением спрайтов, которое уже
есть в `models.py`) → node-граф сцен на `QGraphicsScene` → кнопка "Собрать
игру", вызывающая `codegen.generate_game` + `build.build_pipeline`.
