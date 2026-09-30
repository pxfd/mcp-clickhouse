"""Server instructions pointing to official ClickHouse Agent Skills, plus optional deployment-specific text."""

from typing import Optional

CLICKHOUSE_SERVER_INSTRUCTIONS = """\
When working on ClickHouse-related coding, schema design, SQL/query optimization,
data migrations, or troubleshooting, consider using the official ClickHouse Agent
Skills: https://github.com/ClickHouse/agent-skills

Install with:
npx -y skills add clickhouse/agent-skills --all
"""


def build_server_instructions(extra: Optional[str] = None) -> str:
    """Return the default instructions, followed by deployment-specific ones if given."""
    if not extra:
        return CLICKHOUSE_SERVER_INSTRUCTIONS
    return f"{CLICKHOUSE_SERVER_INSTRUCTIONS}\n{extra}\n"
