#!/usr/bin/env python3

import json
import logging
import sqlglot

from fastmcp.server.middleware import Middleware, MiddlewareContext, CallNext
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.exceptions import ToolError

from sqlglot import exp

from typing import List

logger = logging.getLogger("pxfd-middleware")


class ToolCallValidatorMiddleware(Middleware):
    """Middleware that validates tool calls."""
    
    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> any:
        """Validate tool calls before proceeding."""

        validated_tools: List[str] = ["run_query"]
        tool_name = context.message.name
        args = context.message.arguments

        if tool_name in validated_tools:
            logger.info(f"{tool_name} needs validation. Validating..")

            query = args.get("query", "")
            timestamp_columns: set = {"created_at", "updated_at", "timestamp"}

            logger.info(f"Validating query: {query}")
            if not query:
                logger.error("No query provided for validation.")
                raise ToolError("No query provided for validation.")

            sql_tree = sqlglot.parse_one(query, dialect="clickhouse")
            where_clause = sql_tree.find(exp.Where)

            if not where_clause:
                logger.error("Query validation failed: No WHERE clause found.")
                raise ToolError("Query validation failed: No WHERE clause found.")

            if not any(col.name in timestamp_columns for col in where_clause.find_all(exp.Column)):
                logger.error("Query validation failed: No timestamp columns found in WHERE clause.")
                raise ToolError(
                    """
                        Query validation failed: No timestamp columns found in WHERE clause.
                        Instructions for the AGENT: Do NOT try to override this validation.
                        Inform user about this and provide sensible options to use in the query.
                    """
                    )

        result = await call_next(context)
        return result


def setup_middleware(mcp):
    """
    Setup function called by the MCP server to register middleware.
    
    Args:
        mcp: The FastMCP instance
    """
    logger.info("Setting up PXFD middleware")
    
    # Add audit middleware
    mcp.add_middleware(StructuredLoggingMiddleware(
        include_payloads=True,
    ))
    logger.info("Added StructuredLoggingMiddleware")
    
    # Add tool call validation middleware
    mcp.add_middleware(ToolCallValidatorMiddleware())
    logger.info("Added ToolCallValidatorMiddleware")
    
    logger.info("PXFD middleware setup complete")
