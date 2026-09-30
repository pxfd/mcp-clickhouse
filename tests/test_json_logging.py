"""Every log line must be a single parseable JSON object."""

import json
import logging
import unittest

from mcp_clickhouse.json_logging import JsonFormatter


class TestJsonFormatter(unittest.TestCase):
    def _emit(self, **kwargs):
        logger = logging.getLogger("test-json-logging")
        record = logger.makeRecord(
            logger.name, logging.INFO, "mcp_server.py", 42, "hello %s", ("world",), None, **kwargs
        )
        line = JsonFormatter().format(record)
        self.assertNotIn("\n", line)
        return json.loads(line)

    def test_core_fields(self):
        payload = self._emit()
        self.assertEqual(payload["message"], "hello world")
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "test-json-logging")
        self.assertEqual(payload["file"], "mcp_server.py:42")
        self.assertRegex(payload["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    def test_extras_are_promoted_to_top_level_fields(self):
        payload = self._emit(extra={"query_id": "abc-123", "rows": 7})
        self.assertEqual(payload["query_id"], "abc-123")
        self.assertEqual(payload["rows"], 7)

    def test_multiline_message_and_traceback_stay_on_one_line(self):
        try:
            raise ValueError("boom\nsecond line")
        except ValueError:
            record = logging.getLogger("test-json-logging").makeRecord(
                "test-json-logging",
                logging.ERROR,
                "mcp_server.py",
                1,
                "failed:\nmultiline",
                (),
                __import__("sys").exc_info(),
            )
        line = JsonFormatter().format(record)
        self.assertNotIn("\n", line)
        payload = json.loads(line)
        self.assertIn("Traceback", payload["exception"])
        self.assertEqual(payload["message"], "failed:\nmultiline")

    def test_already_json_message_becomes_fields_not_an_escaped_blob(self):
        """fastmcp's StructuredLoggingMiddleware hands logging a JSON string."""
        inner_payload = json.dumps(
            {"name": "run_query", "arguments": {"query": "SELECT 1 WHERE s = 'a'"}}
        )
        message = json.dumps(
            {
                "event": "request_start",
                "method": "tools/call",
                "payload": inner_payload,
                "payload_type": "CallToolRequestParams",
            }
        )
        logger = logging.getLogger("fastmcp.middleware.structured_logging")
        record = logger.makeRecord(logger.name, logging.INFO, "logging.py", 122, message, (), None)
        payload = json.loads(JsonFormatter().format(record))

        self.assertEqual(payload["event"], "request_start")
        self.assertEqual(payload["method"], "tools/call")
        # Both layers unwrapped: a real object, reachable as log.payload.arguments.query
        self.assertEqual(payload["payload"]["name"], "run_query")
        self.assertEqual(payload["payload"]["arguments"]["query"], "SELECT 1 WHERE s = 'a'")
        self.assertNotIn("message", payload)

    def test_nested_payload_cannot_overwrite_core_fields(self):
        logger = logging.getLogger("test-json-logging")
        message = json.dumps({"level": "TRACE", "logger": "spoofed", "event": "x"})
        record = logger.makeRecord(
            logger.name, logging.ERROR, "mcp_server.py", 1, message, (), None
        )
        payload = json.loads(JsonFormatter().format(record))

        self.assertEqual(payload["level"], "ERROR")
        self.assertEqual(payload["logger"], "test-json-logging")
        self.assertEqual(payload["event"], "x")

    def test_plain_messages_are_left_alone(self):
        for message in ("[warn] not json", "{not json}", "null", "42", '{"a": 1'):
            with self.subTest(message=message):
                logger = logging.getLogger("test-json-logging")
                record = logger.makeRecord(logger.name, logging.INFO, "f.py", 1, message, (), None)
                payload = json.loads(JsonFormatter().format(record))
                self.assertEqual(payload["message"], message)

    def test_non_serializable_extra_falls_back_to_str(self):
        payload = self._emit(extra={"client": object()})
        self.assertIn("object", payload["client"])


if __name__ == "__main__":
    unittest.main()
