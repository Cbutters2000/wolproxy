import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response
import httpx
from wakeonlan import send_magic_packet

app = FastAPI()

TARGET_MAC = os.getenv("LM_STUDIO_MAC")
TARGET_URL = f"http://{os.getenv('LM_STUDIO_IP')}:{os.getenv('LM_STUDIO_PORT', '1234')}"
WAKE_TIMEOUT = float(os.getenv("WAKE_TIMEOUT", "180"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "600"))

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
}

client = httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0))


def clean_headers(headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP and k.lower() != "host"}


async def wait_for_backend() -> bool:
    deadline = asyncio.get_event_loop().time() + WAKE_TIMEOUT
    while asyncio.get_event_loop().time() < deadline:
        try:
            r = await client.get(f"{TARGET_URL}/v1/models")
            if r.status_code < 500:
                return True
        except httpx.RequestError:
            pass
        await asyncio.sleep(2)
    return False


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def proxy(request: Request, path: str):
    if TARGET_MAC:
        try:
            send_magic_packet(TARGET_MAC)
        except Exception as e:
            print(f"WoL Error: {e}")

    if not await wait_for_backend():
        return Response(
            content="Proxy Error: LM Studio did not come up after WoL",
            status_code=502,
        )

    clean_path = path.lstrip("/")
    url = f"{TARGET_URL}/{clean_path}" if clean_path else TARGET_URL
    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body()
    headers = clean_headers(request.headers)

    try:
        req = client.build_request(
            method=request.method,
            url=url,
            content=body,
            headers=headers,
        )
        response = await client.send(req, stream=True)

        resp_headers = clean_headers(response.headers)
        content_type = response.headers.get("content-type", "")

        if "text/event-stream" in content_type.lower() or request.headers.get("accept", "").find("text/event-stream") >= 0:
            async def stream_generator():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    await response.aclose()

            return StreamingResponse(
                stream_generator(),
                status_code=response.status_code,
                headers=resp_headers,
                media_type="text/event-stream",
            )

        content = await response.aread()
        await response.aclose()
        return Response(content=content, status_code=response.status_code, headers=resp_headers)

    except httpx.RequestError as e:
        return Response(content=f"Proxy Error: {e}", status_code=502)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=31234)
