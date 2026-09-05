"""Командная строка vnstudio — временный интерфейс, пока не готов GUI (этап 4).

    python -m vnstudio codegen <project_dir> -o <output_dir>
    python -m vnstudio build   <project_dir> -o <output_dir> --renpy-sdk <sdk_dir> [--skip-distribute]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vnstudio.build import RenpyBuildError, RenpySDKNotFound, build_pipeline
from vnstudio.codegen import generate_game
from vnstudio.models import ProjectValidationError, load_project


def cmd_codegen(args: argparse.Namespace) -> int:
    bundle = load_project(args.project_dir)
    game_dir = generate_game(bundle, args.output)
    print(f"Проект '{bundle.meta.name}' сгенерирован в {game_dir}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    bundle = load_project(args.project_dir)
    generate_game(bundle, args.output)
    result = build_pipeline(
        project_root=args.output,
        sdk_path=args.renpy_sdk,
        skip_distribute=args.skip_distribute,
    )
    print(f"Готово: {', '.join(result.steps)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vnstudio")
    sub = parser.add_subparsers(dest="command", required=True)

    p_codegen = sub.add_parser("codegen", help="сгенерировать .rpy-проект без сборки")
    p_codegen.add_argument("project_dir", type=Path)
    p_codegen.add_argument("-o", "--output", type=Path, required=True)
    p_codegen.set_defaults(func=cmd_codegen)

    p_build = sub.add_parser("build", help="codegen + compile + lint + distribute")
    p_build.add_argument("project_dir", type=Path)
    p_build.add_argument("-o", "--output", type=Path, required=True)
    p_build.add_argument("--renpy-sdk", type=Path, default=None)
    p_build.add_argument("--skip-distribute", action="store_true")
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ProjectValidationError as exc:
        print(f"Ошибка в проекте: {exc}", file=sys.stderr)
        return 1
    except (RenpySDKNotFound, RenpyBuildError) as exc:
        print(f"Ошибка сборки: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
