import os
import unittest
from unittest.mock import patch

from mcp_clickhouse.mcp_env import MCPServerConfig, get_mcp_config
from mcp_clickhouse.mcp_server import mcp
from mcp_clickhouse.skills_advisor import (
    CLICKHOUSE_SERVER_INSTRUCTIONS,
    build_server_instructions,
)


class TestSkillsAdvisorInstructions(unittest.TestCase):
    def test_server_instructions_are_configured(self):
        self.assertIsInstance(mcp.instructions, str)
        self.assertTrue(mcp.instructions.strip())
        self.assertEqual(
            mcp.instructions, build_server_instructions(get_mcp_config().server_instructions)
        )

    def test_instructions_mention_skills_repo_and_install_hint(self):
        self.assertIn("github.com/ClickHouse/agent-skills", mcp.instructions)
        self.assertIn("skills add clickhouse/agent-skills", mcp.instructions)


class TestBuildServerInstructions(unittest.TestCase):
    def test_default_without_extra(self):
        self.assertEqual(build_server_instructions(None), CLICKHOUSE_SERVER_INSTRUCTIONS)
        self.assertEqual(build_server_instructions(""), CLICKHOUSE_SERVER_INSTRUCTIONS)

    def test_extra_is_appended_after_default(self):
        result = build_server_instructions("Always filter by timestamp.")
        self.assertTrue(result.startswith(CLICKHOUSE_SERVER_INSTRUCTIONS))
        self.assertTrue(result.endswith("Always filter by timestamp.\n"))


class TestServerInstructionsEnv(unittest.TestCase):
    def test_unset_returns_none(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLICKHOUSE_SERVER_INSTRUCTIONS", None)
            self.assertIsNone(MCPServerConfig().server_instructions)

    def test_blank_returns_none(self):
        with patch.dict(os.environ, {"CLICKHOUSE_SERVER_INSTRUCTIONS": "  \n "}):
            self.assertIsNone(MCPServerConfig().server_instructions)

    def test_value_is_stripped_and_keeps_newlines(self):
        with patch.dict(os.environ, {"CLICKHOUSE_SERVER_INSTRUCTIONS": "\nline one\nline two\n"}):
            self.assertEqual(MCPServerConfig().server_instructions, "line one\nline two")


if __name__ == "__main__":
    unittest.main()
