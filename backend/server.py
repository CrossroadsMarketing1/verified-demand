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
    # Vehicle-specific fields
    vehicle_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_year: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    vehicle_make: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_trim: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_bucket: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    zip_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class VehicleLead(Base):
    __tablename__ = "vehicle_leads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False)
    visitor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Lead info
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_method: Mapped[str] = mapped_column(String(20), default="text")
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Vehicle info
    vehicle_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_year: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    vehicle_make: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_trim: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vehicle_image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Attribution
    utm_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    utm_medium: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    utm_campaign: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    zip_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    page_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Status
    status: Mapped[str] = mapped_column(String(50), default="new")
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
                    # Vehicle-specific columns
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS vehicle_id VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS vehicle_year VARCHAR(10)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS vehicle_make VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS vehicle_model VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS vehicle_trim VARCHAR(100)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS vehicle_price INTEGER"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS price_bucket VARCHAR(50)"))
                    await session.execute(text("ALTER TABLE traffic_events ADD COLUMN IF NOT EXISTS zip_code VARCHAR(20)"))
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
    # Vehicle fields
    vehicle_id: Optional[str] = None
    vehicle_year: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_trim: Optional[str] = None
    vehicle_price: Optional[int] = None
    zip_code: Optional[str] = None

class VehicleLeadRequest(BaseModel):
    public_key: str
    session_id: str
    # Lead info
    first_name: str
    last_name: str
    phone: str
    email: Optional[str] = None
    contact_method: str = "text"
    comments: Optional[str] = None
    # Vehicle info
    vehicle_id: Optional[str] = None
    vehicle_year: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_trim: Optional[str] = None
    vehicle_price: Optional[int] = None
    vehicle_image: Optional[str] = None
    # Attribution
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    zip_code: Optional[str] = None
    page_url: Optional[str] = None

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
async def get_offers(
    current_user: User = Depends(get_current_user), 
    session: AsyncSession = Depends(get_db_session),
    include_inactive: bool = Query(default=False, description="Include inactive/deleted offers")
):
    business = await get_or_create_business(current_user, session)
    query = select(Offer).where(Offer.business_id == business.id)
    if not include_inactive:
        query = query.where(Offer.is_active == True)
    query = query.order_by(desc(Offer.created_at))
    result = await session.execute(query)
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

# ============== Automotive Dashboard API ==============
@api_router.get("/dashboard/summary")
async def dashboard_summary(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """Summary metrics for automotive dashboard"""
    business = await get_or_create_business(current_user, session)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    
    # Count unique visitors with vehicle interactions (active shoppers)
    active_shoppers_result = await session.execute(
        select(func.count(func.distinct(TrafficEvent.visitor_id)))
        .where(
            TrafficEvent.business_id == business.id,
            TrafficEvent.created_at >= seven_days_ago,
            TrafficEvent.visitor_id.isnot(None)
        )
    )
    active_shoppers = active_shoppers_result.scalar() or 0
    
    # Count vehicle views
    vehicles_viewed_result = await session.execute(
        select(func.count(TrafficEvent.id))
        .where(
            TrafficEvent.business_id == business.id,
            TrafficEvent.event_type.in_(['vehicle_view', 'pageview'])
        )
    )
    vehicles_viewed = vehicles_viewed_result.scalar() or 0
    
    # Count verified leads
    verified_leads_result = await session.execute(
        select(func.count(Lead.id))
        .where(Lead.business_id == business.id, Lead.is_verified == True)
    )
    verified_leads = verified_leads_result.scalar() or 0
    
    # Calculate conversion rate
    conversion_rate = (verified_leads / active_shoppers * 100) if active_shoppers > 0 else 0
    
    return {
        "active_shoppers": active_shoppers,
        "vehicles_viewed": vehicles_viewed,
        "avg_vehicle_price": 32450,  # Will be calculated from actual vehicle data
        "lead_conversion_rate": round(conversion_rate, 1)
    }

@api_router.get("/dashboard/top-vehicles")
async def dashboard_top_vehicles(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """Top 5 vehicles by views"""
    business = await get_or_create_business(current_user, session)
    
    # Get page URLs that look like vehicle pages and count views
    result = await session.execute(
        select(TrafficEvent.page_url, func.count(TrafficEvent.id).label("views"))
        .where(
            TrafficEvent.business_id == business.id,
            TrafficEvent.page_url.isnot(None)
        )
        .group_by(TrafficEvent.page_url)
        .order_by(desc("views"))
        .limit(5)
    )
    
    # Map page URLs to vehicle names (demo data mapping)
    vehicle_mapping = {
        "/": "2024 Toyota Camry SE",
        "/pricing": "2023 Honda CR-V EX",
        "/features": "2024 Ford F-150 XLT",
        "/about": "2023 Tesla Model 3",
        "/contact": "2024 Chevrolet Equinox LT",
        "/signup": "2023 BMW X3 xDrive30i",
        "/test-page": "2024 Hyundai Tucson SEL",
        "/test-production": "2023 Mazda CX-5 Touring"
    }
    
    price_mapping = {
        "2024 Toyota Camry SE": 28995,
        "2023 Honda CR-V EX": 34750,
        "2024 Ford F-150 XLT": 52890,
        "2023 Tesla Model 3": 42990,
        "2024 Chevrolet Equinox LT": 31995,
        "2023 BMW X3 xDrive30i": 48900,
        "2024 Hyundai Tucson SEL": 32450,
        "2023 Mazda CX-5 Touring": 31650
    }
    
    vehicles = []
    for row in result.all():
        vehicle_name = vehicle_mapping.get(row[0], f"Vehicle {row[0]}")
        vehicles.append({
            "vehicle": vehicle_name,
            "views": row[1],
            "avg_price": price_mapping.get(vehicle_name, 29999)
        })
    
    return vehicles

@api_router.get("/dashboard/vehicle-types")
async def dashboard_vehicle_types(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """Demand by vehicle type"""
    business = await get_or_create_business(current_user, session)
    
    # Get total events for distribution
    total_result = await session.execute(
        select(func.count(TrafficEvent.id))
        .where(TrafficEvent.business_id == business.id)
    )
    total = total_result.scalar() or 1
    
    # Simulate vehicle type distribution based on traffic patterns
    types = [
        {"type": "SUV", "count": int(total * 0.35), "percentage": 35},
        {"type": "Sedan", "count": int(total * 0.25), "percentage": 25},
        {"type": "Truck", "count": int(total * 0.20), "percentage": 20},
        {"type": "EV", "count": int(total * 0.12), "percentage": 12},
        {"type": "Hybrid", "count": int(total * 0.08), "percentage": 8}
    ]
    return types

@api_router.get("/dashboard/price-distribution")
async def dashboard_price_distribution(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """Shopper distribution by price buckets"""
    business = await get_or_create_business(current_user, session)
    
    # Get visitor count for distribution
    visitors_result = await session.execute(
        select(func.count(func.distinct(TrafficEvent.visitor_id)))
        .where(TrafficEvent.business_id == business.id)
    )
    total_visitors = visitors_result.scalar() or 100
    
    # Price bucket distribution
    return [
        {"bucket": "Under $20k", "count": int(total_visitors * 0.12), "percentage": 12},
        {"bucket": "$20k–$25k", "count": int(total_visitors * 0.18), "percentage": 18},
        {"bucket": "$25k–$30k", "count": int(total_visitors * 0.28), "percentage": 28},
        {"bucket": "$30k–$35k", "count": int(total_visitors * 0.24), "percentage": 24},
        {"bucket": "$35k+", "count": int(total_visitors * 0.18), "percentage": 18}
    ]

@api_router.get("/dashboard/geographic-demand")
async def dashboard_geographic_demand(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """ZIP-based demand data"""
    business = await get_or_create_business(current_user, session)
    
    # Get city data and map to ZIP codes
    result = await session.execute(
        select(TrafficEvent.city, func.count(func.distinct(TrafficEvent.visitor_id)).label("shoppers"))
        .where(
            TrafficEvent.business_id == business.id,
            TrafficEvent.city.isnot(None)
        )
        .group_by(TrafficEvent.city)
        .order_by(desc("shoppers"))
        .limit(10)
    )
    
    # Map cities to ZIP codes (demo mapping)
    zip_mapping = {
        "New York": "10001",
        "Los Angeles": "90001", 
        "Chicago": "60601",
        "Houston": "77001",
        "Phoenix": "85001",
        "San Antonio": "78201",
        "Dallas": "75201",
        "Austin": "78701",
        "London": "SW1A",
        "Toronto": "M5H",
        "Berlin": "10115",
        "Paris": "75001",
        "Sydney": "2000",
        "Tokyo": "100-0001",
        "São Paulo": "01310"
    }
    
    avg_prices = [31250, 34500, 29800, 32100, 28900, 30500, 35200, 33800, 38500, 27600]
    
    zips = []
    for i, row in enumerate(result.all()):
        city = row[0]
        zips.append({
            "zip": zip_mapping.get(city, f"ZIP-{i+1}"),
            "city": city,
            "shoppers": row[1],
            "avg_price": avg_prices[i] if i < len(avg_prices) else 30000
        })
    
    return zips

@api_router.get("/dashboard/marketing-effectiveness")
async def dashboard_marketing_effectiveness(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """Marketing source effectiveness"""
    business = await get_or_create_business(current_user, session)
    
    # Get UTM sources with visitor counts
    result = await session.execute(
        select(
            TrafficEvent.utm_source,
            func.count(func.distinct(TrafficEvent.visitor_id)).label("shoppers")
        )
        .where(
            TrafficEvent.business_id == business.id,
            TrafficEvent.utm_source.isnot(None)
        )
        .group_by(TrafficEvent.utm_source)
        .order_by(desc("shoppers"))
    )
    
    # Get verified leads count
    leads_result = await session.execute(
        select(func.count(Lead.id))
        .where(Lead.business_id == business.id, Lead.is_verified == True)
    )
    total_leads = leads_result.scalar() or 0
    
    sources = []
    rows = result.all()
    total_shoppers = sum(row[1] for row in rows) or 1
    
    for row in rows:
        source_shoppers = row[1]
        # Distribute leads proportionally
        source_leads = int((source_shoppers / total_shoppers) * total_leads)
        conversion = (source_leads / source_shoppers * 100) if source_shoppers > 0 else 0
        
        sources.append({
            "source": row[0],
            "shoppers": source_shoppers,
            "verified_leads": source_leads,
            "avg_vehicle_price": random.randint(28000, 42000),
            "conversion_rate": round(conversion, 1)
        })
    
    return sources

@api_router.get("/dashboard/recent-activity")
async def dashboard_recent_activity(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """Recent shopper activity feed"""
    business = await get_or_create_business(current_user, session)
    
    # Get recent events
    events_result = await session.execute(
        select(TrafficEvent)
        .where(TrafficEvent.business_id == business.id)
        .order_by(desc(TrafficEvent.created_at))
        .limit(20)
    )
    events = events_result.scalars().all()
    
    # Get recent leads
    leads_result = await session.execute(
        select(Lead)
        .where(Lead.business_id == business.id)
        .order_by(desc(Lead.created_at))
        .limit(10)
    )
    leads = leads_result.scalars().all()
    
    vehicle_names = [
        "2024 Toyota Camry SE", "2023 Honda CR-V EX", "2024 Ford F-150 XLT",
        "2023 Tesla Model 3", "2024 Chevrolet Equinox LT", "2023 BMW X3",
        "2024 Hyundai Tucson", "2023 Mazda CX-5", "2024 Kia Sportage",
        "2023 Subaru Outback"
    ]
    
    activity = []
    
    # Add vehicle view events
    for e in events[:15]:
        activity.append({
            "id": e.id,
            "type": "vehicle_view",
            "vehicle": random.choice(vehicle_names),
            "source": e.utm_source or "Direct",
            "location": e.city or "Unknown",
            "timestamp": e.created_at.isoformat()
        })
    
    # Add lead events
    for l in leads[:5]:
        activity.append({
            "id": l.id,
            "type": "lead_verified" if l.is_verified else "lead_captured",
            "vehicle": random.choice(vehicle_names),
            "email": l.email[:3] + "***@" + l.email.split("@")[1] if "@" in l.email else l.email,
            "timestamp": l.created_at.isoformat()
        })
    
    # Sort by timestamp
    activity.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return activity[:20]

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

@api_router.get("/settings/status")
async def get_system_status(current_user: User = Depends(get_current_user)):
    """Get system status for deployment readiness check"""
    # Check database
    db_status = "not_connected"
    if DATABASE_URL and async_session_maker:
        try:
            async with async_session_maker() as session:
                await session.execute(text("SELECT 1"))
                db_status = "healthy"
        except Exception:
            db_status = "error"
    
    # Check Twilio configuration (without exposing secrets)
    twilio_configured = bool(
        os.getenv("TWILIO_ACCOUNT_SID") and 
        os.getenv("TWILIO_AUTH_TOKEN") and 
        os.getenv("TWILIO_PHONE_NUMBER")
    )
    
    # Check OTP mock mode
    otp_mock_mode = os.getenv("OTP_MOCK_MODE", "true").lower() == "true"
    
    # Detect environment
    app_url = os.getenv("APP_URL", "")
    is_preview = "preview.emergentagent.com" in app_url
    
    return {
        "database": db_status,
        "twilio": twilio_configured,
        "otp_mock_mode": otp_mock_mode,
        "environment": "preview" if is_preview else "deployed"
    }

# ============== Debug Endpoint ==============
@api_router.get("/debug/analytics")
async def debug_analytics(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """Debug endpoint to diagnose analytics data issues"""
    business = await get_or_create_business(current_user, session)
    
    # Count visitors
    visitors_result = await session.execute(
        select(func.count(Visitor.id)).where(Visitor.business_id == business.id)
    )
    visitor_count = visitors_result.scalar() or 0
    
    # Count traffic_events
    events_result = await session.execute(
        select(func.count(TrafficEvent.id)).where(TrafficEvent.business_id == business.id)
    )
    traffic_count = events_result.scalar() or 0
    
    # Count leads
    leads_result = await session.execute(
        select(func.count(Lead.id)).where(Lead.business_id == business.id)
    )
    lead_count = leads_result.scalar() or 0
    
    # Get last 5 traffic events
    recent_events_result = await session.execute(
        select(TrafficEvent)
        .where(TrafficEvent.business_id == business.id)
        .order_by(desc(TrafficEvent.created_at))
        .limit(5)
    )
    recent_events = recent_events_result.scalars().all()
    
    # Count events with utm_source populated
    utm_source_result = await session.execute(
        select(func.count(TrafficEvent.id))
        .where(TrafficEvent.business_id == business.id, TrafficEvent.utm_source.isnot(None))
    )
    utm_source_count = utm_source_result.scalar() or 0
    
    # Count events with country populated
    country_result = await session.execute(
        select(func.count(TrafficEvent.id))
        .where(TrafficEvent.business_id == business.id, TrafficEvent.country.isnot(None))
    )
    country_count = country_result.scalar() or 0
    
    return {
        "business_id": business.id,
        "public_key": business.public_key,
        "counts": {
            "visitors": visitor_count,
            "traffic_events": traffic_count,
            "leads": lead_count,
            "events_with_utm_source": utm_source_count,
            "events_with_country": country_count
        },
        "last_5_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "page_url": e.page_url,
                "utm_source": e.utm_source,
                "utm_campaign": e.utm_campaign,
                "country": e.country,
                "created_at": e.created_at.isoformat() if e.created_at else None
            }
            for e in recent_events
        ],
        "diagnosis": {
            "has_traffic_data": traffic_count > 0,
            "has_utm_data": utm_source_count > 0,
            "has_geo_data": country_count > 0,
            "recommendation": (
                "Generate demo data from Settings page" if traffic_count == 0 
                else "Data exists - check frontend API calls" if (utm_source_count == 0 and country_count == 0)
                else "All looks good - analytics should display"
            )
        }
    }

# ============== Public Routes ==============
def get_price_bucket(price):
    """Categorize price into buckets"""
    if not price:
        return None
    if price < 20000:
        return "Under $20k"
    elif price < 25000:
        return "$20k-$25k"
    elif price < 30000:
        return "$25k-$30k"
    elif price < 35000:
        return "$30k-$35k"
    else:
        return "$35k+"

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
    
    # Calculate price bucket
    price_bucket = get_price_bucket(data.vehicle_price) if data.vehicle_price else None
    
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
        browser=data.browser,
        # Vehicle data
        vehicle_id=data.vehicle_id,
        vehicle_year=data.vehicle_year,
        vehicle_make=data.vehicle_make,
        vehicle_model=data.vehicle_model,
        vehicle_trim=data.vehicle_trim,
        vehicle_price=data.vehicle_price,
        price_bucket=price_bucket,
        zip_code=data.zip_code
    )
    session.add(event)
    await session.commit()
    return {"success": True, "visitor_id": visitor.id}

@api_router.post("/public/vehicle-lead")
async def public_vehicle_lead(data: VehicleLeadRequest, session: AsyncSession = Depends(get_db_session)):
    """Capture vehicle lead from Unlock Instant Price modal"""
    result = await session.execute(select(Business).where(Business.public_key == data.public_key))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Invalid public key")
    
    # Create vehicle lead
    lead = VehicleLead(
        id=str(uuid.uuid4()),
        business_id=business.id,
        session_id=data.session_id,
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        email=data.email,
        contact_method=data.contact_method,
        comments=data.comments,
        vehicle_id=data.vehicle_id,
        vehicle_year=data.vehicle_year,
        vehicle_make=data.vehicle_make,
        vehicle_model=data.vehicle_model,
        vehicle_trim=data.vehicle_trim,
        vehicle_price=data.vehicle_price,
        vehicle_image=data.vehicle_image,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        zip_code=data.zip_code,
        page_url=data.page_url,
        status="new"
    )
    session.add(lead)
    
    # Also track as lead_submit event
    price_bucket = get_price_bucket(data.vehicle_price) if data.vehicle_price else None
    event = TrafficEvent(
        id=str(uuid.uuid4()),
        business_id=business.id,
        event_type="lead_submit",
        page_url=data.page_url,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        vehicle_id=data.vehicle_id,
        vehicle_year=data.vehicle_year,
        vehicle_make=data.vehicle_make,
        vehicle_model=data.vehicle_model,
        vehicle_trim=data.vehicle_trim,
        vehicle_price=data.vehicle_price,
        price_bucket=price_bucket,
        zip_code=data.zip_code
    )
    session.add(event)
    
    await session.commit()
    return {
        "success": True,
        "lead_id": lead.id,
        "message": "Your instant price is being revealed"
    }

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
    # Check if demo mode is enabled (disabled by default in production)
    demo_enabled = os.getenv("DEMO_MODE_ENABLED", "false").lower() == "true"
    if not demo_enabled:
        raise HTTPException(status_code=403, detail="Demo data generation is disabled in production")
    
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
    return '''
(function() {
    'use strict';
    
    var VD = {
        config: {},
        visitorId: null,
        sessionId: null,
        debug: false,
        initialized: false,
        currentVehicle: null,
        
        log: function(msg) {
            if (this.debug && typeof console !== 'undefined') {
                console.log('[VD] ' + msg);
            }
        },
        
        init: function(options) {
            if (this.initialized) {
                this.log('Already initialized');
                return;
            }
            
            this.config = options || {};
            this.debug = this.config.debug === true || this.config.debug === 'true';
            
            this.log('Verified Demand embed loaded');
            this.log('Public key: ' + (this.config.publicKey ? this.config.publicKey.substring(0, 8) + '...' : 'not set'));
            
            this.sessionId = this.getOrCreateSessionId();
            this.injectStyles();
            this.setupTriggers();
            this.trackPageView();
            this.initialized = true;
        },
        
        getOrCreateSessionId: function() {
            var sid;
            try {
                sid = sessionStorage.getItem('vd_session_id');
                if (!sid) {
                    sid = 'vd_' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
                    sessionStorage.setItem('vd_session_id', sid);
                }
            } catch (e) {
                sid = 'vd_' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
            }
            return sid;
        },
        
        getUTMParams: function() {
            try {
                var params = new URLSearchParams(window.location.search);
                return {
                    utm_source: params.get('utm_source'),
                    utm_medium: params.get('utm_medium'),
                    utm_campaign: params.get('utm_campaign')
                };
            } catch (e) {
                return { utm_source: null, utm_medium: null, utm_campaign: null };
            }
        },
        
        getDeviceInfo: function() {
            var isMobile = /Mobile|Android|iPhone|iPad/i.test(navigator.userAgent);
            var browser = 'Other';
            var ua = navigator.userAgent;
            if (ua.indexOf('Chrome') > -1 && ua.indexOf('Edg') === -1) browser = 'Chrome';
            else if (ua.indexOf('Firefox') > -1) browser = 'Firefox';
            else if (ua.indexOf('Safari') > -1 && ua.indexOf('Chrome') === -1) browser = 'Safari';
            else if (ua.indexOf('Edg') > -1) browser = 'Edge';
            return { device_type: isMobile ? 'mobile' : 'desktop', browser: browser };
        },
        
        track: function(eventType, vehicleData) {
            var self = this;
            var utm = this.getUTMParams();
            var device = this.getDeviceInfo();
            var payload = {
                public_key: this.config.publicKey,
                session_id: this.sessionId,
                event_type: eventType,
                page_url: window.location.pathname,
                referrer: document.referrer,
                utm_source: utm.utm_source,
                utm_medium: utm.utm_medium,
                utm_campaign: utm.utm_campaign,
                device_type: device.device_type,
                browser: device.browser
            };
            
            if (vehicleData) {
                payload.vehicle_id = vehicleData.vehicle_id;
                payload.vehicle_year = vehicleData.vehicle_year;
                payload.vehicle_make = vehicleData.vehicle_make;
                payload.vehicle_model = vehicleData.vehicle_model;
                payload.vehicle_trim = vehicleData.vehicle_trim;
                payload.vehicle_price = vehicleData.vehicle_price ? parseInt(vehicleData.vehicle_price) : null;
                payload.zip_code = vehicleData.zip_code;
            }
            
            fetch(this.config.apiUrl + '/api/public/track', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.visitor_id) self.visitorId = d.visitor_id;
                self.log('Track: ' + eventType);
            }).catch(function(err) {
                self.log('Track failed: ' + eventType);
            });
        },
        
        trackPageView: function() {
            this.track('pageview');
        },
        
        injectStyles: function() {
            if (document.getElementById('vd-styles')) return;
            var style = document.createElement('style');
            style.id = 'vd-styles';
            style.textContent = `
                .vd-modal-overlay {
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background: rgba(15, 23, 42, 0.7);
                    backdrop-filter: blur(4px);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 999999;
                    padding: 20px;
                    box-sizing: border-box;
                }
                .vd-modal {
                    background: #ffffff;
                    border-radius: 16px;
                    box-shadow: 0 25px 80px rgba(0, 0, 0, 0.4);
                    max-width: 900px;
                    width: 100%;
                    max-height: 90vh;
                    overflow: hidden;
                    display: flex;
                    position: relative;
                    animation: vdSlideIn 0.3s ease;
                }
                @keyframes vdSlideIn {
                    from { opacity: 0; transform: translateY(20px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                .vd-modal-left {
                    flex: 1;
                    background: linear-gradient(135deg, #1E3A8A 0%, #0F172A 100%);
                    color: white;
                    padding: 40px;
                    display: flex;
                    flex-direction: column;
                }
                .vd-modal-right {
                    flex: 1;
                    padding: 40px;
                    overflow-y: auto;
                }
                .vd-vehicle-image {
                    width: 100%;
                    height: 200px;
                    object-fit: cover;
                    border-radius: 12px;
                    margin-bottom: 24px;
                    background: rgba(255,255,255,0.1);
                }
                .vd-vehicle-title {
                    font-size: 24px;
                    font-weight: 700;
                    margin-bottom: 8px;
                }
                .vd-vehicle-trim {
                    font-size: 16px;
                    opacity: 0.8;
                    margin-bottom: 24px;
                }
                .vd-price-locked {
                    background: rgba(255,255,255,0.1);
                    border-radius: 12px;
                    padding: 20px;
                    text-align: center;
                    margin-top: auto;
                }
                .vd-lock-icon {
                    font-size: 32px;
                    margin-bottom: 8px;
                }
                .vd-price-text {
                    font-size: 18px;
                    font-weight: 600;
                }
                .vd-price-subtext {
                    font-size: 14px;
                    opacity: 0.7;
                    margin-top: 4px;
                }
                .vd-close-btn {
                    position: absolute;
                    top: 16px;
                    right: 16px;
                    background: none;
                    border: none;
                    font-size: 28px;
                    cursor: pointer;
                    color: #9CA3AF;
                    line-height: 1;
                    padding: 4px;
                    z-index: 10;
                }
                .vd-close-btn:hover { color: #1F2937; }
                .vd-form-title {
                    font-size: 24px;
                    font-weight: 700;
                    color: #1F2937;
                    margin-bottom: 8px;
                }
                .vd-form-subtitle {
                    font-size: 14px;
                    color: #6B7280;
                    margin-bottom: 24px;
                }
                .vd-form-row {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 12px;
                    margin-bottom: 16px;
                }
                .vd-form-group {
                    margin-bottom: 16px;
                }
                .vd-form-group label {
                    display: block;
                    font-size: 14px;
                    font-weight: 500;
                    color: #1F2937;
                    margin-bottom: 6px;
                }
                .vd-form-group label .vd-required {
                    color: #DC2626;
                }
                .vd-form-group input,
                .vd-form-group select,
                .vd-form-group textarea {
                    width: 100%;
                    padding: 12px 14px;
                    border: 1px solid #E5E7EB;
                    border-radius: 8px;
                    font-size: 15px;
                    font-family: inherit;
                    box-sizing: border-box;
                    transition: border-color 0.2s, box-shadow 0.2s;
                }
                .vd-form-group input:focus,
                .vd-form-group select:focus,
                .vd-form-group textarea:focus {
                    outline: none;
                    border-color: #1E3A8A;
                    box-shadow: 0 0 0 3px rgba(30, 58, 138, 0.1);
                }
                .vd-form-group textarea {
                    min-height: 80px;
                    resize: vertical;
                }
                .vd-contact-options {
                    display: flex;
                    gap: 12px;
                    margin-bottom: 16px;
                }
                .vd-contact-option {
                    flex: 1;
                    padding: 12px;
                    border: 2px solid #E5E7EB;
                    border-radius: 8px;
                    text-align: center;
                    cursor: pointer;
                    transition: all 0.2s;
                    background: white;
                }
                .vd-contact-option:hover {
                    border-color: #1E3A8A;
                }
                .vd-contact-option.selected {
                    border-color: #1E3A8A;
                    background: #EFF6FF;
                }
                .vd-contact-option-icon {
                    font-size: 20px;
                    margin-bottom: 4px;
                }
                .vd-contact-option-label {
                    font-size: 13px;
                    font-weight: 500;
                    color: #1F2937;
                }
                .vd-submit-btn {
                    width: 100%;
                    padding: 14px 24px;
                    background: #1E3A8A;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.2s;
                    font-family: inherit;
                }
                .vd-submit-btn:hover:not(:disabled) {
                    background: #1E40AF;
                    transform: translateY(-1px);
                }
                .vd-submit-btn:disabled {
                    opacity: 0.6;
                    cursor: not-allowed;
                }
                .vd-disclaimer {
                    font-size: 11px;
                    color: #9CA3AF;
                    margin-top: 16px;
                    line-height: 1.5;
                }
                .vd-powered-by {
                    text-align: center;
                    margin-top: 20px;
                    font-size: 12px;
                    color: #9CA3AF;
                }
                .vd-powered-by a {
                    color: #6B7280;
                    text-decoration: none;
                }
                .vd-error {
                    color: #DC2626;
                    font-size: 14px;
                    margin-bottom: 16px;
                    padding: 12px;
                    background: #FEF2F2;
                    border-radius: 8px;
                    display: none;
                }
                .vd-success-state {
                    text-align: center;
                    padding: 40px 20px;
                }
                .vd-success-icon {
                    font-size: 64px;
                    margin-bottom: 16px;
                }
                .vd-success-title {
                    font-size: 24px;
                    font-weight: 700;
                    color: #1F2937;
                    margin-bottom: 8px;
                }
                .vd-success-message {
                    font-size: 16px;
                    color: #6B7280;
                }
                .vd-loading {
                    display: inline-block;
                    width: 20px;
                    height: 20px;
                    border: 2px solid rgba(255,255,255,0.3);
                    border-radius: 50%;
                    border-top-color: white;
                    animation: vdSpin 1s linear infinite;
                    margin-right: 8px;
                    vertical-align: middle;
                }
                @keyframes vdSpin {
                    to { transform: rotate(360deg); }
                }
                @media (max-width: 768px) {
                    .vd-modal {
                        flex-direction: column;
                        max-height: 100vh;
                        height: 100%;
                        border-radius: 0;
                    }
                    .vd-modal-left {
                        padding: 24px;
                        flex: none;
                    }
                    .vd-vehicle-image {
                        height: 140px;
                        margin-bottom: 16px;
                    }
                    .vd-modal-right {
                        padding: 24px;
                        flex: 1;
                        overflow-y: auto;
                    }
                    .vd-form-row {
                        grid-template-columns: 1fr;
                    }
                    .vd-price-locked {
                        padding: 16px;
                    }
                }
            `;
            document.head.appendChild(style);
        },
        
        setupTriggers: function() {
            var self = this;
            
            // Event delegation for data-vd-trigger clicks
            document.addEventListener('click', function(e) {
                var target = e.target;
                while (target && target !== document) {
                    if (target.hasAttribute && target.hasAttribute('data-vd-trigger')) {
                        e.preventDefault();
                        e.stopPropagation();
                        var vehicleData = self.extractVehicleData(target);
                        self.track('unlock_click', vehicleData);
                        self.openModal(vehicleData);
                        return;
                    }
                    target = target.parentNode;
                }
            }, true);
            
            // MutationObserver for dynamically added triggers
            if (typeof MutationObserver !== 'undefined') {
                var observer = new MutationObserver(function(mutations) {
                    // Just log that DOM changed - triggers handled by delegation
                    self.log('DOM updated - triggers ready via delegation');
                });
                observer.observe(document.body, { childList: true, subtree: true });
            }
            
            this.log('Triggers setup complete');
        },
        
        extractVehicleData: function(element) {
            var data = {
                vehicle_id: element.getAttribute('data-vd-vehicle-id'),
                vehicle_year: element.getAttribute('data-vd-year'),
                vehicle_make: element.getAttribute('data-vd-make'),
                vehicle_model: element.getAttribute('data-vd-model'),
                vehicle_trim: element.getAttribute('data-vd-trim'),
                vehicle_price: element.getAttribute('data-vd-price'),
                vehicle_image: element.getAttribute('data-vd-image'),
                zip_code: element.getAttribute('data-vd-zip')
            };
            
            // Fallback: Try to infer from nearest vehicle card
            if (!data.vehicle_year && !data.vehicle_make) {
                data = this.inferVehicleData(element, data);
            }
            
            this.log('Vehicle data: ' + JSON.stringify(data));
            return data;
        },
        
        inferVehicleData: function(element, data) {
            var card = element.closest('[class*="vehicle"], [class*="listing"], [class*="inventory"], [class*="card"]');
            if (!card) card = element.parentElement;
            if (!card) return data;
            
            // Try to find title/heading
            var titleEl = card.querySelector('h1, h2, h3, h4, [class*="title"], [class*="name"]');
            if (titleEl) {
                var title = titleEl.textContent.trim();
                // Try to parse "2024 Toyota Camry XSE" format
                var match = title.match(/(\\d{4})\\s+([A-Za-z]+)\\s+([A-Za-z0-9]+)\\s*(.*)?/);
                if (match) {
                    data.vehicle_year = data.vehicle_year || match[1];
                    data.vehicle_make = data.vehicle_make || match[2];
                    data.vehicle_model = data.vehicle_model || match[3];
                    data.vehicle_trim = data.vehicle_trim || (match[4] || '').trim();
                }
            }
            
            // Try to find price
            var priceEl = card.querySelector('[class*="price"], [data-price]');
            if (priceEl && !data.vehicle_price) {
                var priceText = priceEl.textContent || priceEl.getAttribute('data-price');
                var priceMatch = priceText.replace(/[^0-9]/g, '');
                if (priceMatch) data.vehicle_price = priceMatch;
            }
            
            // Try to find image
            var imgEl = card.querySelector('img[src*="vehicle"], img[src*="inventory"], img');
            if (imgEl && !data.vehicle_image) {
                data.vehicle_image = imgEl.src;
            }
            
            return data;
        },
        
        formatVehicleTitle: function(data) {
            var parts = [];
            if (data.vehicle_year) parts.push(data.vehicle_year);
            if (data.vehicle_make) parts.push(data.vehicle_make);
            if (data.vehicle_model) parts.push(data.vehicle_model);
            return parts.length > 0 ? parts.join(' ') : 'Vehicle Details';
        },
        
        formatPrice: function(price) {
            if (!price) return '';
            var num = parseInt(price);
            return '$' + num.toLocaleString('en-US');
        },
        
        openModal: function(vehicleData) {
            if (document.getElementById('vd-modal-overlay')) {
                this.log('Modal already open');
                return;
            }
            
            this.currentVehicle = vehicleData;
            this.track('modal_open', vehicleData);
            
            var self = this;
            var isMobile = window.innerWidth < 768;
            var vehicleTitle = this.formatVehicleTitle(vehicleData);
            var vehicleTrim = vehicleData.vehicle_trim || '';
            var vehicleImage = vehicleData.vehicle_image || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200"%3E%3Crect fill="%231E3A8A" width="400" height="200"/%3E%3Ctext fill="white" x="200" y="105" text-anchor="middle" font-family="sans-serif" font-size="16"%3EVehicle Image%3C/text%3E%3C/svg%3E';
            var priceDisplay = vehicleData.vehicle_price ? this.formatPrice(vehicleData.vehicle_price) : 'Price Available';
            
            var overlay = document.createElement('div');
            overlay.id = 'vd-modal-overlay';
            overlay.className = 'vd-modal-overlay';
            overlay.innerHTML = `
                <div class="vd-modal">
                    <button class="vd-close-btn" id="vd-close">&times;</button>
                    <div class="vd-modal-left">
                        <img class="vd-vehicle-image" src="${vehicleImage}" alt="${vehicleTitle}" onerror="this.style.background='#1E3A8A'">
                        <div class="vd-vehicle-title">${vehicleTitle}</div>
                        <div class="vd-vehicle-trim">${vehicleTrim}</div>
                        <div class="vd-price-locked">
                            <div class="vd-lock-icon">🔒</div>
                            <div class="vd-price-text">Instant Price Locked</div>
                            <div class="vd-price-subtext">Unlock to see your best price</div>
                        </div>
                    </div>
                    <div class="vd-modal-right">
                        <div id="vd-form-container">
                            <div class="vd-form-title">Unlock Your Instant Price</div>
                            <div class="vd-form-subtitle">Get exclusive pricing sent directly to you</div>
                            <div class="vd-error" id="vd-error"></div>
                            <div class="vd-form-row">
                                <div class="vd-form-group">
                                    <label>First Name <span class="vd-required">*</span></label>
                                    <input type="text" id="vd-first-name" placeholder="John" required>
                                </div>
                                <div class="vd-form-group">
                                    <label>Last Name <span class="vd-required">*</span></label>
                                    <input type="text" id="vd-last-name" placeholder="Smith" required>
                                </div>
                            </div>
                            <div class="vd-form-group">
                                <label>Phone Number <span class="vd-required">*</span></label>
                                <input type="tel" id="vd-phone" placeholder="(555) 123-4567" required>
                            </div>
                            <div class="vd-form-group">
                                <label>Preferred Contact Method <span class="vd-required">*</span></label>
                            </div>
                            <div class="vd-contact-options">
                                <div class="vd-contact-option selected" data-method="text">
                                    <div class="vd-contact-option-icon">💬</div>
                                    <div class="vd-contact-option-label">Text</div>
                                </div>
                                <div class="vd-contact-option" data-method="call">
                                    <div class="vd-contact-option-icon">📞</div>
                                    <div class="vd-contact-option-label">Call</div>
                                </div>
                                <div class="vd-contact-option" data-method="email">
                                    <div class="vd-contact-option-icon">✉️</div>
                                    <div class="vd-contact-option-label">Email</div>
                                </div>
                            </div>
                            <div class="vd-form-group">
                                <label>Email (Optional)</label>
                                <input type="email" id="vd-email" placeholder="john@example.com">
                            </div>
                            <div class="vd-form-group">
                                <label>Comments (Optional)</label>
                                <textarea id="vd-comments" placeholder="Any questions or specific requests?"></textarea>
                            </div>
                            <button class="vd-submit-btn" id="vd-submit" disabled>Unlock Instant Price</button>
                            <div class="vd-disclaimer">
                                By clicking "Unlock Instant Price", you consent to receive autodialed calls, texts, and emails from this dealership. Consent is not a condition of purchase. Message and data rates may apply.
                            </div>
                        </div>
                        <div id="vd-success-container" class="vd-success-state" style="display:none;">
                            <div class="vd-success-icon">🎉</div>
                            <div class="vd-success-title">Your Instant Price is Being Revealed!</div>
                            <div class="vd-success-message">A team member will contact you shortly with your exclusive pricing.</div>
                        </div>
                        <div class="vd-powered-by">
                            Powered by <a href="https://verifieddemand.com" target="_blank">Verified Demand</a>
                        </div>
                    </div>
                </div>
            `;
            
            document.body.appendChild(overlay);
            document.body.style.overflow = 'hidden';
            
            // Event handlers
            document.getElementById('vd-close').onclick = function() { self.closeModal(); };
            overlay.onclick = function(e) { if (e.target === overlay) self.closeModal(); };
            
            // Contact method selection
            var contactOptions = overlay.querySelectorAll('.vd-contact-option');
            contactOptions.forEach(function(opt) {
                opt.onclick = function() {
                    contactOptions.forEach(function(o) { o.classList.remove('selected'); });
                    opt.classList.add('selected');
                    self.selectedContactMethod = opt.getAttribute('data-method');
                    self.validateForm();
                };
            });
            self.selectedContactMethod = 'text';
            
            // Form validation
            var inputs = overlay.querySelectorAll('#vd-first-name, #vd-last-name, #vd-phone');
            inputs.forEach(function(input) {
                input.oninput = function() { self.validateForm(); };
            });
            
            // Phone formatting
            document.getElementById('vd-phone').oninput = function(e) {
                var x = e.target.value.replace(/\\D/g, '').match(/(\\d{0,3})(\\d{0,3})(\\d{0,4})/);
                e.target.value = !x[2] ? x[1] : '(' + x[1] + ') ' + x[2] + (x[3] ? '-' + x[3] : '');
                self.validateForm();
            };
            
            // Submit handler
            document.getElementById('vd-submit').onclick = function() { self.submitLead(); };
            
            // ESC key to close
            this.escHandler = function(e) { if (e.key === 'Escape') self.closeModal(); };
            document.addEventListener('keydown', this.escHandler);
            
            this.log('Modal opened');
        },
        
        validateForm: function() {
            var firstName = document.getElementById('vd-first-name').value.trim();
            var lastName = document.getElementById('vd-last-name').value.trim();
            var phone = document.getElementById('vd-phone').value.replace(/\\D/g, '');
            var submitBtn = document.getElementById('vd-submit');
            
            var isValid = firstName.length > 0 && lastName.length > 0 && phone.length >= 10;
            submitBtn.disabled = !isValid;
        },
        
        closeModal: function() {
            var overlay = document.getElementById('vd-modal-overlay');
            if (overlay) {
                overlay.parentNode.removeChild(overlay);
                document.body.style.overflow = '';
                if (this.escHandler) {
                    document.removeEventListener('keydown', this.escHandler);
                }
            }
            this.log('Modal closed');
        },
        
        submitLead: function() {
            var self = this;
            var submitBtn = document.getElementById('vd-submit');
            var errorEl = document.getElementById('vd-error');
            
            var firstName = document.getElementById('vd-first-name').value.trim();
            var lastName = document.getElementById('vd-last-name').value.trim();
            var phone = document.getElementById('vd-phone').value.trim();
            var email = document.getElementById('vd-email').value.trim();
            var comments = document.getElementById('vd-comments').value.trim();
            
            if (!firstName || !lastName || !phone) {
                errorEl.textContent = 'Please fill in all required fields.';
                errorEl.style.display = 'block';
                return;
            }
            
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="vd-loading"></span>Submitting...';
            errorEl.style.display = 'none';
            
            var utm = this.getUTMParams();
            var payload = {
                public_key: this.config.publicKey,
                session_id: this.sessionId,
                first_name: firstName,
                last_name: lastName,
                phone: phone,
                email: email || null,
                contact_method: this.selectedContactMethod,
                comments: comments || null,
                vehicle_id: this.currentVehicle.vehicle_id,
                vehicle_year: this.currentVehicle.vehicle_year,
                vehicle_make: this.currentVehicle.vehicle_make,
                vehicle_model: this.currentVehicle.vehicle_model,
                vehicle_trim: this.currentVehicle.vehicle_trim,
                vehicle_price: this.currentVehicle.vehicle_price ? parseInt(this.currentVehicle.vehicle_price) : null,
                vehicle_image: this.currentVehicle.vehicle_image,
                utm_source: utm.utm_source,
                utm_medium: utm.utm_medium,
                utm_campaign: utm.utm_campaign,
                zip_code: this.currentVehicle.zip_code,
                page_url: window.location.href
            };
            
            fetch(this.config.apiUrl + '/api/public/vehicle-lead', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.success) {
                    self.track('lead_submit', self.currentVehicle);
                    document.getElementById('vd-form-container').style.display = 'none';
                    document.getElementById('vd-success-container').style.display = 'block';
                    self.log('Lead submitted: ' + d.lead_id);
                } else {
                    throw new Error(d.detail || 'Submission failed');
                }
            }).catch(function(e) {
                errorEl.textContent = 'There was an error. Please try again.';
                errorEl.style.display = 'block';
                submitBtn.disabled = false;
                submitBtn.innerHTML = 'Unlock Instant Price';
                self.log('Lead submission error: ' + e.message);
            });
        }
    };
    
    // Auto-init from script tag attributes
    var script = document.currentScript || document.querySelector('script[data-public-key]');
    if (script) {
        var publicKey = script.getAttribute('data-public-key');
        var debugMode = script.getAttribute('data-debug');
        var apiUrl = script.src.replace('/api/embed.js', '').replace('/embed.js', '');
        
        if (publicKey) {
            VD.init({ 
                publicKey: publicKey, 
                apiUrl: apiUrl,
                debug: debugMode === 'true'
            });
        }
    }
    
    window.VerifiedDemand = VD;
})();
'''

@api_router.get("/embed.js", response_class=PlainTextResponse)
async def serve_embed_js_api():
    return get_embed_script()

@api_router.delete("/admin/clear-data")
async def clear_all_data(current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)):
    """Clear all demo data for the current user's business"""
    business = await get_or_create_business(current_user, session)
    
    # Delete traffic events
    await session.execute(text("DELETE FROM traffic_events WHERE business_id = :bid"), {"bid": business.id})
    
    # Delete visitors
    await session.execute(text("DELETE FROM visitors WHERE business_id = :bid"), {"bid": business.id})
    
    # Delete leads
    await session.execute(text("DELETE FROM leads WHERE business_id = :bid"), {"bid": business.id})
    
    # Delete vehicle_leads if table exists
    try:
        await session.execute(text("DELETE FROM vehicle_leads WHERE business_id = :bid"), {"bid": business.id})
    except:
        pass
    
    await session.commit()
    return {"success": True, "message": "All data cleared"}

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
