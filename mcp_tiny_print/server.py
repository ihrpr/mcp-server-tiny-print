#!/usr/bin/env python3
"""
MCP Tiny Print Server
A Model Context Protocol server that provides markdown printing functionality
via thermal printer over Bluetooth.
"""

import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP, Context

from .printer import TinyPrinter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global printer instance
printer_instance = None

# Create the MCP server
mcp = FastMCP("Tiny Print")


async def init_printer():
    """Initialize printer connection on server start"""
    global printer_instance
    if printer_instance is None:
        printer_instance = TinyPrinter()
        if not await printer_instance.find_and_connect():
            raise RuntimeError("Failed to connect to PPG printer")
        logger.info("Printer initialized and connected")


@asynccontextmanager
async def managed_printer():
    """Context manager for printer connection"""
    global printer_instance
    if printer_instance is None:
        await init_printer()

    try:
        yield printer_instance
    except Exception:
        logger.exception(f"Printer operation failed")
        raise


@mcp.tool()
async def print_markdown(markdown_text: str, ctx: Context) -> str:
    """
    Print markdown text to the thermal printer.
    """
    try:
        await ctx.report_progress(0, 2, "Initializing printer...")
        async with managed_printer() as printer:
            assert printer is not None, "Printer not initialized"
            await ctx.report_progress(0, 1, "Printer initialized. Sending data...")
            await printer.print_markdown(markdown_text)
            await ctx.report_progress(0, 2, "Printer initialized")
            return f"Successfully printed markdown text to thermal printer"
    except Exception as e:
        error_msg = f"Failed to print markdown: {str(e)}"
        await ctx.error(error_msg)
        logger.error(error_msg)
        return error_msg


def main():
    """Main entry point for the MCP server"""
    # Run the server
    mcp.run()


if __name__ == "__main__":
    main()
