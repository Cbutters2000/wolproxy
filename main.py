import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response
import httpx
from wakeonlan import send_magic_packet

app = FastAPI()

TARGET_MAC = os.getenv("LM_STUDIO_MAC")
TARGET_URL = f"http://{os.getenv('LM_STUDIO_IP')}:{os.getenv('LM_STUDIO_PORT', '1234')}"

# We set a GLOBAL timeout of 5 minutes (300 seconds) on the client itself! ⏱️
# This ensures that connecting, reading headers, AND reading the body all have plenty of time.
client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, path: str):
    if TARGET_MAC:
        try:
            send_magic_packet(TARGET_MAC)
        except Exception as e:
            print(f"WoL Error: {e}")

    clean_path = path.lstrip("/")
    url = f"{TARGET_URL}/{clean_path}" if clean_path else TARGET_URL

    body = await request.body()
    headers = dict(request.headers)
    # Strip problematic headers so httpx can regenerate them correctly 🛠️
    headers.pop("host", None)
    headers.pop("content-length", None)

    try:
        # Use .stream to handle both streaming and non-streaming responses efficiently
        async with client.stream(method=request.method, url=url, content=body, headers=headers) as response:
            # If it's a stream (like chat completions), pass chunks through immediately 🌊
            if "text/event-stream" in response.headers.get("content-type", "").lower():
                async def stream_generator():
                    async for chunk in response.aiter_bytes():
                        yield chunk

                return StreamingResponse(stream_generator(), status_code=response.status_code, headers=dict(response.headers))

            # For everything else (like model lists), read the full body with our generous 5-minute timeout!
            content = await response.aread()
            return Response(content=content, status_code=response.status_code, headers=dict(response.headers))

    except httpx.RequestError as e:
        print(f"Proxy Error connecting to LM Studio at {url}: {e}")
        return Response(content=f"Proxy Error: {e}", status_code=502)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=31234)
