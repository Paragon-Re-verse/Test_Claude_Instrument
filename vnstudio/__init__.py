"""vnstudio — no-code слой поверх Ren'Py.

Пакет реализует три слоя из ТЗ:
  vnstudio.models   — модель проекта (Project, Character, Scene graph, ...) и её валидация
  vnstudio.codegen  — генерация .rpy файлов из модели проекта
  vnstudio.build    — headless-обвязка над Ren'Py CLI (compile/lint/distribute)

GUI-редактор (последний этап по ТЗ) сюда не входит — см. README.md, раздел
"Статус реализации".
"""

__version__ = "0.1.0"
