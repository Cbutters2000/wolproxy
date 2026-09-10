import os
from fastapi import FastAPI, Request, Response
import httpx
from wakeonlan import send_magic_packet

app = FastAPI()

# Get configuration from environment variables (set these in TrueNAS later!)
TARGET_MAC = os.getenv("LM_STUDIO_MAC")
# FIXED: Corrected the f-string syntax here! No more stray quotes or emojis! 🛠️
TARGET_URL = f"http://{os.getenv('LM_STUDIO_IP')}:{os.getenv('LM_STUDIO_PORT', '1234')}"

# We use a global httpx client for better performance (connection pooling)
client = httpx.AsyncClient()

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, path: str):
    # 1. Wake up the machine immediately!
    if TARGET_MAC:
        try:
            send_magic_packet(TARGET_MAC)
        except Exception as e:
            print(f"WoL Error: {e}")

    # 2. Forward the request to LM Studio exactly as it came in
    url = f"{TARGET_URL}/{path}"
    body = await request.body()
    headers = dict(request.headers)
    # We remove 'host' header so LM Studio doesn't get confused about who is calling it
    headers.pop("host", None)

    try:
        response = await client.request(
            method=request.method,
            url=url,
            content=body,
            headers=headers,
            timeout=60.0 # Give the hibernating PC a little time to wake up!
        )

        # Return LM Studio's response back to you exactly as is
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers)
        )

    except httpx.RequestError as e:
        return Response(content=f"Proxy Error: {e}", status_code=502)

if __name__ == "__main__":
    import uvicorn
    # Run on port 31234 since we are using Host Networking now!
    uvicorn.run(app, host="0.0.0.0", port=31234)
