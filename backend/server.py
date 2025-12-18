from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
import secrets
from contextlib import asynccontextmanager

# SQLAlchemy imports
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, Boolean, Text, ForeignKey, Integer, Float, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")

# Safe startup logging - never print actual value
logger.info(f"=== BACKEND STARTUP ENVIRONMENT CHECK ===")
logger.info(f"DATABASE_URL detected: {DATABASE_URL is not None and len(DATABASE_URL) > 0}")
logger.info(f"Environment keys available: {[k for k in os.environ.keys() if 'DATABASE' in k.upper() or 'POSTGRES' in k.upper() or 'SUPABASE' in k.upper()]}")

if DATABASE_URL:
    logger.info("DATABASE_URL is set - connecting to PostgreSQL")
    # Convert postgres:// to postgresql+asyncpg:// for async support
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    # Remove sslmode parameter if present (asyncpg handles SSL differently)
    if "sslmode=" in DATABASE_URL:
        import re
        DATABASE_URL = re.sub(r'[?&]sslmode=[^&]*', '', DATABASE_URL)
        # Clean up any trailing ? or &
        DATABASE_URL = DATABASE_URL.rstrip('?&')
else:
    logger.warning("DATABASE_URL not found - database features will be unavailable")
    DATABASE_URL = None

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# SQLAlchemy Base
class Base(DeclarativeBase):
    pass

# Database Models
class Business(Base):
    __tablename__ = "businesses"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    business_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=True)
    reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reset_token_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Visitor(Base):
    __tablename__ = "visitors"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Offer(Base):
    __tablename__ = "offers"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discount_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Lead(Base):
    __tablename__ = "leads"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class OfferReservation(Base):
    __tablename__ = "offer_reservations"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    offer_id: Mapped[str] = mapped_column(String(36), ForeignKey("offers.id"), nullable=False)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class TrafficEvent(Base):
    __tablename__ = "traffic_events"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False)
    visitor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("visitors.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    page_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    referrer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON stored as text
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class VerificationCode(Base):
    __tablename__ = "verification_codes"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    code_type: Mapped[str] = mapped_column(String(50), nullable=False)  # email_verification, password_reset
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

# Global engine and session
engine = None
async_session_maker = None

async def init_db():
    global engine, async_session_maker
    if DATABASE_URL:
        try:
            engine = create_async_engine(DATABASE_URL, echo=False)
            async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            
            # Create all tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            logger.info("Database tables created/verified successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {str(e)}")
            raise
    else:
        logger.warning("Skipping database initialization - DATABASE_URL not set")

async def close_db():
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database connection closed")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown
    await close_db()

# Create the main app
app = FastAPI(lifespan=lifespan)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer(auto_error=False)

# Pydantic Models for API
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool
    is_verified: bool
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8)

class MessageResponse(BaseModel):
    message: str

# Helper functions
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_jwt_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_db_session():
    if async_session_maker is None:
        raise HTTPException(status_code=503, detail="Database not available")
    async with async_session_maker() as session:
        yield session

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_db_session)
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    payload = decode_jwt_token(credentials.credentials)
    user_id = payload.get("sub")
    
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="User account is disabled")
    
    return user

# Routes
@api_router.get("/")
async def root():
    return {"message": "Hello World", "database": "connected" if DATABASE_URL else "not configured"}

@api_router.get("/health")
async def health_check():
    db_status = "connected" if DATABASE_URL else "not configured"
    if DATABASE_URL and async_session_maker:
        try:
            async with async_session_maker() as session:
                await session.execute(text("SELECT 1"))
                db_status = "healthy"
        except Exception as e:
            db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Auth Routes
@api_router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserRegister, session: AsyncSession = Depends(get_db_session)):
    # Check if user already exists
    result = await session.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create new user
    new_user = User(
        id=str(uuid.uuid4()),
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        is_active=True,
        is_verified=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    
    # Generate JWT token
    token = create_jwt_token(new_user.id, new_user.email)
    
    logger.info(f"New user registered: {new_user.email}")
    
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(new_user)
    )

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin, session: AsyncSession = Depends(get_db_session)):
    # Find user by email
    result = await session.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not user.is_active:
        raise HTTPException(status_code=401, detail="User account is disabled")
    
    # Generate JWT token
    token = create_jwt_token(user.id, user.email)
    
    logger.info(f"User logged in: {user.email}")
    
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user)
    )

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)

@api_router.post("/auth/reset-password", response_model=MessageResponse)
async def request_password_reset(data: PasswordResetRequest, session: AsyncSession = Depends(get_db_session)):
    # Find user by email
    result = await session.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    
    # Always return success to prevent email enumeration
    if not user:
        logger.info(f"Password reset requested for non-existent email: {data.email}")
        return MessageResponse(message="If an account exists with this email, a reset link has been sent")
    
    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    user.reset_token = reset_token
    user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    
    await session.commit()
    
    logger.info(f"Password reset token generated for: {user.email}")
    # In production, send email with reset link
    # For MVP, we log the token (would be sent via email)
    logger.info(f"Reset token (for testing): {reset_token}")
    
    return MessageResponse(message="If an account exists with this email, a reset link has been sent")

@api_router.post("/auth/reset-password/confirm", response_model=MessageResponse)
async def confirm_password_reset(data: PasswordResetConfirm, session: AsyncSession = Depends(get_db_session)):
    # Find user by reset token
    result = await session.execute(
        select(User).where(
            User.reset_token == data.token,
            User.reset_token_expires > datetime.now(timezone.utc)
        )
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Update password
    user.password_hash = hash_password(data.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    user.updated_at = datetime.now(timezone.utc)
    
    await session.commit()
    
    logger.info(f"Password reset completed for: {user.email}")
    
    return MessageResponse(message="Password has been reset successfully")

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
