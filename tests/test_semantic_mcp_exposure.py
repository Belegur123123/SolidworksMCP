import asyncio
import unittest

from mcp import types

from solidworks_mcp.server import list_tools, server
from solidworks_mcp import tool_registry


SEMANTIC_TOOL_NAMES = {
    "register_body_identity",
    "resolve_body_identity",
    "list_body_identities",
    "semantic_extrude",
    "semantic_cut",
}


class SemanticMcpExposureTests(unittest.TestCase):
    def _tools_by_name(self):
        tools = asyncio.run(list_tools())
        return {tool.name: tool for tool in tools}

    def _populate_low_level_tool_cache(self):
        """Exercise the real MCP ListTools request wrapper.

        Calling the decorated ``list_tools`` function directly intentionally
        bypasses mcp.server.lowlevel.Server's request wrapper.  The wrapper is
        what refreshes ``server._tool_cache`` for real MCP ListTools requests,
        so a cache-boundary regression test must invoke the registered request
        handler rather than the undecorated callback.
        """
        handler = server.request_handlers[types.ListToolsRequest]
        asyncio.run(handler(types.ListToolsRequest()))

    def test_server_list_tools_exposes_all_semantic_identity_tools(self):
        tools = self._tools_by_name()
        self.assertTrue(
            SEMANTIC_TOOL_NAMES.issubset(tools),
            f"Missing semantic MCP tools: {sorted(SEMANTIC_TOOL_NAMES - set(tools))}",
        )

    def test_low_level_server_cache_contains_semantic_identity_tools(self):
        # The SDK cache is lazy: it is populated by the registered ListTools
        # request wrapper, not by calling our decorated callback directly.
        self._populate_low_level_tool_cache()
        cache = getattr(server, "_tool_cache", {})
        self.assertTrue(
            SEMANTIC_TOOL_NAMES.issubset(cache),
            f"Missing semantic tools from low-level MCP cache: "
            f"{sorted(SEMANTIC_TOOL_NAMES - set(cache))}",
        )

    def test_semantic_tool_schemas_are_callable_without_legacy_name_scope(self):
        tools = self._tools_by_name()

        register = tools["register_body_identity"].inputSchema
        self.assertIn("body_id", register["properties"])
        self.assertIn("body_id", register["required"])

        semantic_cut = tools["semantic_cut"].inputSchema
        self.assertIn("scope_body_ids", semantic_cut["properties"])
        self.assertIn("scope_body_ids", semantic_cut["required"])
        self.assertNotIn("scope_bodies", semantic_cut["properties"])

        semantic_extrude = tools["semantic_extrude"].inputSchema
        self.assertIn("body_id", semantic_extrude["properties"])
        self.assertIn("body_id", semantic_extrude["required"])

    def test_registry_and_server_manifest_are_consistent(self):
        server_names = set(self._tools_by_name())
        self.assertTrue(SEMANTIC_TOOL_NAMES.issubset(tool_registry.NEW_TOOL_NAMES))
        self.assertTrue(SEMANTIC_TOOL_NAMES.issubset(server_names))

        self.assertIn("register_body_identity", tool_registry.MUTATING_TOOLS)
        self.assertIn("semantic_extrude", tool_registry.MUTATING_TOOLS)
        self.assertIn("semantic_cut", tool_registry.MUTATING_TOOLS)
        self.assertNotIn("resolve_body_identity", tool_registry.MUTATING_TOOLS)
        self.assertNotIn("list_body_identities", tool_registry.MUTATING_TOOLS)


if __name__ == "__main__":
    unittest.main()
