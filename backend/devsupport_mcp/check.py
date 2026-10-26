import asyncio
import json
import sys

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main():
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m devsupport_mcp.check "
            "req_<32 hex chars>"
        )

    async with asyncio.timeout(15):
        async with httpx2.AsyncClient(
            trust_env=False,
            timeout=15,
        ) as http:
            transport = streamable_http_client(
                "http://127.0.0.1:8012/mcp",
                http_client=http,
            )

            async with Client(transport) as client:
                success = await check(client)

    if not success:
        raise SystemExit("MCP tool call failed.")


async def check(client):
    tools = await client.list_tools()
    print("tools:", [tool.name for tool in tools.tools])

    result = await client.call_tool(
        "get_request_log",
        {"request_id": sys.argv[1]},
    )

    if result.is_error:
        for block in result.content:
            if block.type == "text":
                print(block.text)
        return False

    print(json.dumps(
        result.structured_content,
        ensure_ascii=False,
        indent=2,
    ))
    return True


if __name__ == "__main__":
    asyncio.run(main())