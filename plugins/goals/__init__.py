"""Goals plugin — native personal/project goal tracking.

Registers the ``hermes goals`` CLI subcommand via the plugin API
(``ctx.register_cli_command``) instead of patching ``hermes_cli/main.py``.

The main.py subcommand-registration block was the *only* file that conflicted on
every upstream merge (our ``goals`` entry vs upstream's constant churn in the
same parser/frozenset region). Moving registration into this plugin drops the
CLI-core conflict surface to zero — upstream never ships a ``plugins/goals/``
directory, so this stays additive and always merges clean. The command logic
itself still lives in ``hermes_cli/goaltrack.py``; this only wires it up.
"""

from __future__ import annotations


def register(ctx) -> None:
    from hermes_cli.goaltrack import setup_parser, goals_command

    ctx.register_cli_command(
        name="goals",
        help="Personal and project goal tracking (hermes goals …)",
        setup_fn=setup_parser,
        handler_fn=goals_command,
        description=(
            "Create and track goals stored in ~/.hermes/goals.db. "
            "Goals are independent of any dashboard and readable by all skills."
        ),
    )
