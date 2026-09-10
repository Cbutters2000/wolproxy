import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response
import httpx
from wakeonlan import send_magic_packet

app = FastAPI()

TARGET_MAC = os.getenv("LM_STUDIO_MAC")
TARGET_URL = f"http://{os.getenv('LM_STUDIO_IP')}:{os.getenv('LM_STUDIO_PORT', '1234')}"

client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

# Headers we should NEVER forward (hop-by-hop or connection-specific)
STRIP_HEADERS = [
    "host", "content-length", "transfer-encoding",
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer"
]

def clean_headers(headers: dict) -> dict:
    """Remove headers that shouldn't be forwarded."""
    return {k.lower(): v for k, v in headers.items() if k.lower() not in STRIP_HEADERS}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, path: str):
    # 1. Wake up the machine! ⚡️
    if TARGET_MAC:
        try:
            send_magic_packet(TARGET_MAC)
        except Exception as e:
            print(f"WoL Error: {e}")

    # Clean the path to avoid double slashes 🥖
    clean_path = path.lstrip("/")

    if clean_path:
        url = f"{TARGET_URL}/{clean_path}"
    else:
        url = TARGET_URL

    body = await request.body()

    # Sanitize incoming headers 🧹
    headers = dict(request.headers)

    print(f"--- PROXY REQUEST ---")
    print(f"Method: {request.method}")
    print(f"URL: {url}")

    try:
        async with client.stream(method=request.method, url=url, content=body, headers=headers) as response:

            # Clean the response headers BEFORE we send them back! 🔑 THIS IS THE FIX!
            resp_headers = dict(response.headers)

            # CRITICAL: Remove content-length when streaming because
            # we don't know the final size until all chunks are sent.
            if "text/event-stream" in resp_headers.get("content-type", "").lower():
                resp_headers.pop("content-length", None)
                resp_headers.pop("transfer-encoding", None)

                async def stream_generator():
                    async for chunk in response.aiter_bytes():
                        yield chunk

                return StreamingResponse(
                    stream_generator(),
                    status_code=response.status_code,
                    headers=resp_headers  # Cleaned headers! ✅
                )

            # For non-streaming responses, also clean headers but keep content-length OK here
            resp_headers.pop("transfer-encoding", None)  # Still strip this to be safe

            content = await response.aread()
            return Response(content=content, status_code=response.status_code, headers=resp_headers)

    except httpx.RequestError as e:
        print(f"!!! PROXY ERROR !!!")
        print(f"Exception: {e}")
        return Response(content=f"Proxy Error: {e}", status_code=502)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=31234)
