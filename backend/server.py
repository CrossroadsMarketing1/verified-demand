from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, Query, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import json
import random
import csv
import io
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
import secrets
from contextlib import asynccontextmanager

# SQLAlchemy imports
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, Boolean, Text, ForeignKey, Integer, Float, select, text, func, desc, and_
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

logger.info(f"=== BACKEND STARTUP ENVIRONMENT CHECK ===")
logger.info(f"DATABASE_URL detected: {DATABASE_URL is not None and len(DATABASE_URL) > 0}")

if DATABASE_URL:
    logger.info("DATABASE_URL is set - connecting to PostgreSQL")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    if "sslmode=" in DATABASE_URL:
        import re
        DATABASE_URL = re.sub(r'[?&]sslmode=[^&]*', '', DATABASE_URL)
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
    public_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_hex(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Visitor(Base):
    __tablename__ = "visitors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discount_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_redemptions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_redemptions: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False)
    offer_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("offers.id"), nullable=True)
    visitor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("visitors.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    utm_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    utm_medium: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    utm_campaign: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    verification_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

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
    utm_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    utm_medium: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    utm_campaign: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    device_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    browser: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    event_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class VerificationCode(Base):
    __tablename__ = "verification_codes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    code_type: Mapped[str] = mapped_column(String(50), nullable=False)
    business_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=True)
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
            engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"ssl": "require"})
            async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            
            # Create tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            # Run migrations for new columns
            async with async_session_maker() as session:
                # Add missing columns to businesses table
                try:
                    await session.execute(text("ALTER TABLE businesses ADD COLUMN IF NOT EXISTS public_key VARCHAR(64)"))
                    await session.execute(text("UPDATE businesses SET public_key = encode(gen_random_bytes(16), 'hex') WHERE public_key IS NULL"))
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Migration note: {e}")
                    await session.rollback()
                
                # Add missing columns to leads table
                try:
                    await session.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS offer_id VARCHAR(36)"))
                    await session.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(36)"))
                    await session.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS utm_source VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS utm_medium VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS utm_campaign VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE"))
                    await session.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS verification_code VARCHAR(10)"))
                    await session.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS verification_expires TIMESTAMP WITH TIME ZONE"))
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Migration note: {e}")
                    await session.rollback()
                
                # Add missing columns to visitors table
                try:
                    await session.execute(text("ALTER TABLE visitors ADD COLUMN IF NOT EXISTS country VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE visitors ADD COLUMN IF NOT EXISTS city VARCHAR(100)"))
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Migration note: {e}")
                    await session.rollback()
                
                # Add missing columns to offers table
                try:
                    await session.execute(text("ALTER TABLE offers ADD COLUMN IF NOT EXISTS discount_code VARCHAR(50)"))
                    await session.execute(text("ALTER TABLE offers ADD COLUMN IF NOT EXISTS max_redemptions INTEGER"))
                    await session.execute(text("ALTER TABLE offers ADD COLUMN IF NOT EXISTS current_redemptions INTEGER DEFAULT 0"))
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Migration note: {e}")
                    await session.rollback()
                
                # Add missing columns to traffic_events table
                try:
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS utm_source VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS utm_medium VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS utm_campaign VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS country VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS city VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS device_type VARCHAR(50)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS browser VARCHAR(50)"))
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Migration note: {e}")
                    await session.rollback()
                
                # Add/update verification_codes table columns
                try:
                    await session.execute(text("ALTER TABLE verification_codes ADD COLUMN IF NOT EXISTS email VARCHAR(255)"))
                    await session.execute(text("ALTER TABLE verification_codes ADD COLUMN IF NOT EXISTS business_id VARCHAR(36)"))
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Migration note: {e}")
                    await session.rollback()
            
            logger.info("Database tables and migrations completed successfully")
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
    await init_db()
    yield
    await close_db()

app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")
security = HTTPBearer(auto_error=False)

# ============== Pydantic Models ==============
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
    business_id: Optional[str] = None
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

class OfferCreate(BaseModel):
    title: str
    description: Optional[str] = None
    discount_percent: Optional[float] = None
    discount_code: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    max_redemptions: Optional[int] = None

class OfferUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    discount_percent: Optional[float] = None
    discount_code: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None
    max_redemptions: Optional[int] = None

class OfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    description: Optional[str] = None
    discount_percent: Optional[float] = None
    discount_code: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: bool
    max_redemptions: Optional[int] = None
    current_redemptions: int
    created_at: datetime

class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    is_verified: bool
    status: str
    created_at: datetime

class TrackEventRequest(BaseModel):
    public_key: str
    session_id: str
    event_type: str
    page_url: Optional[str] = None
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    device_type: Optional[str] = None
    browser: Optional[str] = None

class LeadCaptureRequest(BaseModel):
    public_key: str
    offer_id: str
    email: EmailStr
    name: Optional[str] = None
    phone: Optional[str] = None
    session_id: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None

class SendOTPRequest(BaseModel):
    public_key: str
    email: EmailStr

class ConfirmOTPRequest(BaseModel):
    public_key: str
    email: EmailStr
    code: str
    offer_id: Optional[str] = None

class BusinessSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    public_key: str
    description: Optional[str] = None

# ============== Helper Functions ==============
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_jwt_token(user_id: str, email: str, business_id: Optional[str] = None) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "business_id": business_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
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

async def get_or_create_business(user: User, session: AsyncSession) -> Business:
    if user.business_id:
        result = await session.execute(select(Business).where(Business.id == user.business_id))
        business = result.scalar_one_or_none()
        if business:
            return business
    # Create new business for user
    business = Business(id=str(uuid.uuid4()), name=f"{user.email}'s Business")
    session.add(business)
    user.business_id = business.id
    await session.commit()
    await session.refresh(business)
    return business

# ============== Routes ==============
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
    return {"status": "healthy", "database": db_status, "timestamp": datetime.now(timezone.utc).isoformat()}

# ============== Auth Routes ==============
@api_router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserRegister, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create business first
    business = Business(id=str(uuid.uuid4()), name=f"{user_data.email}'s Business")
    session.add(business)
    
    new_user = User(
        id=str(uuid.uuid4()),
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        is_active=True,
        is_verified=False,
        business_id=business.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    
    token = create_jwt_token(new_user.id, new_user.email, new_user.business_id)
    logger.info(f"New user registered: {new_user.email}")
    return TokenResponse(access_token=token, user=UserResponse.model_validate(new_user))

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="User account is disabled")
    
    token = create_jwt_token(user.id, user.email, user.business_id)
    logger.info(f"User logged in: {user.email}")
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)

@api_router.post("/auth/reset-password", response_model=MessageResponse)
async def request_password_reset(data: PasswordResetRequest, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if user:
        reset_token = secrets.token_urlsafe(32)
        user.reset_token = reset_token
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await session.commit()
        logger.info(f"Password reset token generated for: {user.email}")
    return MessageResponse(message="If an account exists with this email, a reset link has been sent")

@api_router.post("/auth/reset-password/confirm", response_model=MessageResponse)
async def confirm_password_reset(data: PasswordResetConfirm, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(
        select(User).where(User.reset_token == data.token, User.reset_token_expires > datetime.now(timezone.utc))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user.password_hash = hash_password(data.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    await session.commit()
    return MessageResponse(message="Password has been reset successfully")

# ============== Offers CRUD ==============
@api_router.post("/offers", response_model=OfferResponse)
async def create_offer(offer_data: OfferCreate, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    offer = Offer(
        id=str(uuid.uuid4()),
        business_id=business.id,
        title=offer_data.title,
        description=offer_data.description,
        discount_percent=offer_data.discount_percent,
        discount_code=offer_data.discount_code or f"OFFER{random.randint(1000,9999)}",
        start_date=offer_data.start_date,
        end_date=offer_data.end_date,
        max_redemptions=offer_data.max_redemptions,
        is_active=True
    )
    session.add(offer)
    await session.commit()
    await session.refresh(offer)
    return OfferResponse.model_validate(offer)

@api_router.get("/offers", response_model=List[OfferResponse])
async def get_offers(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(select(Offer).where(Offer.business_id == business.id).order_by(desc(Offer.created_at)))
    return [OfferResponse.model_validate(o) for o in result.scalars().all()]

@api_router.get("/offers/{offer_id}", response_model=OfferResponse)
async def get_offer(offer_id: str, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(select(Offer).where(Offer.id == offer_id, Offer.business_id == business.id))
    offer = result.scalar_one_or_none()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    return OfferResponse.model_validate(offer)

@api_router.put("/offers/{offer_id}", response_model=OfferResponse)
async def update_offer(offer_id: str, offer_data: OfferUpdate, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(select(Offer).where(Offer.id == offer_id, Offer.business_id == business.id))
    offer = result.scalar_one_or_none()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    for key, value in offer_data.model_dump(exclude_unset=True).items():
        setattr(offer, key, value)
    offer.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(offer)
    return OfferResponse.model_validate(offer)

@api_router.delete("/offers/{offer_id}", response_model=MessageResponse)
async def delete_offer(offer_id: str, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(select(Offer).where(Offer.id == offer_id, Offer.business_id == business.id))
    offer = result.scalar_one_or_none()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    offer.is_active = False
    await session.commit()
    return MessageResponse(message="Offer deactivated")

# ============== Leads ==============
@api_router.get("/leads", response_model=List[LeadResponse])
async def get_leads(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    status: Optional[str] = None,
    is_verified: Optional[bool] = None,
    limit: int = Query(default=100, le=500)
):
    business = await get_or_create_business(current_user, session)
    query = select(Lead).where(Lead.business_id == business.id)
    if status:
        query = query.where(Lead.status == status)
    if is_verified is not None:
        query = query.where(Lead.is_verified == is_verified)
    query = query.order_by(desc(Lead.created_at)).limit(limit)
    result = await session.execute(query)
    return [LeadResponse.model_validate(l) for l in result.scalars().all()]

@api_router.get("/leads/export")
async def export_leads(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(select(Lead).where(Lead.business_id == business.id).order_by(desc(Lead.created_at)))
    leads = result.scalars().all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Email", "Name", "Phone", "Source", "UTM Source", "UTM Campaign", "Verified", "Status", "Created At"])
    for lead in leads:
        writer.writerow([lead.id, lead.email, lead.name, lead.phone, lead.source, lead.utm_source, lead.utm_campaign, lead.is_verified, lead.status, lead.created_at.isoformat()])
    
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=leads.csv"})

# ============== Analytics ==============
@api_router.get("/analytics/overview")
async def analytics_overview(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    now = datetime.now(timezone.utc)
    last_30_days = now - timedelta(days=30)
    
    # Total visitors
    visitors_result = await session.execute(select(func.count(Visitor.id)).where(Visitor.business_id == business.id))
    total_visitors = visitors_result.scalar() or 0
    
    # Total leads
    leads_result = await session.execute(select(func.count(Lead.id)).where(Lead.business_id == business.id))
    total_leads = leads_result.scalar() or 0
    
    # Verified leads
    verified_result = await session.execute(select(func.count(Lead.id)).where(Lead.business_id == business.id, Lead.is_verified == True))
    verified_leads = verified_result.scalar() or 0
    
    # Active offers
    offers_result = await session.execute(select(func.count(Offer.id)).where(Offer.business_id == business.id, Offer.is_active == True))
    active_offers = offers_result.scalar() or 0
    
    # Page views (traffic events)
    pageviews_result = await session.execute(select(func.count(TrafficEvent.id)).where(TrafficEvent.business_id == business.id, TrafficEvent.event_type == "pageview"))
    total_pageviews = pageviews_result.scalar() or 0
    
    # Conversion rate
    conversion_rate = (total_leads / total_visitors * 100) if total_visitors > 0 else 0
    
    return {
        "total_visitors": total_visitors,
        "total_leads": total_leads,
        "verified_leads": verified_leads,
        "active_offers": active_offers,
        "total_pageviews": total_pageviews,
        "conversion_rate": round(conversion_rate, 2)
    }

@api_router.get("/analytics/sources")
async def analytics_sources(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(
        select(TrafficEvent.utm_source, func.count(TrafficEvent.id).label("count"))
        .where(TrafficEvent.business_id == business.id, TrafficEvent.utm_source.isnot(None))
        .group_by(TrafficEvent.utm_source)
        .order_by(desc("count"))
        .limit(10)
    )
    return [{"source": row[0], "count": row[1]} for row in result.all()]

@api_router.get("/analytics/geography")
async def analytics_geography(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(
        select(TrafficEvent.country, func.count(TrafficEvent.id).label("count"))
        .where(TrafficEvent.business_id == business.id, TrafficEvent.country.isnot(None))
        .group_by(TrafficEvent.country)
        .order_by(desc("count"))
        .limit(10)
    )
    return [{"country": row[0], "count": row[1]} for row in result.all()]

@api_router.get("/analytics/utm-campaigns")
async def analytics_utm_campaigns(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(
        select(TrafficEvent.utm_campaign, func.count(TrafficEvent.id).label("count"))
        .where(TrafficEvent.business_id == business.id, TrafficEvent.utm_campaign.isnot(None))
        .group_by(TrafficEvent.utm_campaign)
        .order_by(desc("count"))
        .limit(10)
    )
    return [{"campaign": row[0], "count": row[1]} for row in result.all()]

@api_router.get("/analytics/recent-activity")
async def analytics_recent_activity(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session), limit: int = 20):
    business = await get_or_create_business(current_user, session)
    result = await session.execute(
        select(TrafficEvent)
        .where(TrafficEvent.business_id == business.id)
        .order_by(desc(TrafficEvent.created_at))
        .limit(limit)
    )
    events = result.scalars().all()
    return [{
        "id": e.id,
        "event_type": e.event_type,
        "page_url": e.page_url,
        "utm_source": e.utm_source,
        "country": e.country,
        "device_type": e.device_type,
        "created_at": e.created_at.isoformat()
    } for e in events]

# ============== Settings ==============
@api_router.get("/settings/business", response_model=BusinessSettingsResponse)
async def get_business_settings(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    return BusinessSettingsResponse.model_validate(business)

@api_router.put("/settings/business", response_model=BusinessSettingsResponse)
async def update_business_settings(name: str = None, description: str = None, current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    if name:
        business.name = name
    if description:
        business.description = description
    business.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(business)
    return BusinessSettingsResponse.model_validate(business)

# ============== Public Routes ==============
@api_router.post("/public/track")
async def public_track(data: TrackEventRequest, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(Business).where(Business.public_key == data.public_key))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Invalid public key")
    
    # Get or create visitor
    visitor_result = await session.execute(select(Visitor).where(Visitor.session_id == data.session_id, Visitor.business_id == business.id))
    visitor = visitor_result.scalar_one_or_none()
    if not visitor:
        visitor = Visitor(id=str(uuid.uuid4()), business_id=business.id, session_id=data.session_id, country=data.country, city=data.city)
        session.add(visitor)
        await session.flush()
    
    event = TrafficEvent(
        id=str(uuid.uuid4()),
        business_id=business.id,
        visitor_id=visitor.id,
        event_type=data.event_type,
        page_url=data.page_url,
        referrer=data.referrer,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        country=data.country,
        city=data.city,
        device_type=data.device_type,
        browser=data.browser
    )
    session.add(event)
    await session.commit()
    return {"success": True, "visitor_id": visitor.id}

@api_router.post("/public/leads/capture")
async def public_capture_lead(data: LeadCaptureRequest, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(Business).where(Business.public_key == data.public_key))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Invalid public key")
    
    # Check if lead already exists
    existing = await session.execute(select(Lead).where(Lead.email == data.email, Lead.business_id == business.id))
    if existing.scalar_one_or_none():
        return {"success": True, "message": "Lead already exists", "requires_verification": True}
    
    lead = Lead(
        id=str(uuid.uuid4()),
        business_id=business.id,
        offer_id=data.offer_id,
        email=data.email,
        name=data.name,
        phone=data.phone,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        source="embed",
        is_verified=False
    )
    session.add(lead)
    await session.commit()
    return {"success": True, "lead_id": lead.id, "requires_verification": True}

@api_router.post("/public/verify/send-otp")
async def public_send_otp(data: SendOTPRequest, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(Business).where(Business.public_key == data.public_key))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Invalid public key")
    
    code = str(random.randint(100000, 999999))
    verification = VerificationCode(
        id=str(uuid.uuid4()),
        email=data.email,
        code=code,
        code_type="lead_verification",
        business_id=business.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)
    )
    session.add(verification)
    await session.commit()
    
    # In production, send email here
    logger.info(f"OTP for {data.email}: {code}")
    return {"success": True, "message": "Verification code sent"}

@api_router.post("/public/verify/confirm-otp")
async def public_confirm_otp(data: ConfirmOTPRequest, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(Business).where(Business.public_key == data.public_key))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Invalid public key")
    
    vc_result = await session.execute(
        select(VerificationCode).where(
            VerificationCode.email == data.email,
            VerificationCode.code == data.code,
            VerificationCode.business_id == business.id,
            VerificationCode.used_at.is_(None),
            VerificationCode.expires_at > datetime.now(timezone.utc)
        )
    )
    verification = vc_result.scalar_one_or_none()
    if not verification:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    
    verification.used_at = datetime.now(timezone.utc)
    
    # Mark lead as verified
    lead_result = await session.execute(select(Lead).where(Lead.email == data.email, Lead.business_id == business.id))
    lead = lead_result.scalar_one_or_none()
    if lead:
        lead.is_verified = True
        lead.updated_at = datetime.now(timezone.utc)
    
    await session.commit()
    
    # Get offer discount code if provided
    discount_code = None
    if data.offer_id:
        offer_result = await session.execute(select(Offer).where(Offer.id == data.offer_id))
        offer = offer_result.scalar_one_or_none()
        if offer:
            discount_code = offer.discount_code
            offer.current_redemptions += 1
            await session.commit()
    
    return {"success": True, "verified": True, "discount_code": discount_code}

@api_router.get("/public/offers/{offer_id}/check")
async def public_check_offer(offer_id: str, public_key: str, session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(Business).where(Business.public_key == public_key))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Invalid public key")
    
    offer_result = await session.execute(select(Offer).where(Offer.id == offer_id, Offer.business_id == business.id, Offer.is_active == True))
    offer = offer_result.scalar_one_or_none()
    if not offer:
        return {"available": False, "reason": "Offer not found or inactive"}
    
    if offer.max_redemptions and offer.current_redemptions >= offer.max_redemptions:
        return {"available": False, "reason": "Offer fully redeemed"}
    
    if offer.end_date and offer.end_date < datetime.now(timezone.utc):
        return {"available": False, "reason": "Offer expired"}
    
    return {
        "available": True,
        "title": offer.title,
        "description": offer.description,
        "discount_percent": offer.discount_percent
    }

# ============== Demo Data Generation ==============
@api_router.post("/demo/generate")
async def generate_demo_data(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    business = await get_or_create_business(current_user, session)
    
    # Create 3 offers
    offers = []
    offer_templates = [
        {"title": "Early Bird 20% Off", "description": "Get 20% off when you sign up early!", "discount_percent": 20},
        {"title": "VIP Access Pass", "description": "Exclusive VIP access with 15% discount", "discount_percent": 15},
        {"title": "Launch Special", "description": "Special launch offer - 25% off first purchase", "discount_percent": 25}
    ]
    for t in offer_templates:
        offer = Offer(
            id=str(uuid.uuid4()),
            business_id=business.id,
            title=t["title"],
            description=t["description"],
            discount_percent=t["discount_percent"],
            discount_code=f"DEMO{random.randint(1000,9999)}",
            is_active=True,
            max_redemptions=100
        )
        offers.append(offer)
        session.add(offer)
    await session.flush()
    
    # Create 20 visitors
    visitors = []
    countries = ["United States", "United Kingdom", "Canada", "Germany", "France", "Australia", "Japan", "Brazil"]
    cities = ["New York", "London", "Toronto", "Berlin", "Paris", "Sydney", "Tokyo", "São Paulo"]
    for i in range(20):
        visitor = Visitor(
            id=str(uuid.uuid4()),
            business_id=business.id,
            session_id=f"demo_session_{uuid.uuid4().hex[:8]}",
            ip_address=f"192.168.{random.randint(1,255)}.{random.randint(1,255)}",
            country=random.choice(countries),
            city=random.choice(cities),
            created_at=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30))
        )
        visitors.append(visitor)
        session.add(visitor)
    await session.flush()
    
    # Create 20 leads
    first_names = ["John", "Jane", "Mike", "Sarah", "David", "Emily", "Chris", "Lisa", "Tom", "Anna"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller", "Wilson", "Moore", "Taylor"]
    sources = ["google", "facebook", "twitter", "linkedin", "direct", "referral"]
    campaigns = ["summer_sale", "product_launch", "newsletter", "social_promo", "ppc_campaign"]
    
    for i in range(20):
        is_verified = random.choice([True, False, True])  # 66% verified
        lead = Lead(
            id=str(uuid.uuid4()),
            business_id=business.id,
            offer_id=random.choice(offers).id,
            visitor_id=random.choice(visitors).id,
            email=f"demo.user{i+1}@example.com",
            name=f"{random.choice(first_names)} {random.choice(last_names)}",
            phone=f"+1-555-{random.randint(100,999)}-{random.randint(1000,9999)}" if random.choice([True, False]) else None,
            source=random.choice(sources),
            utm_source=random.choice(sources),
            utm_campaign=random.choice(campaigns),
            is_verified=is_verified,
            status="verified" if is_verified else "new",
            created_at=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30))
        )
        session.add(lead)
    
    # Create 150 traffic events
    event_types = ["pageview", "pageview", "pageview", "click", "scroll", "form_view"]
    devices = ["desktop", "mobile", "tablet"]
    browsers = ["Chrome", "Firefox", "Safari", "Edge"]
    pages = ["/", "/pricing", "/features", "/about", "/contact", "/signup"]
    referrers = ["https://google.com", "https://facebook.com", "https://twitter.com", None, None]
    
    for i in range(150):
        visitor = random.choice(visitors)
        event = TrafficEvent(
            id=str(uuid.uuid4()),
            business_id=business.id,
            visitor_id=visitor.id,
            event_type=random.choice(event_types),
            page_url=random.choice(pages),
            referrer=random.choice(referrers),
            utm_source=random.choice(sources) if random.choice([True, False]) else None,
            utm_campaign=random.choice(campaigns) if random.choice([True, False]) else None,
            country=visitor.country,
            city=visitor.city,
            device_type=random.choice(devices),
            browser=random.choice(browsers),
            created_at=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))
        )
        session.add(event)
    
    await session.commit()
    return {"success": True, "message": "Demo data generated: 3 offers, 20 visitors, 20 leads, 150 traffic events"}

# ============== Embed Script ==============
def get_embed_script():
    return """
(function() {
    const VD = {
        config: {},
        visitorId: null,
        sessionId: null,
        
        init: function(options) {
            this.config = options || {};
            this.sessionId = this.getOrCreateSessionId();
            this.trackPageView();
            this.setupTriggers();
        },
        
        getOrCreateSessionId: function() {
            let sid = sessionStorage.getItem('vd_session_id');
            if (!sid) {
                sid = 'vd_' + Math.random().toString(36).substr(2, 9);
                sessionStorage.setItem('vd_session_id', sid);
            }
            return sid;
        },
        
        getUTMParams: function() {
            const params = new URLSearchParams(window.location.search);
            return {
                utm_source: params.get('utm_source'),
                utm_medium: params.get('utm_medium'),
                utm_campaign: params.get('utm_campaign')
            };
        },
        
        track: function(eventType, data) {
            const utm = this.getUTMParams();
            fetch(this.config.apiUrl + '/api/public/track', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    public_key: this.config.publicKey,
                    session_id: this.sessionId,
                    event_type: eventType,
                    page_url: window.location.pathname,
                    referrer: document.referrer,
                    ...utm,
                    ...data
                })
            }).then(r => r.json()).then(d => {
                if (d.visitor_id) this.visitorId = d.visitor_id;
            }).catch(console.error);
        },
        
        trackPageView: function() {
            this.track('pageview', {
                device_type: /Mobile|Android|iPhone/i.test(navigator.userAgent) ? 'mobile' : 'desktop',
                browser: navigator.userAgent.includes('Chrome') ? 'Chrome' : 
                         navigator.userAgent.includes('Firefox') ? 'Firefox' : 
                         navigator.userAgent.includes('Safari') ? 'Safari' : 'Other'
            });
        },
        
        setupTriggers: function() {
            document.querySelectorAll('[data-vd-trigger]').forEach(el => {
                el.addEventListener('click', () => this.openModal());
            });
        },
        
        openModal: function() {
            if (document.getElementById('vd-modal')) return;
            
            const modal = document.createElement('div');
            modal.id = 'vd-modal';
            modal.innerHTML = `
                <div style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:10000;">
                    <div style="background:white;padding:30px;border-radius:12px;max-width:400px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
                        <h2 style="margin:0 0 10px;font-size:24px;">Claim Your Offer</h2>
                        <p style="color:#666;margin-bottom:20px;">Enter your email to get exclusive access</p>
                        <div id="vd-form">
                            <input type="email" id="vd-email" placeholder="Your email" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:6px;margin-bottom:10px;box-sizing:border-box;">
                            <input type="text" id="vd-name" placeholder="Your name (optional)" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:6px;margin-bottom:15px;box-sizing:border-box;">
                            <button id="vd-submit" style="width:100%;padding:12px;background:linear-gradient(135deg,#667eea,#764ba2);color:white;border:none;border-radius:6px;cursor:pointer;font-size:16px;">Get Access</button>
                        </div>
                        <div id="vd-verify" style="display:none;">
                            <input type="text" id="vd-code" placeholder="Enter 6-digit code" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:6px;margin-bottom:15px;box-sizing:border-box;text-align:center;font-size:20px;letter-spacing:5px;">
                            <button id="vd-verify-btn" style="width:100%;padding:12px;background:linear-gradient(135deg,#667eea,#764ba2);color:white;border:none;border-radius:6px;cursor:pointer;font-size:16px;">Verify</button>
                        </div>
                        <div id="vd-success" style="display:none;text-align:center;">
                            <div style="font-size:48px;margin-bottom:10px;">🎉</div>
                            <h3 style="margin:0 0 10px;">You're In!</h3>
                            <p id="vd-discount-code" style="background:#f0f0f0;padding:15px;border-radius:6px;font-family:monospace;font-size:18px;"></p>
                        </div>
                        <button id="vd-close" style="position:absolute;top:10px;right:15px;background:none;border:none;font-size:24px;cursor:pointer;color:#999;">×</button>
                        <p id="vd-error" style="color:red;margin-top:10px;display:none;"></p>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
            
            document.getElementById('vd-close').onclick = () => modal.remove();
            document.getElementById('vd-submit').onclick = () => this.submitLead();
            document.getElementById('vd-verify-btn').onclick = () => this.verifyCode();
        },
        
        submitLead: function() {
            const email = document.getElementById('vd-email').value;
            const name = document.getElementById('vd-name').value;
            const errorEl = document.getElementById('vd-error');
            
            if (!email) {
                errorEl.textContent = 'Please enter your email';
                errorEl.style.display = 'block';
                return;
            }
            
            const utm = this.getUTMParams();
            fetch(this.config.apiUrl + '/api/public/leads/capture', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    public_key: this.config.publicKey,
                    offer_id: this.config.offerId,
                    email: email,
                    name: name,
                    session_id: this.sessionId,
                    ...utm
                })
            }).then(r => r.json()).then(d => {
                if (d.success) {
                    this.leadEmail = email;
                    this.sendOTP(email);
                }
            }).catch(e => {
                errorEl.textContent = 'Error submitting. Please try again.';
                errorEl.style.display = 'block';
            });
        },
        
        sendOTP: function(email) {
            fetch(this.config.apiUrl + '/api/public/verify/send-otp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    public_key: this.config.publicKey,
                    email: email
                })
            }).then(r => r.json()).then(d => {
                document.getElementById('vd-form').style.display = 'none';
                document.getElementById('vd-verify').style.display = 'block';
            });
        },
        
        verifyCode: function() {
            const code = document.getElementById('vd-code').value;
            const errorEl = document.getElementById('vd-error');
            
            fetch(this.config.apiUrl + '/api/public/verify/confirm-otp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    public_key: this.config.publicKey,
                    email: this.leadEmail,
                    code: code,
                    offer_id: this.config.offerId
                })
            }).then(r => r.json()).then(d => {
                if (d.verified) {
                    document.getElementById('vd-verify').style.display = 'none';
                    document.getElementById('vd-success').style.display = 'block';
                    document.getElementById('vd-discount-code').textContent = d.discount_code || 'Check your email!';
                } else {
                    errorEl.textContent = 'Invalid code. Please try again.';
                    errorEl.style.display = 'block';
                }
            }).catch(e => {
                errorEl.textContent = 'Verification failed. Please try again.';
                errorEl.style.display = 'block';
            });
        }
    };
    
    // Auto-init from script tag attributes
    const script = document.currentScript || document.querySelector('script[data-public-key]');
    if (script) {
        const publicKey = script.getAttribute('data-public-key');
        const offerId = script.getAttribute('data-offer-id');
        const apiUrl = script.src.replace('/embed.js', '');
        
        if (publicKey) {
            VD.init({ publicKey, offerId, apiUrl });
        }
    }
    
    window.VerifiedDemand = VD;
})();
"""

@api_router.get("/embed.js", response_class=PlainTextResponse)
async def serve_embed_js_api():
    return get_embed_script()

# Include router and middleware
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve embed.js (root level)
@app.get("/embed.js", response_class=PlainTextResponse)
async def serve_embed_js():
    return get_embed_script()
