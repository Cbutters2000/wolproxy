import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response
import httpx
from wakeonlan import send_magic_packet

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("proxy")

app = FastAPI()
TARGET_MAC = os.getenv("LM_STUDIO_MAC")
TARGET_HOST = os.getenv("LM_STUDIO_IP")
TARGET_PORT = os.getenv("LM_STUDIO_PORT", "1234")
TARGET_URL = f"http://{TARGET_HOST}:{TARGET_PORT}"

log.info("Upstream target: %s  MAC=%s", TARGET_URL, TARGET_MAC)

client = httpx.AsyncClient(
    timeout=httpx.Timeout(600.0, connect=10.0),
    follow_redirects=True,
)

HOP = {
    "host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
    "accept-encoding", "content-encoding",
}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(request: Request, path: str):
    if TARGET_MAC:
        try:
            send_magic_packet(TARGET_MAC)
        except Exception as e:
            log.warning("WoL error: %s", e)

    clean_path = path.lstrip("/")
    url = f"{TARGET_URL}/{clean_path}" if clean_path else TARGET_URL
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = {}
    if ct := request.headers.get("content-type"):
        headers["content-type"] = ct
    if auth := request.headers.get("authorization"):
        headers["authorization"] = auth

    body = await request.body()
    log.info("%s %s -> %s (%d bytes)", request.method, request.url.path, url, len(body))

    try:
        req = client.build_request(request.method, url, content=body, headers=headers)
        upstream = await client.send(req, stream=True)
    except httpx.RequestError as e:
        log.exception("Upstream error talking to %s", url)
        return Response(content=f"Proxy Error: {type(e).__name__}: {e}", status_code=502)

    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP}
    ctype = upstream.headers.get("content-type", "")

    if "text/event-stream" in ctype.lower():
        async def gen():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
        return StreamingResponse(gen(), status_code=upstream.status_code, headers=out_headers, media_type="text/event-stream")

    content = await upstream.aread()
    await upstream.aclose()
    return Response(content=content, status_code=upstream.status_code, headers=out_headers)
