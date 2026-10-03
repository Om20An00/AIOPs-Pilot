"""Thin wrapper so agents call tools through an MCP ClientSession (not by importing the data directly)."""
import json


class MCPTools:
    def __init__(self, session):
        self.session = session

    async def call(self, name: str, **arguments) -> dict:
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(f"MCP tool {name} failed: {result.content}")
        if getattr(result, "structuredContent", None):
            data = result.structuredContent
            return data["result"] if set(data) == {"result"} else data
        return json.loads(result.content[0].text)
