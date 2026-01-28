import concurrent.futures
import functools
import hashlib
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from multiprocessing import cpu_count
from pathlib import Path

import jwt
from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import OAuth2PasswordRequestForm

import auth
from Logger import Logger

app = FastAPI()

""" app.add_middleware(HTTPSRedirectMiddleware) """
""" app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["example.com", "*.example.com"]
) """
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Or your specific frontend URL
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)



MAX_FILES_PER_REQUEST = 100
TRANSFER_CHUNK_SIZE = 100
BASE_UPLOAD_DIR = Path("uploads")
BASE_UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_MIME_TYPES = {"application/xml", "text/xml"}
SENDER_EXE = Path("sender.exe")
REMOTE_BASE_DIR = "/remote/inbox"


def send_batch(batch_dir: Path) -> None:
    remote_dir = f"{REMOTE_BASE_DIR}/{batch_dir.name}"

    subprocess.run(
    [
    str(SENDER_EXE),
    str(batch_dir),
    remote_dir,
    ],
    check=True,
    )

def transfer_batch(batch_dir: Path) -> None:
    files = sorted(batch_dir.glob("*.xml"))

    for _index, chunk in enumerate(
        chunked(files, TRANSFER_CHUNK_SIZE), start=1
    ):
        try:
            send_batch(chunk)
        except Exception:
            # This is where you'd:
            # - log failure
            # - mark batch/chunk as FAILED
            # - retry later
            raise

def chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


@app.post("/upload/batch", status_code=200)
async def upload_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=413,
            detail=f"Max {MAX_FILES_PER_REQUEST} files per request",
        )

    sorted(files, key=lambda f : f.filename )
    
    batch_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}"
    batch_dir = BASE_UPLOAD_DIR / batch_id
    batch_dir.mkdir(parents=True)

    for file in files:
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Invalid MIME type: {file.filename}",
            )

        file_path = batch_dir / file.filename

        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    # Schedule batch processing (not per file)
    background_tasks.add_task(transfer_batch, batch_dir)

    return {
        "batch_id": batch_id,
        "files_received": len(files),
        "status": "accepted",
    }

@app.get("/ping", status_code=200)
async def ping(response: Response):
    Logger.getLogger().fatal("Root endpoint accessed")
    response.headers["X-Custom-Header"] = "Metadata-Value"
    response.headers["Content-Language"] = "en-US"
    return "pong"

def timer(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"{func.__name__} took {end - start:.4f} seconds")
        return result
    return wrapper



TIMEOUT = 10

# 1. Define the worker function at the top level
def hash_chunk(start_i, end_i, limit):
    # Each chunk needs its own starting point
    local_hash = hashlib.sha256(f"seed-{start_i}".encode())
    chunk_results = []
    
    for i in range(start_i, end_i):
        for j in range(limit):
            data = f"{i}-{j}-{local_hash.hexdigest()}".encode()
            local_hash = hashlib.sha256(data)
        # To avoid RAM crashes, we only store the result of the inner loop completion
        chunk_results.append(local_hash.hexdigest())
    return chunk_results

@app.get("/heavy")
async def heavy(limit: int, response: Response):
    start = time.perf_counter()
    num_cores = cpu_count()
    
    if limit <= 0:
        return {"status": "failed", "reason": "limit too low"}

    chunk_size = limit // num_cores
    futures = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=num_cores) as executor:
        for i in range(num_cores):
            s_i = i * chunk_size
            e_i = limit if i == num_cores - 1 else (i + 1) * chunk_size
            # Submit each chunk to a different CPU core
            futures.append(executor.submit(hash_chunk, s_i, e_i, limit))

        try:
            # Gather results from all cores with a global timeout
            combined_results = []
            for f in concurrent.futures.as_completed(futures, timeout=TIMEOUT):
                combined_results.extend(f.result())
            
            end = time.perf_counter()
            duration = end - start

            response.headers["X-Computation-Time"] = f"{duration:.4f}s"
            response.headers["X-Cores-Used"] = str(num_cores)
            response.headers["X-Limit-Processed"] = str(limit)

            return {
                "status": "completed",
                "cores_used": num_cores,
                "time": f"{end - start:.4f}",
                "result_count": len(combined_results),
                "sample": combined_results[:3]
            }

        except concurrent.futures.TimeoutError as exc:
            executor.shutdown(wait=False, cancel_futures=True)
            raise HTTPException(status_code=504, detail="Multi-CPU Task Timed Out") from exc
        



@app.post("/login")
async def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    # ... (verify user here) ...
    
    access_token = auth.create_access_token(data={"sub": form_data.username})
    refresh_token = auth.create_refresh_token(data={"sub": form_data.username})
    
    # Set the refresh token in a secure cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,   # Prevents JS access
        secure=True,     # Only sends over HTTPS
        samesite="lax",  # CSRF protection
        max_age=auth.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/refresh")
async def refresh_access_token(refresh_token: str = Cookie(None)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    
    try:
        payload = jwt.decode(refresh_token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        if payload.get("scope") != "refresh_token":
            raise HTTPException(status_code=401, detail="Invalid token scope")
            
        new_access_token = auth.reate_access_token(data={"sub": payload.get("sub")})
        return {"access_token": new_access_token, "token_type": "bearer"}
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc