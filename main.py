import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response
import httpx
from wakeonlan import send_magic_packet

app = FastAPI()

TARGET_MAC = os.getenv("LM_STUDIO_MAC")
# Fixed the syntax error from before! No stray quotes! ✅
TARGET_URL = f"http://{os.getenv('LM_STUDIO_IP')}:{os.getenv('LM_STUDIO_PORT', '1234')}"

client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

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

    # Build URL carefully. If it's the root, don't add a slash!
    if clean_path:
        url = f"{TARGET_URL}/{clean_path}"
    else:
        url = TARGET_URL

    body = await request.body()

    # 2. Sanitize headers! 🧹
    # We strip out 'host', 'content-length', and 'transfer-encoding' because httpx will calculate those for us.
    # Sending them manually often causes "Bad Gateway" errors!
    headers = dict(request.headers)

    headers_to_remove = ["host", "content-length", "transfer-encoding", "connection"]
    for h in headers_to_remove:
        headers.pop(h, None)

    print(f"--- PROXY REQUEST ---")
    print(f"Method: {request.method}")
    print(f"URL: {url}") # <--- Check your logs to see if this looks right!

    try:
        # Try streaming first (for chat completions) 🌊
        async with client.stream(method=request.method, url=url, content=body, headers=headers) as response:

            # If LM Studio says "this is a stream", we stream it back.
            if "text/event-stream" in response.headers.get("content-type", "").lower():
                async def stream_generator():
                    async for chunk in response.aiter_bytes():
                        yield chunk

                return StreamingResponse(stream_generator(), status_code=response.status_code, headers=dict(response.headers))

            # Otherwise, read the whole thing and send it back.
            content = await response.aread()
            return Response(content=content, status_code=response.status_code, headers=dict(response.headers))

    except httpx.RequestError as e:
        print(f"!!! CRITICAL PROXY ERROR !!!")
        print(f"Exception: {e}") # <--- This will tell us exactly what broke!

        # If the stream failed for some reason (maybe it wasn't a stream after all?),
        # try one last time without streaming.
        try:
            final_response = await client.request(method=request.method, url=url, content=body, headers=headers)
            return Response(content=final_response.content, status_code=final_response.status_code)
        except Exception as e2:
             print(f"!!! FALLBACK ALSO FAILED !!!") # <--- If you see this in logs... we are in trouble!
             return Response(content=f"Proxy Error: {e}", status_code=502)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=31234)
