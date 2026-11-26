"""python -m sentinel.cli create-user <name> <role>
python -m sentinel.cli serve
python -m sentinel.cli inspect <command> [args...]   # MCP-marketplace onboarding: list a server's tools BEFORE trusting it"""
import getpass, sys
from .config import DATA_DIR
from .security import UserStore

def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "create-user":
        UserStore(DATA_DIR / "users.json").create(sys.argv[2], getpass.getpass("password (>=12 chars): "), sys.argv[3])
        print("created", sys.argv[2], sys.argv[3])
    elif sys.argv[1:2] == ["serve"]:
        import uvicorn
        uvicorn.run("sentinel.api:app", host="127.0.0.1", port=8443)   # localhost only; put a TLS proxy in front for remote use
    elif sys.argv[1:2] == ["inspect"] and len(sys.argv) >= 3:
        import asyncio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def look():
            params = StdioServerParameters(command=sys.argv[2], args=sys.argv[3:])
            async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
                await s.initialize()
                for t in (await s.list_tools()).tools:
                    print(f"- {t.name}: {(t.description or '').strip().splitlines()[0] if t.description else ''}")
            print("\nReview these. Then add the server to MCP_REGISTRY with trusted=True and pinned_tools={...}.")
        asyncio.run(look())
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
