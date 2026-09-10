import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response
import httpx
from wakeonlan import send_magic_packet

app = FastAPI()

# Get configuration from environment variables (set these in TrueNAS later!)
TARGET_MAC = os.getenv("LM_STUDIO_MAC")
TARGET_URL = f"http://{os.getenv('LM_STUDIO_IP')}:{os.getenv('LM_STUDIO_PORT', '1234')"}"

# Global httpx client for better performance (connection pooling)
client = httpx.AsyncClient()

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, path: str):
    # 1. Wake up the machine immediately! ⚡️
    if TARGET_MAC:
        try:
            send_magic_packet(TARGET_MAC)
        except Exception as e:
            print(f"WoL Error: {e}")

    # Fix double slash issue by stripping leading slashes from path and manually adding one back in the URL construction below. 🥖
    clean_path = path.lstrip("/")
    url = f"{TARGET_URL}/{clean_path}" if clean_path else TARGET_URL

    body = await request.body()
    headers = dict(request.headers)
    # We remove 'host' header so LM Studio doesnt get confused about who is calling it
    headers.pop("host", None)

    try:
        # Use .stream instead of .request to handle streaming responses from LM Studio 🌊
        async with client.stream(method=request.method, url=url, content=body, headers=headers, timeout=60.0) as response:
            # If the request is for a chat completion (which usually streams), we pass through chunks of data instantly!
            if "text/event-stream" in response.headers.get("content-type", "").lower():
                async def stream_generator():
                    async for chunk in response.aiter_bytes():
                        yield chunk

                return StreamingResponse(stream_generator(), status_code=response.status_code, headers=dict(response.headers))

            # Otherwise, just return the full response normally as we did before
            content = await response.aread()
            return Response(content=content, status_code=response.status_code, headers=dict(response.headers))

    except httpx.RequestError as e:
        return Response(content=f"Proxy Error: {e}", status_code=502)

if __name__ == "__main__":
    import uvicorn
    # Changed to port 31234 so it doesn't clash with TrueNAS on port 80!
    uvicorn.run(app, host="0.0.0.0", port=31234)
