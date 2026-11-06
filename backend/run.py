"""Start the API server.

    python run.py            # http://127.0.0.1:8030  (docs at /docs)

On Linux you can also run `uvicorn app.main:app` directly. This wrapper exists
because psycopg's async mode needs a selector event loop, and Windows uses a
different default.
"""
import asyncio
import os
import sys

import uvicorn


def main():
    config = uvicorn.Config("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8030")))
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
