import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response
import httpx

app = FastAPI()

TARGET_URL = f"http://{os.getenv('LM_STUDIO_IP', '192.168.1.40')}:{os.getenv('LM_STUDIO_PORT', '1234')}"
TARGET_MAC = os.getenv('TARGET_MAC', '')

# Wake-on-LAN helper
def send_magic_packet(mac: str):
    # Convert MAC to bytes, e.g., "AA:BB:CC:DD:EE:FF" -> b'\xaa\xbb...'
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + (mac_bytes * 16)

    import socket, struct
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(packet, ("255.255.255.255", 9))
    s.close()

client = httpx.AsyncClient(timeout=httpx.Timeout(300.0), verify=False)

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, path: str):
    # Wake up the machine immediately! ⚡️
    if TARGET_MAC:
        try:
            send_magic_packet(TARGET_MAC)
        except Exception as e:
            print(f"WoL Error: {e}")

    # Forward to LM Studio with streaming 🌊️💨️
    url = f"{TARGET_URL}/{path}"
    body = await request.body()

    headers = dict(request.headers)
    headers.pop("host", None)

    rp_req = client.build_request(method=request.method, url=url, content=body, headers=headers)

    try:
        rp_resp = await client.send(rp_req, stream=True)
    except Exception as e:
        return Response(content=f"Proxy Error: {e}", status_code=502)

    async def stream_generator():
        async for chunk in rp_resp.aiter_bytes():
            yield chunk

    return StreamingResponse(
        stream_generator(),
        status_code=rp_resp.status_code,
        headers=dict(rp_resp.headers)
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=31234)
