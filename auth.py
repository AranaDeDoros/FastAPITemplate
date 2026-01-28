from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

# Configuration
SECRET_KEY = "your-super-secret-key-change-this"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# The scheme that tells FastAPI how to extract the token
# tokenUrl points to your login route
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
password_hash = PasswordHash.recommended() # Defaults to Argon2

def verify_password(plain, hashed):
    return password_hash.verify(plain, hashed)

def get_password_hash(password):
    return password_hash.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError as exc:
        raise credentials_exception from exc
    
    # Here you would typically fetch the user from your database
    # user = db.get_user(username)
    return {"username": username}

REFRESH_TOKEN_EXPIRE_DAYS = 7

def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "scope": "refresh_token"}) # Scope prevents reuse
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)