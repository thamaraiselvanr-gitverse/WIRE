import asyncio
import sys

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from wire.service import WireService

app = FastAPI(title="WIRE Semantic Web Reconstructor")


class ReconstructRequest(BaseModel):
    url: str


@app.post("/api/reconstruct")
async def reconstruct(request: ReconstructRequest):
    service = WireService()
    try:
        score = await service.run(request.url)
        return {"status": "success", "fidelity_score": score, "url": request.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--server":
            print("Starting FastAPI server on port 8000...")
            uvicorn.run("wire.main:app", host="0.0.0.0", port=8000, reload=False)
            return

        url = sys.argv[1]
        service = WireService()
        try:
            score = asyncio.run(service.run(url))
            print(f"\nReconstruction complete! Fidelity Score: {score}")
        except Exception as e:
            print(f"\nError during reconstruction: {e}")
            sys.exit(1)
    else:
        print("Usage: wire <url> OR string '--server' to start the REST API")
        print("Starting FastAPI server on port 8000 as default...")
        uvicorn.run("wire.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
