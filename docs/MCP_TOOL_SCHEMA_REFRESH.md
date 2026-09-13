# MCP tool-schema refresh after adding semantic CAD tools

## Scope

The semantic body-identity architecture adds these MCP tools:

- `register_body_identity`
- `resolve_body_identity`
- `list_body_identities`
- `semantic_extrude`
- `semantic_cut`

The SolidworksMCP server exposes them through `server.list_tools()` and the v6
`NEW_TOOLS` registry. The server-side manifest is the source of truth for MCP
tool exposure.

## Important distinction: server manifest vs client cache

An MCP client can cache the tool schema that was present when the connection or
conversation was initialized. If SolidworksMCP is upgraded while that client
session remains open, the running Python process may contain the new methods and
`server.list_tools()` may return the new tools while the client still presents
an older tool set.

That condition is a client schema-cache issue, not evidence that the server
failed to register the tools.

For acceptance tests, distinguish these layers explicitly:

1. Runtime implementation: inspect `SolidWorksAutomation` methods and MRO.
2. Server MCP manifest: call `server.list_tools()` and confirm the semantic tool
   names and schemas are present.
3. Client-visible manifest: confirm the actual MCP client exposes the same tool
   names for direct invocation.

All three must agree before a direct ChatGPT -> semantic MCP tool acceptance test
is started.

## Refresh procedure

After changing the MCP tool set:

1. Pull the updated branch.
2. Run the unit tests.
3. Restart the SolidworksMCP server process.
4. Reconnect/refresh the MCP client connection. If the host application caches
   tool schemas per conversation, start a fresh conversation after reconnecting.
5. Confirm direct client visibility of the new tools before any CAD mutation.

Do not use `execute_python` as a substitute for a missing direct MCP tool during
an integration acceptance test. It bypasses the interface boundary that the test
is intended to validate.

## Regression coverage

`tests/test_semantic_mcp_exposure.py` calls the real asynchronous
`solidworks_mcp.server.list_tools()` function and verifies that all five semantic
identity tools are exposed with the expected schemas. This protects against a
server-side registration regression independently of any external client's
schema cache.
