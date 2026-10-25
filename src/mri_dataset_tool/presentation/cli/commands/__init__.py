"""CLI commands: each module exposes ``add_parser(subparsers)`` (which sets ``run`` with
``set_defaults``) and ``run(args) -> int``; register it in ``main.COMMANDS``."""
