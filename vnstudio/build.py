"""Headless-обвязка над Ren'Py CLI: compile -> lint -> distribute.

Ren'Py SDK не входит в этот репозиторий (это отдельный, довольно большой
дистрибутив от разработчиков Ren'Py) — пользователь инструмента должен либо
указать путь к уже скачанному SDK (--renpy-sdk), либо переменную окружения
RENPY_SDK. Сам vnstudio ничего не скачивает и не подменяет SDK.

Официальный headless-интерфейс — скрипт `renpy.sh`/`renpy.exe` в корне SDK,
вызываемый как `renpy.sh <project_dir> <command> [args]`. См. документацию
Ren'Py: "Command Line" / "Building Distributions".
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path


class RenpySDKNotFound(RuntimeError):
    pass


class RenpyBuildError(RuntimeError):
    def __init__(self, step: str, returncode: int, output: str):
        super().__init__(f"Ren'Py '{step}' завершился с кодом {returncode}:\n{output}")
        self.step = step
        self.returncode = returncode
        self.output = output


@dataclass
class BuildResult:
    project_root: Path  # каталог, переданный в Ren'Py (родитель game/)
    steps: list[str]
    output: dict[str, str]


def find_renpy_launcher(sdk_path: str | Path | None = None) -> Path:
    """Находит исполняемый файл headless-запуска Ren'Py внутри SDK."""
    candidates: list[Path] = []
    if sdk_path is not None:
        candidates.append(Path(sdk_path))
    env_sdk = os.environ.get("RENPY_SDK")
    if env_sdk:
        candidates.append(Path(env_sdk))

    exe_name = "renpy.exe" if platform.system() == "Windows" else "renpy.sh"
    for sdk in candidates:
        launcher = sdk / exe_name
        if launcher.exists():
            return launcher

    raise RenpySDKNotFound(
        "Не найден Ren'Py SDK. Укажите путь через --renpy-sdk или переменную окружения "
        f"RENPY_SDK (ожидается файл '{exe_name}' в корне SDK). "
        "Скачать SDK: https://www.renpy.org/latest.html"
    )


def _run(launcher: Path, project_root: Path, *args: str) -> str:
    cmd = [str(launcher), str(project_root), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RenpyBuildError(step=" ".join(args), returncode=proc.returncode, output=output)
    return output


def compile_project(launcher: Path, project_root: Path) -> str:
    """`renpy.sh <project> compile` — проверка синтаксиса и байткомпиляция .rpy."""
    return _run(launcher, project_root, "compile")


def lint_project(launcher: Path, project_root: Path) -> str:
    """`renpy.sh <project> lint` — статическая проверка скрипта (не только синтаксис)."""
    return _run(launcher, project_root, "lint")


def distribute_project(launcher: Path, project_root: Path, destination: Path | None = None) -> str:
    """`renpy.sh <project> distribute` — сборка готового пакета (zip/exe/...)."""
    args = ["distribute"]
    if destination is not None:
        args += ["--destination", str(destination)]
    return _run(launcher, project_root, *args)


def build_pipeline(
    project_root: Path,
    sdk_path: str | Path | None = None,
    destination: Path | None = None,
    skip_distribute: bool = False,
) -> BuildResult:
    """Полный headless-пайплайн: compile -> lint -> (distribute).

    project_root — каталог, СОДЕРЖАЩИЙ game/ (то есть output_dir из
    codegen.generate_game), не сам game/.
    """
    launcher = find_renpy_launcher(sdk_path)
    output: dict[str, str] = {}
    steps: list[str] = []

    output["compile"] = compile_project(launcher, project_root)
    steps.append("compile")

    output["lint"] = lint_project(launcher, project_root)
    steps.append("lint")

    if not skip_distribute:
        output["distribute"] = distribute_project(launcher, project_root, destination)
        steps.append("distribute")

    return BuildResult(project_root=project_root, steps=steps, output=output)
