"""Call the Väre MCP server like an agent would, over streamable HTTP.

    python scripts/mcp_smoke.py                       # http://localhost:8000/mcp
    python scripts/mcp_smoke.py https://helppox.com/vare/mcp
"""

import asyncio
import json
import sys

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp"


def show(label, result):
    data = result.structured_content if result.structured_content is not None else \
        [getattr(c, "text", c) for c in result.content]
    print(f"\n== {label}{'  (ERROR)' if result.is_error else ''}")
    print(json.dumps(data, indent=1, ensure_ascii=False)[:1800])


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    async with streamable_http_client(URL) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("server:", init.server_info.name, init.server_info.version)
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            show("qloo_profile The Bear", await session.call_tool(
                "qloo_profile", {"name": "The Bear", "entity_type": "tv_show"}))
            show("qloo_related The Substance -> movie", await session.call_tool(
                "qloo_related", {"name": "The Substance", "entity_type": "movie", "related_type": "movie", "take": 6}))
            show("create_tags", await session.call_tool("create_tags", {
                "text": "Finally watched The Substance with my wife. The director clearly has seen her Kubrick "
                        "movies. Also many references to Icarus, Cinderella, movie Limitless etc.",
                "destination": "instagram"}))
            show("suggest_topics", await session.call_tool("suggest_topics", {
                "text": "Binged the new season of The Bear in two nights. Jeremy Allen White deserves every award."}))


if __name__ == "__main__":
    asyncio.run(main())
