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

## Использование (CLI — временный интерфейс до GUI)

```bash
pip install -e .

# Только сгенерировать .rpy-проект, без вызова Ren'Py:
python -m vnstudio codegen examples/dating_sim_demo -o /tmp/vn_out

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
пользователя.

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
