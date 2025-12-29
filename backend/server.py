from fastapi import FastAPI, APIRouter, Query, BackgroundTasks, Request, Depends, HTTPException
from fastapi.responses import Response, PlainTextResponse, JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any
import uuid
from datetime import datetime, timezone, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio
import hashlib
import random
import json
import string
import jwt
import bcrypt


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# SMTP Configuration
SMTP_CONFIG = {
    "host": os.environ.get("SMTP_HOST"),
    "port": int(os.environ.get("SMTP_PORT", 587)),
    "user": os.environ.get("SMTP_USER"),
    "password": os.environ.get("SMTP_PASS"),
    "from_email": os.environ.get("SMTP_FROM")
}

# SMS/Twilio Configuration
SMS_CONFIG = {
    "provider": os.environ.get("SMS_PROVIDER", "twilio"),
    "twilio_account_sid": os.environ.get("TWILIO_ACCOUNT_SID"),
    "twilio_auth_token": os.environ.get("TWILIO_AUTH_TOKEN"),
    "twilio_from_number": os.environ.get("TWILIO_FROM_NUMBER")
}

# OTP Configuration
OTP_EXPIRY_SECONDS = 600  # 10 minutes
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = 30  # seconds
RATE_LIMIT_PER_PHONE = 3  # max OTP requests per phone per 10 minutes
OTP_LOCKOUT_SECONDS = 900  # 15 minutes lockout after max attempts

# Auth Configuration
JWT_SECRET = os.environ.get("JWT_SECRET", "change_this_secret_in_production")
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))
ADMIN_SETUP_KEY = os.environ.get("ADMIN_SETUP_KEY", "")
AUTH_COOKIE_NAME = "vd_auth_token"
AUTH_RATE_LIMIT_LOGIN = 10  # Max login attempts per IP per 10 minutes
AUTH_MIN_PASSWORD_LENGTH = 10  # Minimum password length

def is_smtp_configured() -> bool:
    """Check if SMTP is properly configured"""
    return all([
        SMTP_CONFIG["host"],
        SMTP_CONFIG["user"],
        SMTP_CONFIG["password"],
        SMTP_CONFIG["from_email"]
    ])


def is_sms_configured() -> bool:
    """Check if SMS (Twilio) is properly configured"""
    return all([
        SMS_CONFIG["twilio_account_sid"],
        SMS_CONFIG["twilio_auth_token"],
        SMS_CONFIG["twilio_from_number"]
    ])

def is_development_mode() -> bool:
    """Check if running in development mode"""
    return os.environ.get("ENV", "production").lower() == "development"

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks


# Tracking event model
class TrackEvent(BaseModel):
    event: str
    publicKey: str
    timestamp: Optional[str] = None
    url: Optional[str] = None
    referrer: Optional[str] = None
    data: Optional[Any] = None


# Lead submission model
class VehicleLead(BaseModel):
    publicKey: str
    name: str
    email: str
    phone: str
    vehicle: Optional[Any] = None
    url: Optional[str] = None
    referrer: Optional[str] = None
    # Honeypot field - should be empty for real users
    company: Optional[str] = None
    website: Optional[str] = None


# CORS headers for public endpoints
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


# ============================================
# Rate Limiting (In-Memory)
# ============================================
from collections import defaultdict
import time
import re

# Rate limit storage: {key: [(timestamp1, timestamp2, ...)]}
rate_limit_store = defaultdict(list)
RATE_LIMIT_WINDOW = 600  # 10 minutes in seconds
RATE_LIMIT_PER_IP = 10
RATE_LIMIT_PER_KEY = 30


def clean_old_entries(entries: list, window: int) -> list:
    """Remove entries older than the window"""
    cutoff = time.time() - window
    return [t for t in entries if t > cutoff]


def check_rate_limit(identifier: str, limit: int) -> bool:
    """Check if identifier has exceeded rate limit. Returns True if OK, False if exceeded."""
    global rate_limit_store
    
    current_time = time.time()
    entries = rate_limit_store[identifier]
    
    # Clean old entries
    entries = clean_old_entries(entries, RATE_LIMIT_WINDOW)
    rate_limit_store[identifier] = entries
    
    if len(entries) >= limit:
        return False  # Rate limit exceeded
    
    # Add new entry
    entries.append(current_time)
    return True


def get_client_ip(request) -> str:
    """Get client IP, respecting X-Forwarded-For header"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP in the chain
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ============================================
# Authentication Helpers
# ============================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password strength.
    Returns (is_valid, error_message)
    """
    if len(password) < AUTH_MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {AUTH_MIN_PASSWORD_LENGTH} characters"
    
    # Check for at least one uppercase, one lowercase, one digit
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    
    if not (has_upper and has_lower and has_digit):
        return False, "Password must contain at least one uppercase letter, one lowercase letter, and one number"
    
    return True, ""


def generate_temp_password() -> str:
    """Generate a temporary password for admin-created users"""
    # Generate a readable password: 2 words + 2 digits + symbol
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=12)) + random.choice("!@#$%")


def create_jwt_token(user_id: str, email: str, role: str) -> str:
    """Create JWT token for user"""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_jwt_token(token: str) -> Optional[dict]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        return None


async def get_current_user(request: Request) -> Optional[dict]:
    """Extract current user from JWT cookie"""
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None
    
    payload = decode_jwt_token(token)
    if not payload:
        return None
    
    # Verify user still exists and is active
    user = await db.users.find_one({
        "id": payload.get("user_id"),
        "is_active": True
    })
    
    if not user:
        return None
    
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user.get("role", "user")
    }


async def require_auth(request: Request) -> dict:
    """Dependency to require authentication"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(request: Request) -> dict:
    """Dependency to require admin role"""
    user = await require_auth(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ============================================
# Input Validation
# ============================================

def validate_email(email: str) -> tuple[str, bool]:
    """Validate and normalize email. Returns (normalized_email, is_valid)"""
    if not email:
        return "", False
    
    # Normalize
    email = email.strip().lower()
    
    # Basic email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    is_valid = bool(re.match(pattern, email))
    
    return email, is_valid


def validate_phone(phone: str) -> tuple[str, bool]:
    """Validate and normalize phone. Returns (normalized_phone, is_valid)"""
    if not phone:
        return "", False
    
    # Strip non-digits
    digits_only = re.sub(r'\D', '', phone)
    
    # Valid if at least 10 digits
    is_valid = len(digits_only) >= 10
    
    return phone.strip(), is_valid


def check_honeypot(lead: VehicleLead) -> bool:
    """Check if honeypot fields are filled (indicates bot). Returns True if spam suspected."""
    # If either honeypot field has content, it's likely a bot
    if lead.company and lead.company.strip():
        return True
    if lead.website and lead.website.strip():
        return True
    return False


# ============================================
# Email Notification Functions
# ============================================

def format_vehicle_summary(vehicle: Optional[dict]) -> str:
    """Format vehicle data into a readable summary"""
    if not vehicle:
        return "No vehicle data provided"
    
    # Try to build a summary from common fields
    parts = []
    if vehicle.get("year"):
        parts.append(str(vehicle["year"]))
    if vehicle.get("make"):
        parts.append(str(vehicle["make"]))
    if vehicle.get("model"):
        parts.append(str(vehicle["model"]))
    if vehicle.get("trim"):
        parts.append(str(vehicle["trim"]))
    
    if parts:
        return " ".join(parts)
    
    # Fallback: show first few key-value pairs
    summary_parts = []
    for key, value in list(vehicle.items())[:5]:
        if value and key not in ["trackId", "elementTag", "elementText", "elementId"]:
            summary_parts.append(f"{key}: {value}")
    
    return ", ".join(summary_parts) if summary_parts else "Vehicle data available"


def build_lead_email_html(site: dict, lead: dict, timestamp: str) -> str:
    """Build HTML email content for lead notification"""
    vehicle_summary = format_vehicle_summary(lead.get("vehicle"))
    source_url = lead.get("url") or lead.get("source_url") or "Not provided"
    
    # Build verification badge and unlock code section
    verification_badge = ""
    unlock_code_section = ""
    if lead.get("is_verified"):
        verification_badge = '<span style="display:inline-block;background:#dcfce7;color:#166534;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:bold;margin-left:10px;">✓ PHONE VERIFIED</span>'
        if lead.get("unlock_code"):
            unlock_code_section = f'''
                <div style="background:#f0f9ff;border:2px solid #0ea5e9;border-radius:8px;padding:15px;margin:15px 0;text-align:center;">
                    <div style="font-size:12px;color:#0369a1;text-transform:uppercase;font-weight:bold;margin-bottom:5px;">Confirmation Code</div>
                    <div style="font-size:28px;font-weight:bold;color:#0c4a6e;letter-spacing:2px;">{lead.get("unlock_code")}</div>
                </div>
            '''
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #2563eb; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
            .content {{ background: #f9fafb; padding: 20px; border: 1px solid #e5e7eb; }}
            .lead-info {{ background: white; padding: 15px; border-radius: 8px; margin: 15px 0; }}
            .label {{ font-weight: bold; color: #6b7280; font-size: 12px; text-transform: uppercase; }}
            .value {{ font-size: 16px; margin-bottom: 12px; }}
            .footer {{ text-align: center; padding: 15px; color: #9ca3af; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">🎉 New Lead Received! {verification_badge}</h2>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">{site.get('name', 'Unknown Site')}</p>
            </div>
            <div class="content">
                {unlock_code_section}
                <div class="lead-info">
                    <div class="label">Contact Name</div>
                    <div class="value">{lead.get('name', 'Not provided')}</div>
                    
                    <div class="label">Email</div>
                    <div class="value"><a href="mailto:{lead.get('email', '')}">{lead.get('email', 'Not provided')}</a></div>
                    
                    <div class="label">Phone</div>
                    <div class="value"><a href="tel:{lead.get('phone', '')}">{lead.get('phone', 'Not provided')}</a></div>
                    
                    <div class="label">Vehicle Interest</div>
                    <div class="value">{vehicle_summary}</div>
                    
                    <div class="label">Source Page</div>
                    <div class="value"><a href="{source_url}">{source_url}</a></div>
                    
                    <div class="label">Submitted At</div>
                    <div class="value">{timestamp}</div>
                </div>
                
                <p style="color: #6b7280; font-size: 14px;">
                    <strong>Site:</strong> {site.get('name', 'Unknown')} 
                    {f"({site.get('domain')})" if site.get('domain') else ""}
                    <br>
                    <strong>Public Key:</strong> <code>{lead.get('publicKey', 'Unknown')}</code>
                </p>
            </div>
            <div class="footer">
                Powered by VerifiedDemand
            </div>
        </div>
    </body>
    </html>
    """
    return html


def build_lead_email_text(site: dict, lead: dict, timestamp: str) -> str:
    """Build plain text email content for lead notification"""
    vehicle_summary = format_vehicle_summary(lead.get("vehicle"))
    source_url = lead.get("url") or lead.get("source_url") or "Not provided"
    
    # Build verification and unlock code section for text email
    verification_text = ""
    if lead.get("is_verified"):
        verification_text = " [✓ PHONE VERIFIED]"
        if lead.get("unlock_code"):
            verification_text += f"\n\n*** CONFIRMATION CODE: {lead.get('unlock_code')} ***\n"
    
    text = f"""
New Lead Received!{verification_text}
==================

Site: {site.get('name', 'Unknown Site')} {f"({site.get('domain')})" if site.get('domain') else ""}

LEAD DETAILS
------------
Name: {lead.get('name', 'Not provided')}
Email: {lead.get('email', 'Not provided')}
Phone: {lead.get('phone', 'Not provided')}
Vehicle: {vehicle_summary}
Source URL: {source_url}
Submitted: {timestamp}
Public Key: {lead.get('publicKey', 'Unknown')}

---
Powered by VerifiedDemand
"""
    return text


def send_email_sync(to_emails: List[str], subject: str, html_content: str, text_content: str) -> bool:
    """Send email synchronously (to be run in thread pool)"""
    if not is_smtp_configured():
        logger.warning("SMTP not configured, skipping email send")
        return False
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_CONFIG["from_email"]
        msg["To"] = ", ".join(to_emails)
        
        # Attach both plain text and HTML versions
        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))
        
        # Connect and send
        with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"]) as server:
            server.starttls()
            server.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
            server.sendmail(SMTP_CONFIG["from_email"], to_emails, msg.as_string())
        
        logger.info(f"Email sent successfully to {to_emails}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


async def send_email_async(to_emails: List[str], subject: str, html_content: str, text_content: str) -> bool:
    """Send email asynchronously using thread pool"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, send_email_sync, to_emails, subject, html_content, text_content)


async def resolve_site_by_public_key(public_key: str) -> Optional[dict]:
    """Resolve a site by current or previous public key"""
    site = await db.sites.find_one({
        "$or": [
            {"public_key": public_key},
            {"previous_public_keys": public_key}
        ]
    })
    return site


async def send_lead_notification(lead: dict):
    """Send lead notification emails to site owners"""
    public_key = lead.get("publicKey")
    if not public_key:
        logger.warning("Lead missing publicKey, skipping notification")
        return
    
    # Resolve the site
    site = await resolve_site_by_public_key(public_key)
    if not site:
        logger.info(f"No site found for key {public_key}, skipping notification")
        return
    
    # Check if site is active and has notification emails
    if not site.get("is_active", True):
        logger.info(f"Site {site.get('name')} is inactive, skipping notification")
        return
    
    notification_emails = site.get("notification_emails", [])
    if not notification_emails:
        logger.info(f"Site {site.get('name')} has no notification emails configured")
        return
    
    # Build and send email
    timestamp = lead.get("server_timestamp") or datetime.now(timezone.utc).isoformat()
    subject = f"🎉 New Lead: {lead.get('name', 'Unknown')} - {site.get('name', 'VerifiedDemand')}"
    
    html_content = build_lead_email_html(site, lead, timestamp)
    text_content = build_lead_email_text(site, lead, timestamp)
    
    success = await send_email_async(notification_emails, subject, html_content, text_content)
    if success:
        logger.info(f"Lead notification sent for {lead.get('email')} to {notification_emails}")
    else:
        logger.warning(f"Failed to send lead notification for {lead.get('email')}")


@api_router.post("/track")
async def track_event(event: TrackEvent, request: Request):
    """Receive tracking events from embed.js"""
    doc = event.model_dump()
    doc['server_timestamp'] = datetime.now(timezone.utc).isoformat()
    
    # Extract source domain
    source_domain = extract_request_domain(request, event.url)
    doc['source_domain'] = source_domain
    
    # Check domain status
    site = await resolve_site_by_public_key(event.publicKey)
    if site:
        allowlist = get_site_allowlist(site)
        doc['domain_status'] = check_domain_status(source_domain, allowlist)
    else:
        doc['domain_status'] = 'unknown'
    
    await db.tracking_events.insert_one(doc)
    logger.info(f"Tracked event: {event.event} for key: {event.publicKey}, domain: {source_domain}, status: {doc['domain_status']}")
    return Response(
        content='{"status":"ok"}',
        media_type="application/json",
        headers=CORS_HEADERS
    )


@api_router.options("/track")
async def track_options():
    """Handle CORS preflight for /api/track"""
    return Response(status_code=200, headers=CORS_HEADERS)


# Public endpoints for embed.js
@api_router.post("/public/track")
async def public_track_event(event: TrackEvent, request: Request):
    """Public tracking endpoint for embed.js"""
    doc = event.model_dump()
    doc['server_timestamp'] = datetime.now(timezone.utc).isoformat()
    
    # Extract source domain
    source_domain = extract_request_domain(request, event.url)
    doc['source_domain'] = source_domain
    
    # Check domain status
    site = await resolve_site_by_public_key(event.publicKey)
    if site:
        allowlist = get_site_allowlist(site)
        doc['domain_status'] = check_domain_status(source_domain, allowlist)
    else:
        doc['domain_status'] = 'unknown'
    
    await db.tracking_events.insert_one(doc)
    logger.info(f"Public tracked event: {event.event} for key: {event.publicKey}, domain: {source_domain}, status: {doc['domain_status']}")
    return Response(
        content='{"status":"ok"}',
        media_type="application/json",
        headers=CORS_HEADERS
    )


@api_router.options("/public/track")
async def public_track_options():
    """Handle CORS preflight for /api/public/track"""
    return Response(status_code=200, headers=CORS_HEADERS)


@api_router.post("/public/vehicle-lead")
async def submit_vehicle_lead(lead: VehicleLead, request: Request, background_tasks: BackgroundTasks):
    """Receive lead submissions from embed.js modal with anti-spam protection"""
    
    # Get client info for rate limiting and logging
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Check rate limits
    ip_key = f"ip:{client_ip}"
    pk_key = f"pk:{lead.publicKey}"
    
    if not check_rate_limit(ip_key, RATE_LIMIT_PER_IP):
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        return Response(
            content='{"status":"error","message":"Too many requests. Please try again later."}',
            status_code=429,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    if not check_rate_limit(pk_key, RATE_LIMIT_PER_KEY):
        logger.warning(f"Rate limit exceeded for public key: {lead.publicKey}")
        return Response(
            content='{"status":"error","message":"Too many requests. Please try again later."}',
            status_code=429,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Check honeypot
    is_spam = check_honeypot(lead)
    
    # Validate and normalize inputs
    normalized_email, email_valid = validate_email(lead.email)
    normalized_phone, phone_valid = validate_phone(lead.phone)
    is_invalid_contact = not email_valid or not phone_valid
    
    # Extract source domain and check domain status
    source_domain = extract_request_domain(request, lead.url)
    site = await resolve_site_by_public_key(lead.publicKey)
    
    if site:
        allowlist = get_site_allowlist(site)
        domain_status = check_domain_status(source_domain, allowlist)
    else:
        domain_status = 'unknown'
    
    # Build lead document
    doc = lead.model_dump()
    doc['id'] = str(uuid.uuid4())
    doc['server_timestamp'] = datetime.now(timezone.utc).isoformat()
    doc['status'] = 'new'
    
    # Add quality flags
    doc['is_suspected_spam'] = is_spam
    doc['is_invalid_contact'] = is_invalid_contact
    doc['email_valid'] = email_valid
    doc['phone_valid'] = phone_valid
    doc['source_ip'] = client_ip
    doc['source_user_agent'] = user_agent
    doc['source_domain'] = source_domain
    doc['domain_status'] = domain_status
    
    # Store normalized values
    doc['email'] = normalized_email
    doc['phone'] = normalized_phone
    
    # Remove honeypot fields from storage (don't need to keep them)
    doc.pop('company', None)
    doc.pop('website', None)
    
    # Save the lead
    await db.vehicle_leads.insert_one(doc)
    
    if is_spam:
        logger.warning(f"Suspected spam lead from {client_ip}: {normalized_email}")
    elif is_invalid_contact:
        logger.info(f"Lead with invalid contact from {client_ip}: email_valid={email_valid}, phone_valid={phone_valid}")
    elif domain_status == 'mismatch':
        logger.warning(f"Lead from mismatched domain {source_domain} for key: {lead.publicKey}")
    else:
        logger.info(f"Lead submitted: {normalized_email} for key: {lead.publicKey}, domain: {source_domain}")
    
    # Only send notification if not spam, contact is valid, AND domain is not mismatched
    should_notify = not is_spam and not is_invalid_contact and domain_status != 'mismatch'
    if should_notify:
        background_tasks.add_task(send_lead_notification, doc)
    
    # Always return 200 to avoid giving bots feedback
    return Response(
        content='{"status":"ok","message":"Lead received"}',
        media_type="application/json",
        headers=CORS_HEADERS
    )


@api_router.options("/public/vehicle-lead")
async def vehicle_lead_options():
    """Handle CORS preflight for /api/public/vehicle-lead"""
    return Response(status_code=200, headers=CORS_HEADERS)


# ============================================
# OTP Verification API Endpoints
# ============================================

# OTP Models
class OTPRequest(BaseModel):
    public_key: str = Field(..., alias="publicKey")
    phone: str
    name: str
    email: Optional[str] = None
    vehicle: Optional[Any] = None
    source_url: Optional[str] = None
    
    class Config:
        populate_by_name = True


class OTPVerify(BaseModel):
    public_key: str = Field(..., alias="publicKey")
    phone: str
    code: str
    
    class Config:
        populate_by_name = True


# Auth Models
class UserRegister(BaseModel):
    email: str
    password: str
    setup_key: Optional[str] = None  # Required for first admin registration
    role: Optional[str] = "user"


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    created_at: str


class AdminUserCreate(BaseModel):
    """Admin creates a new user"""
    email: str
    role: Optional[str] = "user"
    send_temp_password: Optional[bool] = True  # If true, generates and returns temp password


class AdminUserUpdate(BaseModel):
    """Admin updates a user"""
    is_active: Optional[bool] = None
    role: Optional[str] = None


def generate_otp_code() -> str:
    """Generate a 6-digit OTP code"""
    return str(random.randint(100000, 999999))


def hash_otp_code(code: str) -> str:
    """Hash OTP code for secure storage"""
    return hashlib.sha256(code.encode()).hexdigest()


def normalize_phone_for_otp(phone: str) -> str:
    """Normalize phone number for OTP (digits only)"""
    return re.sub(r'\D', '', phone)


# Unlock code generation - exclude confusing characters (0, O, I, l, 1)
UNLOCK_CODE_CHARS = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'

def generate_unlock_code() -> str:
    """
    Generate a unique, human-readable unlock/confirmation code.
    Format: VD-XXXXXX (6 alphanumeric chars, excludes confusing chars)
    """
    code_part = ''.join(random.choices(UNLOCK_CODE_CHARS, k=6))
    return f"VD-{code_part}"


async def get_unique_unlock_code(max_attempts: int = 10) -> str:
    """
    Generate a unique unlock code, checking against existing codes in DB.
    Returns a unique code or raises an exception after max attempts.
    """
    for _ in range(max_attempts):
        code = generate_unlock_code()
        # Check if code already exists
        existing = await db.vehicle_leads.find_one({"unlock_code": code})
        if not existing:
            return code
    # Fallback: add random suffix for guaranteed uniqueness
    code = generate_unlock_code()
    suffix = ''.join(random.choices(UNLOCK_CODE_CHARS, k=2))
    return f"{code}{suffix}"


async def send_sms(to_phone: str, message: str, otp_code: str = None) -> tuple[bool, str, str]:
    """
    Send SMS via Twilio or mock in development mode.
    Returns (success, dev_code_or_none, error_message_or_none)
    
    Behavior:
    - If Twilio configured → send real SMS, never return dev_code
    - If Twilio NOT configured:
      - ENV=development → mock SMS (log code), return dev_code
      - ENV=production → return error, do NOT send
    """
    # Check if Twilio is configured
    if is_sms_configured():
        # Real Twilio SMS - NEVER expose dev_code
        try:
            from twilio.rest import Client
            client = Client(SMS_CONFIG["twilio_account_sid"], SMS_CONFIG["twilio_auth_token"])
            
            # Format phone number (ensure it starts with +1 for US)
            formatted_phone = to_phone
            if not formatted_phone.startswith('+'):
                if len(formatted_phone) == 10:
                    formatted_phone = '+1' + formatted_phone
                elif len(formatted_phone) == 11 and formatted_phone.startswith('1'):
                    formatted_phone = '+' + formatted_phone
                else:
                    formatted_phone = '+' + formatted_phone
            
            msg = client.messages.create(
                body=message,
                from_=SMS_CONFIG["twilio_from_number"],
                to=formatted_phone
            )
            logger.info(f"✅ SMS sent successfully to {formatted_phone}, Twilio SID: {msg.sid}")
            return True, None, None  # Success, no dev_code in production
            
        except ImportError:
            logger.error("❌ Twilio library not installed. Run: pip install twilio")
            return False, None, "SMS service configuration error"
        except Exception as e:
            # Log Twilio error details (without secrets)
            error_msg = str(e)
            if hasattr(e, 'code'):
                logger.error(f"❌ Twilio API error - Code: {e.code}, Message: {error_msg}")
            else:
                logger.error(f"❌ Twilio send failed: {error_msg}")
            return False, None, "Failed to send SMS. Please try again."
    
    # Twilio NOT configured
    if is_development_mode():
        # Mock SMS mode - only in development
        logger.info(f"📱 [MOCK SMS - DEV MODE] To: {to_phone}")
        logger.info(f"📱 [MOCK SMS - DEV MODE] Message: {message}")
        if otp_code:
            logger.info(f"📱 [MOCK SMS - DEV MODE] OTP Code: {otp_code}")
        return True, otp_code, None  # Return dev_code ONLY in dev mode
    else:
        # Production without Twilio - fail gracefully
        logger.error("❌ SMS not configured in production mode - cannot send OTP")
        return False, None, "SMS temporarily unavailable. Please try again later."


@api_router.post("/public/otp/request")
async def request_otp(otp_req: OTPRequest, request: Request):
    """Request OTP code for phone verification"""
    
    # Get client info
    client_ip = get_client_ip(request)
    source_domain = extract_request_domain(request, otp_req.source_url)
    
    # Normalize phone
    normalized_phone = normalize_phone_for_otp(otp_req.phone)
    
    # Validate phone (at least 10 digits)
    if len(normalized_phone) < 10:
        return Response(
            content='{"ok":false,"error":"Invalid phone number. Please enter a valid phone number."}',
            status_code=400,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Check rate limits
    ip_key = f"otp_ip:{client_ip}"
    pk_key = f"otp_pk:{otp_req.public_key}"
    phone_key = f"otp_phone:{normalized_phone}"
    
    if not check_rate_limit(ip_key, RATE_LIMIT_PER_IP):
        logger.warning(f"OTP rate limit exceeded for IP: {client_ip}")
        return Response(
            content='{"ok":false,"error":"Too many requests. Please try again later."}',
            status_code=429,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    if not check_rate_limit(pk_key, RATE_LIMIT_PER_KEY):
        logger.warning(f"OTP rate limit exceeded for public key: {otp_req.public_key}")
        return Response(
            content='{"ok":false,"error":"Too many requests. Please try again later."}',
            status_code=429,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    if not check_rate_limit(phone_key, RATE_LIMIT_PER_PHONE):
        logger.warning(f"OTP rate limit exceeded for phone: {normalized_phone}")
        return Response(
            content='{"ok":false,"error":"Too many verification attempts for this phone. Please try again later."}',
            status_code=429,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Resolve site
    site = await resolve_site_by_public_key(otp_req.public_key)
    if not site:
        return Response(
            content='{"ok":false,"error":"Invalid configuration. Please contact support."}',
            status_code=400,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Check domain status - block if mismatch
    allowlist = get_site_allowlist(site)
    domain_status = check_domain_status(source_domain, allowlist)
    
    if domain_status == 'mismatch':
        logger.warning(f"OTP blocked due to domain mismatch: {source_domain} for key {otp_req.public_key}")
        return Response(
            content='{"ok":false,"error":"This form is not authorized for this website."}',
            status_code=403,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Check resend cooldown - must wait 30 seconds between OTP requests for same phone+key
    now = datetime.now(timezone.utc)
    recent_otp = await db.otp_verifications.find_one(
        {
            "phone": normalized_phone,
            "public_key": otp_req.public_key,
            "status": {"$in": ["pending", "sent"]}
        },
        sort=[("created_at", -1)]
    )
    
    if recent_otp:
        last_sent_str = recent_otp.get("last_sent_at") or recent_otp.get("created_at")
        if last_sent_str:
            try:
                last_sent = datetime.fromisoformat(last_sent_str.replace('Z', '+00:00'))
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                seconds_since = (now - last_sent).total_seconds()
                
                if seconds_since < OTP_RESEND_COOLDOWN:
                    remaining = int(OTP_RESEND_COOLDOWN - seconds_since)
                    logger.info(f"OTP resend cooldown for phone {normalized_phone}: {remaining}s remaining")
                    return Response(
                        content=json.dumps({
                            "ok": False,
                            "error": f"Please wait {remaining} seconds before requesting a new code.",
                            "cooldown_remaining": remaining
                        }),
                        status_code=429,
                        media_type="application/json",
                        headers=CORS_HEADERS
                    )
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse last_sent_at: {e}")
    
    # Check if SMS is configured (or development mode for mock)
    # In production without Twilio, fail early - do NOT create OTP record
    if not is_sms_configured() and not is_development_mode():
        logger.error("SMS not configured in production - blocking OTP request")
        return Response(
            content='{"ok":false,"error":"SMS temporarily unavailable. Please try again later."}',
            status_code=503,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Generate OTP
    otp_code = generate_otp_code()
    code_hash = hash_otp_code(otp_code)
    
    expires_at = now + timedelta(seconds=OTP_EXPIRY_SECONDS)
    
    # Store OTP verification record
    otp_doc = {
        "id": str(uuid.uuid4()),
        "public_key": otp_req.public_key,
        "site_id": site.get("site_id"),
        "phone": normalized_phone,
        "code_hash": code_hash,
        "created_at": now.isoformat(),
        "last_sent_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "attempts": 0,
        "max_attempts": OTP_MAX_ATTEMPTS,
        "status": "pending",
        "source_ip": client_ip,
        "source_domain": source_domain,
        "domain_status": domain_status,
        "lead_draft": {
            "name": otp_req.name,
            "email": otp_req.email,
            "phone": otp_req.phone,
            "vehicle": otp_req.vehicle,
            "source_url": otp_req.source_url
        }
    }
    
    await db.otp_verifications.insert_one(otp_doc)
    
    # Send SMS (or mock in development)
    # Improved SMS content
    sms_message = f"Your VerifiedDemand verification code is: {otp_code}. Expires in 10 minutes."
    sms_sent, dev_code, sms_error = await send_sms(normalized_phone, sms_message, otp_code)
    
    if not sms_sent:
        # Update status to failed - don't leave broken OTP state
        await db.otp_verifications.update_one(
            {"id": otp_doc["id"]},
            {"$set": {"status": "send_failed", "error": sms_error or "SMS send failed"}}
        )
        error_msg = sms_error or "Failed to send verification code. Please try again."
        return Response(
            content=json.dumps({"ok": False, "error": error_msg}),
            status_code=500,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Update status to sent
    await db.otp_verifications.update_one(
        {"id": otp_doc["id"]},
        {"$set": {"status": "sent"}}
    )
    
    logger.info(f"OTP requested for phone {normalized_phone}, key {otp_req.public_key}")
    
    # Build response - include dev_code ONLY in development mode with mock SMS
    response_data = {
        "ok": True,
        "expires_in": OTP_EXPIRY_SECONDS,
        "cooldown": OTP_RESEND_COOLDOWN,
        "message": "Verification code sent to your phone."
    }
    
    # SECURITY: Only include dev_code when ALL conditions met:
    # 1. dev_code was returned (only happens with mock SMS)
    # 2. ENV is explicitly "development"
    # 3. Twilio is NOT configured (double check)
    if dev_code and is_development_mode() and not is_sms_configured():
        response_data["dev_code"] = dev_code
        response_data["message"] = f"[DEV MODE] Code: {dev_code} - Also logged to server console."
    
    return Response(
        content=json.dumps(response_data),
        media_type="application/json",
        headers=CORS_HEADERS
    )


@api_router.options("/public/otp/request")
async def otp_request_options():
    """Handle CORS preflight for /api/public/otp/request"""
    return Response(status_code=200, headers=CORS_HEADERS)


@api_router.post("/public/otp/verify")
async def verify_otp(otp_verify: OTPVerify, request: Request, background_tasks: BackgroundTasks):
    """Verify OTP code and create lead"""
    
    # Normalize phone
    normalized_phone = normalize_phone_for_otp(otp_verify.phone)
    
    # Find latest pending/sent OTP for this phone+key (both statuses are valid for verification)
    now = datetime.now(timezone.utc)
    otp_record = await db.otp_verifications.find_one({
        "public_key": otp_verify.public_key,
        "phone": normalized_phone,
        "status": {"$in": ["pending", "sent"]},
        "expires_at": {"$gt": now.isoformat()}
    }, sort=[("created_at", -1)])
    
    if not otp_record:
        return Response(
            content='{"ok":false,"error":"No pending verification found. Please request a new code."}',
            status_code=400,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Check if locked
    if otp_record.get("attempts", 0) >= otp_record.get("max_attempts", OTP_MAX_ATTEMPTS):
        await db.otp_verifications.update_one(
            {"id": otp_record["id"]},
            {"$set": {"status": "locked"}}
        )
        return Response(
            content='{"ok":false,"error":"Too many incorrect attempts. Please request a new code."}',
            status_code=400,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Increment attempts
    await db.otp_verifications.update_one(
        {"id": otp_record["id"]},
        {"$inc": {"attempts": 1}}
    )
    
    # Verify code
    input_hash = hash_otp_code(otp_verify.code.strip())
    if input_hash != otp_record["code_hash"]:
        attempts_left = otp_record.get("max_attempts", OTP_MAX_ATTEMPTS) - otp_record.get("attempts", 0) - 1
        if attempts_left <= 0:
            await db.otp_verifications.update_one(
                {"id": otp_record["id"]},
                {"$set": {"status": "locked"}}
            )
            return Response(
                content='{"ok":false,"error":"Too many incorrect attempts. Please request a new code."}',
                status_code=400,
                media_type="application/json",
                headers=CORS_HEADERS
            )
        return Response(
            content=f'{{"ok":false,"error":"Invalid code. {attempts_left} attempts remaining."}}',
            status_code=400,
            media_type="application/json",
            headers=CORS_HEADERS
        )
    
    # Code is correct - mark as verified
    await db.otp_verifications.update_one(
        {"id": otp_record["id"]},
        {"$set": {"status": "verified", "verified_at": now.isoformat()}}
    )
    
    # Generate unique unlock/confirmation code
    unlock_code = await get_unique_unlock_code()
    
    # Create the lead from draft
    lead_draft = otp_record.get("lead_draft", {})
    
    # Validate email if provided
    email = lead_draft.get("email", "")
    normalized_email, email_valid = validate_email(email) if email else ("", True)
    
    lead_doc = {
        "id": str(uuid.uuid4()),
        "publicKey": otp_verify.public_key,
        "name": lead_draft.get("name"),
        "email": normalized_email,
        "phone": lead_draft.get("phone"),
        "vehicle": lead_draft.get("vehicle"),
        "url": lead_draft.get("source_url"),
        "server_timestamp": now.isoformat(),
        "status": "new",
        "is_verified": True,
        "verified_at": now.isoformat(),
        "verification_method": "sms_otp",
        "otp_verification_id": otp_record["id"],
        "unlock_code": unlock_code,
        "unlock_code_created_at": now.isoformat(),
        "is_suspected_spam": False,
        "is_invalid_contact": not email_valid if email else False,
        "email_valid": email_valid if email else None,
        "phone_valid": True,  # Verified via SMS
        "source_ip": otp_record.get("source_ip"),
        "source_user_agent": request.headers.get("user-agent", "unknown"),
        "source_domain": otp_record.get("source_domain"),
        "domain_status": otp_record.get("domain_status", "unknown")
    }
    
    await db.vehicle_leads.insert_one(lead_doc)
    logger.info(f"Verified lead created: {normalized_email or lead_doc['phone']} for key: {otp_verify.public_key}, unlock_code: {unlock_code}")
    
    # Send dealer notification (only if domain is verified or unknown, not mismatch)
    domain_status = otp_record.get("domain_status", "unknown")
    if domain_status != 'mismatch':
        background_tasks.add_task(send_lead_notification, lead_doc)
    
    return Response(
        content=json.dumps({
            "ok": True,
            "verified": True,
            "lead_id": lead_doc["id"],
            "unlock_code": unlock_code,
            "message": "Phone verified successfully!"
        }),
        media_type="application/json",
        headers=CORS_HEADERS
    )


@api_router.options("/public/otp/verify")
async def otp_verify_options():
    """Handle CORS preflight for /api/public/otp/verify"""
    return Response(status_code=200, headers=CORS_HEADERS)


# ============================================
# Dashboard API Endpoints (Read-Only)
# ============================================

def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable format"""
    if doc is None:
        return None
    result = {}
    for key, value in doc.items():
        if key == '_id':
            result['_id'] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO date string to datetime"""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def build_public_key_filter(key: str) -> dict:
    """Build filter that matches either publicKey or public_key field"""
    return {"$or": [{"publicKey": key}, {"public_key": key}]}


def build_timestamp_filter(start_date: datetime, end_date: datetime) -> dict:
    """Build filter that matches any timestamp field within range"""
    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()
    return {
        "$or": [
            {"timestamp": {"$gte": start_iso, "$lte": end_iso}},
            {"server_timestamp": {"$gte": start_iso, "$lte": end_iso}},
            {"created_at": {"$gte": start_iso, "$lte": end_iso}}
        ]
    }


def build_event_type_filter(event_types: list) -> dict:
    """Build filter that matches event OR event_type field"""
    return {
        "$or": [
            {"event": {"$in": event_types}},
            {"event_type": {"$in": event_types}}
        ]
    }


def normalize_lead(doc: dict) -> dict:
    """Normalize lead document fields for consistent response"""
    item = serialize_doc(doc)
    # Normalize public_key
    item['public_key'] = item.get('publicKey') or item.get('public_key')
    # Normalize timestamp
    item['timestamp'] = item.get('server_timestamp') or item.get('timestamp') or item.get('created_at')
    item['created_at'] = item['timestamp']
    # Normalize source URL
    item['source_url'] = item.get('url') or item.get('source_url') or item.get('page_url')
    return item


def normalize_event(doc: dict) -> dict:
    """Normalize event document fields for consistent response"""
    item = serialize_doc(doc)
    # Normalize public_key
    item['public_key'] = item.get('publicKey') or item.get('public_key')
    # Normalize event_type
    item['event_type'] = item.get('event') or item.get('event_type')
    # Normalize timestamp
    item['timestamp'] = item.get('server_timestamp') or item.get('timestamp') or item.get('created_at')
    # Normalize data
    item['custom_data'] = item.get('data') or item.get('custom_data')
    return item


def redact_pii(value: str, show_chars: int = 3) -> str:
    """Partially redact PII data for debug endpoint"""
    if not value or len(value) <= show_chars * 2:
        return "***"
    return value[:show_chars] + "***" + value[-show_chars:]


# ============================================
# Authentication Endpoints
# ============================================

@api_router.post("/auth/register")
async def register_user(user_data: UserRegister):
    """Register a new user. First admin requires ADMIN_SETUP_KEY."""
    
    # Validate email
    normalized_email, is_valid = validate_email(user_data.email)
    if not is_valid:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Invalid email address"}
        )
    
    # Check if email already exists
    existing = await db.users.find_one({"email": normalized_email})
    if existing:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Email already registered"}
        )
    
    # Validate password strength
    is_valid_pwd, pwd_error = validate_password_strength(user_data.password)
    if not is_valid_pwd:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": pwd_error}
        )
    
    # Check if this is the first user (admin bootstrap)
    user_count = await db.users.count_documents({})
    role = "user"
    
    if user_count == 0:
        # First user must use admin setup key to become admin
        if not ADMIN_SETUP_KEY:
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": "ADMIN_SETUP_KEY not configured"}
            )
        
        if user_data.setup_key != ADMIN_SETUP_KEY:
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "Invalid setup key for first admin registration"}
            )
        role = "admin"
    else:
        # Subsequent registrations require admin setup key too (controlled registration)
        if user_data.setup_key != ADMIN_SETUP_KEY:
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "Registration requires a valid invite code"}
            )
        # Allow specifying role if valid key provided
        if user_data.role in ["admin", "user"]:
            role = user_data.role
    
    # Create user
    now = datetime.now(timezone.utc)
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": normalized_email,
        "password_hash": hash_password(user_data.password),
        "role": role,
        "created_at": now.isoformat(),
        "last_login_at": None,
        "is_active": True
    }
    
    await db.users.insert_one(user_doc)
    logger.info(f"User registered: {normalized_email} (role: {role})")
    
    return JSONResponse(
        status_code=201,
        content={
            "ok": True,
            "user": {
                "id": user_doc["id"],
                "email": user_doc["email"],
                "role": user_doc["role"]
            },
            "message": f"User registered successfully as {role}"
        }
    )


@api_router.post("/auth/login")
async def login_user(user_data: UserLogin, request: Request):
    """Login user and set httpOnly cookie with JWT"""
    
    # Rate limiting on login attempts
    client_ip = get_client_ip(request)
    rate_key = f"auth_login:{client_ip}"
    if not check_rate_limit(rate_key, AUTH_RATE_LIMIT_LOGIN):
        logger.warning(f"Login rate limit exceeded for IP: {client_ip}")
        return JSONResponse(
            status_code=429,
            content={"ok": False, "error": "Too many login attempts. Please try again later."}
        )
    
    # Normalize email
    normalized_email = user_data.email.strip().lower()
    
    # Find user
    user = await db.users.find_one({"email": normalized_email})
    
    if not user:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Invalid email or password"}
        )
    
    # Check if user is active
    if not user.get("is_active", True):
        logger.warning(f"Login attempt for disabled account: {normalized_email}")
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Account is disabled. Please contact an administrator."}
        )
    
    # Verify password
    if not verify_password(user_data.password, user.get("password_hash", "")):
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Invalid email or password"}
        )
    
    # Update last login
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"last_login_at": now.isoformat()}}
    )
    
    # Create JWT token
    token = create_jwt_token(user["id"], user["email"], user.get("role", "user"))
    
    logger.info(f"User logged in: {normalized_email}")
    
    # Create response with httpOnly cookie
    response = JSONResponse(
        content={
            "ok": True,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "role": user.get("role", "user")
            },
            "message": "Login successful"
        }
    )
    
    # Set httpOnly cookie - secure=True in production
    is_production = not is_development_mode()
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_production,  # True in production (HTTPS), False in development
        samesite="lax",
        max_age=JWT_EXPIRY_HOURS * 3600,
        path="/"
    )
    
    return response


@api_router.post("/auth/logout")
async def logout_user():
    """Logout user by clearing the auth cookie"""
    response = JSONResponse(
        content={"ok": True, "message": "Logged out successfully"}
    )
    
    # Clear the cookie
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/"
    )
    
    return response


@api_router.get("/auth/me")
async def get_current_user_info(request: Request):
    """Get current user info if authenticated"""
    user = await get_current_user(request)
    
    if not user:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Not authenticated", "user": None}
        )
    
    return JSONResponse(
        content={
            "ok": True,
            "user": user
        }
    )


# ============================================
# Admin User Management Endpoints
# ============================================

@api_router.get("/dashboard/users")
async def list_users(request: Request, _user: dict = Depends(require_admin)):
    """List all users (admin only)"""
    
    cursor = db.users.find({}).sort([("created_at", -1)])
    users = await cursor.to_list(length=1000)
    
    # Sanitize output - don't expose password hashes
    sanitized_users = []
    for u in users:
        sanitized_users.append({
            "id": u.get("id"),
            "email": u.get("email"),
            "role": u.get("role", "user"),
            "is_active": u.get("is_active", True),
            "created_at": u.get("created_at"),
            "last_login_at": u.get("last_login_at")
        })
    
    return {"users": sanitized_users, "total": len(sanitized_users)}


@api_router.post("/dashboard/users")
async def admin_create_user(user_data: AdminUserCreate, request: Request, _user: dict = Depends(require_admin)):
    """Create a new user (admin only) - generates a temporary password"""
    
    # Validate email
    normalized_email, is_valid = validate_email(user_data.email)
    if not is_valid:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Invalid email address"}
        )
    
    # Check if email already exists
    existing = await db.users.find_one({"email": normalized_email})
    if existing:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Email already registered"}
        )
    
    # Validate role
    role = user_data.role if user_data.role in ["admin", "user"] else "user"
    
    # Generate temporary password
    temp_password = generate_temp_password()
    
    # Create user
    now = datetime.now(timezone.utc)
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": normalized_email,
        "password_hash": hash_password(temp_password),
        "role": role,
        "created_at": now.isoformat(),
        "last_login_at": None,
        "is_active": True,
        "requires_password_change": True  # Flag to prompt password change on first login
    }
    
    await db.users.insert_one(user_doc)
    logger.info(f"Admin {_user['email']} created user: {normalized_email} (role: {role})")
    
    response_data = {
        "ok": True,
        "user": {
            "id": user_doc["id"],
            "email": user_doc["email"],
            "role": user_doc["role"],
            "is_active": user_doc["is_active"]
        },
        "message": "User created successfully"
    }
    
    # Include temp password in response (admin should share this securely)
    if user_data.send_temp_password:
        response_data["temp_password"] = temp_password
        response_data["message"] = f"User created. Temporary password: {temp_password}"
    
    return JSONResponse(status_code=201, content=response_data)


@api_router.patch("/dashboard/users/{user_id}")
async def admin_update_user(user_id: str, update: AdminUserUpdate, request: Request, _user: dict = Depends(require_admin)):
    """Update a user's status or role (admin only)"""
    
    # Find user
    user = await db.users.find_one({"id": user_id})
    if not user:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "User not found"}
        )
    
    # Prevent admin from disabling themselves
    if user_id == _user["id"] and update.is_active is False:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Cannot disable your own account"}
        )
    
    # Prevent admin from demoting themselves
    if user_id == _user["id"] and update.role == "user":
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Cannot demote your own account"}
        )
    
    # Build update document
    update_doc = {"updated_at": datetime.now(timezone.utc).isoformat()}
    
    if update.is_active is not None:
        update_doc["is_active"] = update.is_active
    
    if update.role is not None and update.role in ["admin", "user"]:
        update_doc["role"] = update.role
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": update_doc}
    )
    
    # Fetch updated user
    updated_user = await db.users.find_one({"id": user_id})
    
    logger.info(f"Admin {_user['email']} updated user {user_id}: {update_doc}")
    
    return {
        "ok": True,
        "user": {
            "id": updated_user["id"],
            "email": updated_user["email"],
            "role": updated_user.get("role", "user"),
            "is_active": updated_user.get("is_active", True)
        },
        "message": "User updated successfully"
    }


@api_router.post("/dashboard/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, request: Request, _user: dict = Depends(require_admin)):
    """Reset a user's password to a temporary password (admin only)"""
    
    # Find user
    user = await db.users.find_one({"id": user_id})
    if not user:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "User not found"}
        )
    
    # Generate new temporary password
    temp_password = generate_temp_password()
    
    # Update user
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "password_hash": hash_password(temp_password),
            "requires_password_change": True,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    logger.info(f"Admin {_user['email']} reset password for user {user_id}")
    
    return {
        "ok": True,
        "temp_password": temp_password,
        "message": f"Password reset. New temporary password: {temp_password}"
    }


# Debug endpoint - for development only
@api_router.get("/dashboard/debug-sample")
async def debug_sample(
    collection: str = Query(..., description="Collection name: tracking_events or vehicle_leads")
):
    """Development endpoint to inspect stored data shape"""
    if collection not in ["tracking_events", "vehicle_leads"]:
        return {"error": "Invalid collection. Use 'tracking_events' or 'vehicle_leads'"}
    
    coll = db[collection]
    
    # Get 3 most recent documents
    cursor = coll.find({}).sort([("server_timestamp", -1), ("timestamp", -1), ("_id", -1)]).limit(3)
    docs = await cursor.to_list(length=3)
    
    # Collect all unique keys across documents
    all_keys = set()
    samples = []
    
    for doc in docs:
        serialized = serialize_doc(doc)
        all_keys.update(serialized.keys())
        
        # Redact PII fields
        if 'email' in serialized and serialized['email']:
            serialized['email'] = redact_pii(str(serialized['email']))
        if 'phone' in serialized and serialized['phone']:
            serialized['phone'] = redact_pii(str(serialized['phone']))
        if 'name' in serialized and serialized['name']:
            serialized['name'] = redact_pii(str(serialized['name']))
            
        samples.append(serialized)
    
    return {
        "collection": collection,
        "sample_count": len(samples),
        "top_level_keys": sorted(list(all_keys)),
        "samples": samples
    }


@api_router.get("/dashboard/summary")
async def get_dashboard_summary(
    request: Request,
    public_key: Optional[str] = Query(None, alias="public_key", description="Public key to filter by"),
    publicKey: Optional[str] = Query(None, description="Public key (alternative param name)"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    _user: dict = Depends(require_auth)
):
    """Get summary statistics for a public key"""
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"error": "public_key parameter is required"}
    
    # Check access for non-admin users
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, key)
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this site's data")
    
    # Parse dates, default to last 7 days
    end_date = parse_date(end) or datetime.now(timezone.utc)
    start_date = parse_date(start) or (end_date - timedelta(days=7))
    
    # Build flexible filters
    key_filter = build_public_key_filter(key)
    time_filter = build_timestamp_filter(start_date, end_date)
    
    # Base filter combining key and time
    base_events_filter = {"$and": [key_filter, time_filter]}
    base_leads_filter = {"$and": [key_filter, time_filter]}
    
    # Count vehicle views (pageview, vehicle_view)
    view_event_types = ["vehicle_view", "pageview"]
    vehicle_views = await db.tracking_events.count_documents({
        "$and": [
            key_filter,
            time_filter,
            build_event_type_filter(view_event_types)
        ]
    })
    
    # Count unlock clicks (various naming conventions)
    click_event_types = [
        "unlock_click", "unlock-click", "unlock_price", "unlock-price",
        "vd_trigger_click", "trigger_click", "click"
    ]
    unlock_clicks = await db.tracking_events.count_documents({
        "$and": [
            key_filter,
            time_filter,
            build_event_type_filter(click_event_types)
        ]
    })
    
    # Count leads
    total_leads = await db.vehicle_leads.count_documents(base_leads_filter)
    
    # Count total events (without date filter being too strict - try simpler query first)
    total_events = await db.tracking_events.count_documents(base_events_filter)
    
    # If no events found with time filter, try without time filter to see if data exists
    if total_events == 0:
        total_events_no_time = await db.tracking_events.count_documents(key_filter)
        if total_events_no_time > 0:
            logger.info(f"Found {total_events_no_time} events for key {key} outside date range")
    
    return {
        "public_key": key,
        "date_range": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        },
        "total_vehicle_views": vehicle_views,
        "total_unlock_clicks": unlock_clicks,
        "total_leads": total_leads,
        "total_events": total_events
    }


@api_router.get("/dashboard/leads")
async def get_dashboard_leads(
    request: Request,
    public_key: Optional[str] = Query(None, alias="public_key", description="Public key to filter by"),
    publicKey: Optional[str] = Query(None, description="Public key (alternative param name)"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(50, ge=1, le=500, description="Number of results"),
    skip: int = Query(0, ge=0, description="Number of results to skip"),
    _user: dict = Depends(require_auth)
):
    """Get leads for a public key with pagination"""
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"error": "public_key parameter is required", "leads": [], "total": 0}
    
    # Check access for non-admin users
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, key)
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this site's data")
    
    # Parse dates - default to last 90 days for leads to capture more data
    end_date = parse_date(end) or datetime.now(timezone.utc)
    start_date = parse_date(start) or (end_date - timedelta(days=90))
    
    # Build flexible filters
    key_filter = build_public_key_filter(key)
    time_filter = build_timestamp_filter(start_date, end_date)
    
    # Combined query
    query = {"$and": [key_filter, time_filter]}
    
    # Get total count
    total_count = await db.vehicle_leads.count_documents(query)
    
    # If no results with time filter, try without time filter
    if total_count == 0:
        total_without_time = await db.vehicle_leads.count_documents(key_filter)
        if total_without_time > 0:
            # Use key filter only if time filter returns nothing
            query = key_filter
            total_count = total_without_time
            logger.info(f"Using key-only filter, found {total_count} leads for key {key}")
    
    # Get leads sorted by newest first (try multiple sort fields)
    cursor = db.vehicle_leads.find(query).sort([
        ("server_timestamp", -1), 
        ("timestamp", -1),
        ("created_at", -1),
        ("_id", -1)
    ]).skip(skip).limit(limit)
    leads = await cursor.to_list(length=limit)
    
    # Normalize leads for consistent response
    serialized_leads = [normalize_lead(lead) for lead in leads]
    
    return {
        "leads": serialized_leads,
        "total": total_count,
        "limit": limit,
        "skip": skip
    }


@api_router.get("/dashboard/events")
async def get_dashboard_events(
    request: Request,
    public_key: Optional[str] = Query(None, alias="public_key", description="Public key to filter by"),
    publicKey: Optional[str] = Query(None, description="Public key (alternative param name)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(50, ge=1, le=500, description="Number of results"),
    skip: int = Query(0, ge=0, description="Number of results to skip"),
    _user: dict = Depends(require_auth)
):
    """Get tracking events for a public key with pagination"""
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"error": "public_key parameter is required", "events": [], "total": 0}
    
    # Check access for non-admin users
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, key)
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this site's data")
    
    # Parse dates - default to last 90 days
    end_date = parse_date(end) or datetime.now(timezone.utc)
    start_date = parse_date(start) or (end_date - timedelta(days=90))
    
    # Build flexible filters
    key_filter = build_public_key_filter(key)
    time_filter = build_timestamp_filter(start_date, end_date)
    
    # Combined query
    query = {"$and": [key_filter, time_filter]}
    
    # Add event type filter if specified (match both field names)
    if event_type:
        query["$and"].append({
            "$or": [{"event": event_type}, {"event_type": event_type}]
        })
    
    # Get total count
    total_count = await db.tracking_events.count_documents(query)
    
    # If no results with time filter, try without time filter
    if total_count == 0:
        simple_query = key_filter.copy()
        if event_type:
            simple_query = {"$and": [key_filter, {"$or": [{"event": event_type}, {"event_type": event_type}]}]}
        total_without_time = await db.tracking_events.count_documents(simple_query)
        if total_without_time > 0:
            query = simple_query
            total_count = total_without_time
            logger.info(f"Using key-only filter, found {total_count} events for key {key}")
    
    # Get events sorted by newest first
    cursor = db.tracking_events.find(query).sort([
        ("server_timestamp", -1), 
        ("timestamp", -1),
        ("created_at", -1),
        ("_id", -1)
    ]).skip(skip).limit(limit)
    events = await cursor.to_list(length=limit)
    
    # Normalize events for consistent response
    serialized_events = [normalize_event(event) for event in events]
    
    return {
        "events": serialized_events,
        "total": total_count,
        "limit": limit,
        "skip": skip
    }


@api_router.get("/dashboard/event-types")
async def get_event_types(
    request: Request,
    public_key: Optional[str] = Query(None, alias="public_key", description="Public key to filter by"),
    publicKey: Optional[str] = Query(None, description="Public key (alternative param name)"),
    _user: dict = Depends(require_auth)
):
    """Get distinct event types for a public key"""
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"event_types": []}
    
    # Check access for non-admin users
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, key)
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this site's data")
    
    key_filter = build_public_key_filter(key)
    
    # Get distinct values from both possible field names
    event_types_1 = await db.tracking_events.distinct("event", key_filter)
    event_types_2 = await db.tracking_events.distinct("event_type", key_filter)
    
    # Combine and dedupe
    all_types = list(set(event_types_1 + event_types_2))
    # Filter out None values
    all_types = [t for t in all_types if t is not None]
    
    return {"event_types": sorted(all_types)}


# ============================================
# Dealer Dashboard v2 - Call Queue Endpoints
# ============================================

# Valid lead statuses for dealer workflow
LEAD_STATUSES = ["new", "attempted", "contacted", "appt_set", "sold", "lost"]

class LeadUpdate(BaseModel):
    """Schema for updating lead workflow fields"""
    status: Optional[str] = Field(None, description="Lead status")
    note: Optional[str] = Field(None, description="Note to add")
    next_action_at: Optional[str] = Field(None, description="Next follow-up datetime ISO")
    last_contacted_at: Optional[str] = Field(None, description="Last contacted datetime ISO")


def normalize_lead_for_queue(doc: dict) -> dict:
    """Normalize lead document for dealer queue view"""
    item = serialize_doc(doc)
    # Core identifiers
    item['id'] = item.get('id') or str(item.get('_id', ''))
    item['public_key'] = item.get('publicKey') or item.get('public_key')
    
    # Timestamps
    item['timestamp'] = item.get('server_timestamp') or item.get('timestamp') or item.get('created_at')
    item['created_at'] = item['timestamp']
    
    # Contact info
    item['name'] = item.get('name') or ''
    item['email'] = item.get('email') or ''
    item['phone'] = item.get('phone') or ''
    
    # Verification status
    item['is_verified'] = item.get('is_verified', False)
    item['verified_at'] = item.get('verified_at')
    item['verification_method'] = item.get('verification_method')
    
    # Unlock/confirmation code
    item['unlock_code'] = item.get('unlock_code') or ''
    
    # Vehicle info (simplified)
    vehicle = item.get('vehicle') or {}
    if isinstance(vehicle, dict):
        parts = [str(vehicle.get(k, '')) for k in ['year', 'make', 'model', 'trim'] if vehicle.get(k)]
        item['vehicle_summary'] = ' '.join(parts) if parts else ''
        item['vehicle'] = vehicle
    else:
        item['vehicle_summary'] = ''
        item['vehicle'] = {}
    
    # Domain/source info
    item['source_url'] = item.get('url') or item.get('source_url') or item.get('page_url') or ''
    item['source_domain'] = item.get('source_domain') or ''
    item['domain_status'] = item.get('domain_status', 'unknown')
    
    # Workflow fields (with defaults)
    item['status'] = item.get('status', 'new')
    item['status_updated_at'] = item.get('status_updated_at')
    item['notes'] = item.get('notes', [])
    item['next_action_at'] = item.get('next_action_at')
    item['last_contacted_at'] = item.get('last_contacted_at')
    item['assigned_to_user_id'] = item.get('assigned_to_user_id')
    item['updated_at'] = item.get('updated_at') or item['timestamp']
    
    # Flags
    item['is_suspected_spam'] = item.get('is_suspected_spam', False)
    item['is_invalid_contact'] = item.get('is_invalid_contact', False)
    
    return item


@api_router.get("/dashboard/leads/queue")
async def get_leads_queue(
    request: Request,
    public_key: Optional[str] = Query(None, alias="public_key", description="Site public key"),
    publicKey: Optional[str] = Query(None, description="Site public key (alt)"),
    verified_only: bool = Query(True, description="Only show verified leads"),
    status: str = Query("new", description="Filter by status: new|attempted|contacted|appt_set|sold|lost|all"),
    has_code_only: bool = Query(False, description="Only show leads with unlock code"),
    hide_mismatch: bool = Query(True, description="Hide domain mismatch leads"),
    q: Optional[str] = Query(None, description="Search name/email/phone/unlock_code"),
    date_from: Optional[str] = Query(None, description="Start date ISO"),
    date_to: Optional[str] = Query(None, description="End date ISO"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    _user: dict = Depends(require_auth)
):
    """
    Get leads queue for dealer dashboard.
    - RBAC enforced: admins see all, users see only assigned sites
    - Optimized for dealer workflow
    """
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"error": "public_key parameter is required", "leads": [], "total": 0, "page": 1, "page_size": page_size}
    
    # Check access for non-admin users
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, key)
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this site's data")
    
    # Build query
    query_conditions = [build_public_key_filter(key)]
    
    # Verified filter
    if verified_only:
        query_conditions.append({"is_verified": True})
    
    # Status filter
    if status and status != "all":
        if status in LEAD_STATUSES:
            query_conditions.append({"$or": [{"status": status}, {"status": {"$exists": False}}] if status == "new" else [{"status": status}]})
    
    # Has unlock code filter
    if has_code_only:
        query_conditions.append({"unlock_code": {"$exists": True, "$nin": ["", None]}})
    
    # Hide domain mismatch
    if hide_mismatch:
        query_conditions.append({"$or": [{"domain_status": {"$ne": "mismatch"}}, {"domain_status": {"$exists": False}}]})
    
    # Date range filter
    if date_from or date_to:
        end_date = parse_date(date_to) or datetime.now(timezone.utc)
        start_date = parse_date(date_from) or (end_date - timedelta(days=30))
        query_conditions.append(build_timestamp_filter(start_date, end_date))
    
    # Search filter (name, email, phone, unlock_code)
    if q:
        search_regex = {"$regex": q, "$options": "i"}
        query_conditions.append({
            "$or": [
                {"name": search_regex},
                {"email": search_regex},
                {"phone": search_regex},
                {"unlock_code": search_regex}
            ]
        })
    
    # Combine all conditions
    query = {"$and": query_conditions} if len(query_conditions) > 1 else query_conditions[0]
    
    # Get total count
    total_count = await db.vehicle_leads.count_documents(query)
    
    # Calculate skip
    skip = (page - 1) * page_size
    
    # Get leads sorted by newest first, with next_action leads prioritized
    cursor = db.vehicle_leads.find(query).sort([
        ("next_action_at", 1),  # Leads with follow-up dates first
        ("server_timestamp", -1),
        ("timestamp", -1),
        ("_id", -1)
    ]).skip(skip).limit(page_size)
    
    leads = await cursor.to_list(length=page_size)
    
    # Normalize leads for queue view
    serialized_leads = [normalize_lead_for_queue(lead) for lead in leads]
    
    return {
        "leads": serialized_leads,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size
    }


@api_router.get("/dashboard/leads/queue/stats")
async def get_queue_stats(
    request: Request,
    public_key: Optional[str] = Query(None, alias="public_key", description="Site public key"),
    publicKey: Optional[str] = Query(None, description="Site public key (alt)"),
    _user: dict = Depends(require_auth)
):
    """
    Get quick stats for dealer dashboard KPIs.
    """
    
    key = public_key or publicKey
    if not key:
        return {"error": "public_key parameter is required"}
    
    # Check access
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, key)
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this site's data")
    
    key_filter = build_public_key_filter(key)
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    
    # Build time filters
    today_filter = build_timestamp_filter(today_start, now)
    week_filter = build_timestamp_filter(week_ago, now)
    
    # Count new verified (today)
    new_verified_today = await db.vehicle_leads.count_documents({
        "$and": [key_filter, today_filter, {"is_verified": True}, {"$or": [{"status": "new"}, {"status": {"$exists": False}}]}]
    })
    
    # Count contacted (today)
    contacted_today = await db.vehicle_leads.count_documents({
        "$and": [key_filter, {"status": "contacted"}, {"status_updated_at": {"$gte": today_start.isoformat()}}]
    })
    
    # Count appointments set (7d)
    appts_7d = await db.vehicle_leads.count_documents({
        "$and": [key_filter, {"status": "appt_set"}, {"status_updated_at": {"$gte": week_ago.isoformat()}}]
    })
    
    # Total verified (7d)
    total_verified_7d = await db.vehicle_leads.count_documents({
        "$and": [key_filter, week_filter, {"is_verified": True}]
    })
    
    # Leads needing follow-up (next_action_at <= now)
    needs_followup = await db.vehicle_leads.count_documents({
        "$and": [key_filter, {"next_action_at": {"$lte": now.isoformat()}}, {"status": {"$nin": ["sold", "lost"]}}]
    })
    
    return {
        "new_verified_today": new_verified_today,
        "contacted_today": contacted_today,
        "appts_set_7d": appts_7d,
        "total_verified_7d": total_verified_7d,
        "needs_followup": needs_followup
    }


@api_router.get("/dashboard/leads/{lead_id}")
async def get_lead_detail(
    lead_id: str,
    request: Request,
    _user: dict = Depends(require_auth)
):
    """
    Get full lead detail including notes history.
    """
    
    # Find lead by id field (UUID string)
    lead = await db.vehicle_leads.find_one({"id": lead_id})
    
    if not lead:
        # Try by MongoDB _id
        try:
            from bson import ObjectId
            lead = await db.vehicle_leads.find_one({"_id": ObjectId(lead_id)})
        except:
            pass
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Check access
    key = lead.get("publicKey") or lead.get("public_key")
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, key)
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this lead")
    
    return normalize_lead_for_queue(lead)


@api_router.patch("/dashboard/leads/{lead_id}")
async def update_lead_workflow(
    lead_id: str,
    update: LeadUpdate,
    request: Request,
    _user: dict = Depends(require_auth)
):
    """
    Update lead workflow fields: status, notes, next_action_at, last_contacted_at.
    - Appends notes with user info and timestamp
    - Enforces RBAC
    """
    
    # Find lead
    lead = await db.vehicle_leads.find_one({"id": lead_id})
    
    if not lead:
        try:
            from bson import ObjectId
            lead = await db.vehicle_leads.find_one({"_id": ObjectId(lead_id)})
        except:
            pass
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Check access
    key = lead.get("publicKey") or lead.get("public_key")
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, key)
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this lead")
    
    # Build update document
    now = datetime.now(timezone.utc)
    update_doc = {"updated_at": now.isoformat()}
    
    # Update status
    if update.status:
        if update.status not in LEAD_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {LEAD_STATUSES}")
        update_doc["status"] = update.status
        update_doc["status_updated_at"] = now.isoformat()
    
    # Add note
    if update.note:
        note_obj = {
            "text": update.note,
            "created_at": now.isoformat(),
            "user_id": _user.get("id"),
            "user_email": _user.get("email")
        }
        # Append to existing notes array (or create new)
        existing_notes = lead.get("notes", [])
        if not isinstance(existing_notes, list):
            existing_notes = []
        existing_notes.append(note_obj)
        update_doc["notes"] = existing_notes
    
    # Update next_action_at
    if update.next_action_at:
        update_doc["next_action_at"] = update.next_action_at
    
    # Update last_contacted_at
    if update.last_contacted_at:
        update_doc["last_contacted_at"] = update.last_contacted_at
    
    # Perform update
    lead_filter = {"id": lead_id} if lead.get("id") else {"_id": lead["_id"]}
    result = await db.vehicle_leads.update_one(lead_filter, {"$set": update_doc})
    
    if result.modified_count == 0:
        logger.warning(f"No document modified for lead {lead_id}")
    
    # Return updated lead
    updated_lead = await db.vehicle_leads.find_one(lead_filter)
    return normalize_lead_for_queue(updated_lead)


# ============================================
# Site Management API Endpoints
# ============================================

import secrets
from urllib.parse import urlparse

# Site models
class SiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    domain: Optional[str] = Field(None, max_length=253)
    notification_emails: Optional[List[str]] = Field(default_factory=list)
    allowed_domains: Optional[List[str]] = Field(default_factory=list)


class SiteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    domain: Optional[str] = Field(None, max_length=253)
    is_active: Optional[bool] = None
    notification_emails: Optional[List[str]] = None
    allowed_domains: Optional[List[str]] = None


def generate_public_key() -> str:
    """Generate a cryptographically secure public key (32 hex chars)"""
    return secrets.token_hex(16)


def validate_domain(domain: str) -> bool:
    """Basic domain format validation"""
    if not domain:
        return True
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
    return bool(re.match(pattern, domain))


def normalize_domain(domain_or_url: str) -> Optional[str]:
    """
    Normalize a domain or URL to a clean domain string.
    - Strips protocol and port
    - Removes www. prefix
    - Lowercases
    Example: https://www.Example.com:443/page → example.com
    """
    if not domain_or_url:
        return None
    
    domain_or_url = domain_or_url.strip().lower()
    
    # If it looks like a URL, parse it
    if '://' in domain_or_url:
        try:
            parsed = urlparse(domain_or_url)
            domain = parsed.netloc or parsed.path
        except Exception:
            domain = domain_or_url
    else:
        domain = domain_or_url
    
    # Remove port if present
    if ':' in domain:
        domain = domain.split(':')[0]
    
    # Remove www. prefix
    if domain.startswith('www.'):
        domain = domain[4:]
    
    return domain if domain else None


def extract_request_domain(request: Request, payload_url: Optional[str] = None) -> Optional[str]:
    """
    Extract the source domain from request headers or payload.
    Priority: Origin > Referer > payload URL
    """
    # Try Origin header first (most reliable for CORS requests)
    origin = request.headers.get("origin")
    if origin:
        return normalize_domain(origin)
    
    # Try Referer header
    referer = request.headers.get("referer")
    if referer:
        return normalize_domain(referer)
    
    # Fallback to URL in payload
    if payload_url:
        return normalize_domain(payload_url)
    
    return None


def get_site_allowlist(site: dict) -> List[str]:
    """
    Get the effective allowlist for a site.
    - If allowed_domains is set, use it
    - Otherwise, if domain is set, use [domain]
    - Otherwise, return empty list (no enforcement)
    """
    allowed = site.get("allowed_domains", [])
    if allowed:
        return [normalize_domain(d) for d in allowed if d]
    
    # Fallback to single domain if set
    domain = site.get("domain")
    if domain:
        return [normalize_domain(domain)]
    
    return []


def check_domain_status(source_domain: Optional[str], allowlist: List[str]) -> str:
    """
    Check if source_domain is in the allowlist.
    Returns: 'verified', 'mismatch', or 'unknown'
    """
    if not allowlist:
        return "unknown"  # No allowlist configured
    
    if not source_domain:
        return "unknown"  # Cannot determine source domain
    
    # Normalize and check
    source_normalized = normalize_domain(source_domain)
    if source_normalized in allowlist:
        return "verified"
    
    return "mismatch"


def serialize_site(doc: dict) -> dict:
    """Serialize site document for API response"""
    if doc is None:
        return None
    result = {}
    for key, value in doc.items():
        if key == '_id':
            result['_id'] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


async def get_user_accessible_site_keys(user: dict) -> Optional[List[str]]:
    """
    Get list of public keys the user can access.
    Returns None if user is admin (can access all), otherwise returns list of allowed keys.
    """
    if user.get("role") == "admin":
        return None  # Admin can access all sites
    
    user_id = user.get("id")
    # Find sites where user is owner OR in allowed_user_ids
    query = {
        "$or": [
            {"owner_user_id": user_id},
            {"allowed_user_ids": user_id}
        ]
    }
    cursor = db.sites.find(query, {"public_key": 1})
    sites = await cursor.to_list(length=1000)
    return [s["public_key"] for s in sites]


async def user_can_access_site(user: dict, public_key: str) -> bool:
    """Check if user can access a specific site by public key"""
    if user.get("role") == "admin":
        return True
    
    user_id = user.get("id")
    site = await db.sites.find_one({
        "public_key": public_key,
        "$or": [
            {"owner_user_id": user_id},
            {"allowed_user_ids": user_id}
        ]
    })
    return site is not None


@api_router.post("/dashboard/sites")
async def create_site(site: SiteCreate, request: Request, _user: dict = Depends(require_admin)):
    """Create a new site with auto-generated public key (Admin only)"""
    
    # Validate domain if provided
    if site.domain and not validate_domain(site.domain):
        return {"error": "Invalid domain format"}
    
    # Generate unique public key
    max_attempts = 10
    public_key = None
    for _ in range(max_attempts):
        candidate = generate_public_key()
        existing = await db.sites.find_one({"public_key": candidate})
        if not existing:
            public_key = candidate
            break
    
    if not public_key:
        return {"error": "Failed to generate unique public key"}
    
    now = datetime.now(timezone.utc)
    
    # Normalize allowed_domains
    allowed_domains = []
    if site.allowed_domains:
        allowed_domains = [normalize_domain(d) for d in site.allowed_domains if d and d.strip()]
    
    doc = {
        "site_id": f"site_{secrets.token_hex(8)}",
        "name": site.name,
        "domain": site.domain,
        "public_key": public_key,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "is_active": True,
        "notification_emails": site.notification_emails or [],
        "allowed_domains": allowed_domains,
        "previous_public_keys": [],
        "owner_user_id": _user["id"],  # Site ownership for RBAC
        "allowed_user_ids": []  # Additional users with access (optional)
    }
    
    await db.sites.insert_one(doc)
    logger.info(f"Created site: {site.name} with key: {public_key}")
    
    return serialize_site(doc)


@api_router.get("/dashboard/sites")
async def list_sites(request: Request, _user: dict = Depends(require_auth)):
    """List sites - Admin sees all, users see only assigned sites"""
    
    # Build query based on user role
    if _user.get("role") == "admin":
        # Admin can see all sites
        query = {}
    else:
        # Non-admin users only see sites they own or are assigned to
        user_id = _user.get("id")
        query = {
            "$or": [
                {"owner_user_id": user_id},
                {"allowed_user_ids": user_id}
            ]
        }
    
    cursor = db.sites.find(query).sort([("created_at", -1), ("_id", -1)])
    sites = await cursor.to_list(length=1000)
    return {"sites": [serialize_site(s) for s in sites]}


@api_router.get("/dashboard/sites/{public_key}")
async def get_site(public_key: str, request: Request, _user: dict = Depends(require_auth)):
    """Get a single site by public key"""
    # Check both current and previous keys
    site = await db.sites.find_one({
        "$or": [
            {"public_key": public_key},
            {"previous_public_keys": public_key}
        ]
    })
    
    if not site:
        return {"error": "Site not found"}
    
    # Check access for non-admin users
    if _user.get("role") != "admin":
        can_access = await user_can_access_site(_user, site.get("public_key"))
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied to this site")
    
    return serialize_site(site)


@api_router.patch("/dashboard/sites/{public_key}")
async def update_site(public_key: str, update: SiteUpdate, request: Request, _user: dict = Depends(require_admin)):
    """Update a site's settings (Admin only)"""
    
    # Validate domain if provided
    if update.domain is not None and update.domain and not validate_domain(update.domain):
        return {"error": "Invalid domain format"}
    
    site = await db.sites.find_one({"public_key": public_key})
    if not site:
        return {"error": "Site not found"}
    
    # Build update document
    update_doc = {"updated_at": datetime.now(timezone.utc).isoformat()}
    
    if update.name is not None:
        update_doc["name"] = update.name
    if update.domain is not None:
        update_doc["domain"] = update.domain
    if update.is_active is not None:
        update_doc["is_active"] = update.is_active
    if update.notification_emails is not None:
        update_doc["notification_emails"] = update.notification_emails
    if update.allowed_domains is not None:
        # Normalize allowed domains
        update_doc["allowed_domains"] = [
            normalize_domain(d) for d in update.allowed_domains if d and d.strip()
        ]
    
    await db.sites.update_one(
        {"public_key": public_key},
        {"$set": update_doc}
    )
    
    # Fetch and return updated site
    updated_site = await db.sites.find_one({"public_key": public_key})
    logger.info(f"Updated site: {public_key}")
    
    return serialize_site(updated_site)


@api_router.post("/dashboard/sites/{public_key}/rotate-key")
async def rotate_site_key(public_key: str, request: Request, _user: dict = Depends(require_admin)):
    """Rotate a site's public key, preserving the old key in history (Admin only)"""
    
    site = await db.sites.find_one({"public_key": public_key})
    if not site:
        return {"error": "Site not found"}
    
    # Generate new unique public key
    max_attempts = 10
    new_public_key = None
    for _ in range(max_attempts):
        candidate = generate_public_key()
        existing = await db.sites.find_one({"public_key": candidate})
        if not existing:
            new_public_key = candidate
            break
    
    if not new_public_key:
        return {"error": "Failed to generate new unique public key"}
    
    # Update site with new key, preserving old key in history
    previous_keys = site.get("previous_public_keys", [])
    previous_keys.append(public_key)
    
    await db.sites.update_one(
        {"public_key": public_key},
        {
            "$set": {
                "public_key": new_public_key,
                "previous_public_keys": previous_keys,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        }
    )
    
    # Fetch and return updated site
    updated_site = await db.sites.find_one({"public_key": new_public_key})
    logger.info(f"Rotated key for site: {site.get('name')} from {public_key} to {new_public_key}")
    
    return {
        "message": "Key rotated successfully",
        "old_key": public_key,
        "new_key": new_public_key,
        "site": serialize_site(updated_site)
    }


@api_router.post("/dashboard/sites/{public_key}/send-test-email")
async def send_test_email(public_key: str, request: Request, _user: dict = Depends(require_admin)):
    """Send a test email to the site's notification emails"""
    
    site = await db.sites.find_one({"public_key": public_key})
    if not site:
        return {"success": False, "error": "Site not found"}
    
    notification_emails = site.get("notification_emails", [])
    if not notification_emails:
        return {"success": False, "error": "No notification emails configured for this site"}
    
    if not is_smtp_configured():
        return {"success": False, "error": "SMTP is not configured. Please set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, and SMTP_FROM environment variables."}
    
    # Build test email content
    site_name = site.get("name", "Unknown Site")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    subject = f"✅ Test Email - {site_name}"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #10b981; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
            .content {{ background: #f9fafb; padding: 20px; border: 1px solid #e5e7eb; }}
            .footer {{ text-align: center; padding: 15px; color: #9ca3af; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">✅ Test Email Successful!</h2>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">{site_name}</p>
            </div>
            <div class="content">
                <p>This is a test email from VerifiedDemand to confirm your notification settings are working correctly.</p>
                
                <p><strong>Site Details:</strong></p>
                <ul>
                    <li><strong>Site Name:</strong> {site_name}</li>
                    <li><strong>Domain:</strong> {site.get('domain', 'Not set')}</li>
                    <li><strong>Public Key:</strong> <code>{public_key}</code></li>
                    <li><strong>Test Sent:</strong> {timestamp}</li>
                </ul>
                
                <p>When a new lead is captured, you will receive an email similar to this one with the lead's contact information.</p>
            </div>
            <div class="footer">
                Powered by VerifiedDemand
            </div>
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
Test Email Successful!
======================

This is a test email from VerifiedDemand to confirm your notification settings are working correctly.

Site Details:
- Site Name: {site_name}
- Domain: {site.get('domain', 'Not set')}
- Public Key: {public_key}
- Test Sent: {timestamp}

When a new lead is captured, you will receive an email similar to this one with the lead's contact information.

---
Powered by VerifiedDemand
"""
    
    try:
        success = await send_email_async(notification_emails, subject, html_content, text_content)
        if success:
            return {
                "success": True,
                "message": f"Test email sent successfully to {', '.join(notification_emails)}"
            }
        else:
            return {"success": False, "error": "Failed to send email. Check server logs for details."}
    except Exception as e:
        logger.error(f"Test email error: {e}")
        return {"success": False, "error": str(e)}


# Helper to resolve site from either key format
async def resolve_site_by_key(key: str) -> Optional[dict]:
    """Resolve a site from public_key or publicKey (compatibility)"""
    site = await db.sites.find_one({
        "$or": [
            {"public_key": key},
            {"previous_public_keys": key}
        ]
    })
    return site


# ============================================
# Embed.js script - served from /api/embed.js
# ============================================
EMBED_JS = '''
(function() {
  "use strict";

  console.log("[VD] embed executed");

  // Get script element and configuration
  var scriptEl = document.currentScript || (function() {
    var scripts = document.getElementsByTagName("script");
    for (var i = scripts.length - 1; i >= 0; i--) {
      if (scripts[i].src && scripts[i].src.indexOf("embed.js") !== -1) {
        return scripts[i];
      }
    }
    return null;
  })();

  if (!scriptEl) {
    console.error("[VerifiedDemand] Could not find script element");
    return;
  }

  var config = {
    publicKey: scriptEl.getAttribute("data-public-key"),
    debug: scriptEl.getAttribute("data-debug") === "true",
    endpoint: scriptEl.src.replace("/api/embed.js", "")
  };

  // Debug logger - outputs when data-debug="true"
  function log() {
    if (config.debug) {
      var args = ["[VerifiedDemand]"].concat(Array.prototype.slice.call(arguments));
      console.log.apply(console, args);
    }
  }

  log("Initialized with config:", JSON.stringify(config));
  log("Public Key:", config.publicKey);
  log("Endpoint:", config.endpoint);

  // Track event function - sends to backend
  function trackEvent(eventType, data) {
    log("Track event:", eventType, data);

    var payload = {
      event: eventType,
      publicKey: config.publicKey,
      timestamp: new Date().toISOString(),
      url: window.location.href,
      referrer: document.referrer,
      data: data
    };

    // Send to backend
    try {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", config.endpoint + "/api/track", true);
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
          if (xhr.status === 200) {
            log("Event sent successfully");
          } else {
            log("Event send failed:", xhr.status);
          }
        }
      };
      xhr.send(JSON.stringify(payload));
    } catch (e) {
      log("Error sending event:", e);
    }
  }

  // Modal state
  var modalOverlay = null;
  var modalContainer = null;
  var currentVehicleData = null;
  var currentLeadData = null;  // Store lead data between steps

  // Create modal DOM elements
  function createModal() {
    if (modalOverlay) return;

    // Overlay
    modalOverlay = document.createElement("div");
    modalOverlay.id = "vd-modal-overlay";
    modalOverlay.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:999999;display:none;align-items:center;justify-content:center;";

    // Container
    modalContainer = document.createElement("div");
    modalContainer.id = "vd-modal-container";
    modalContainer.style.cssText = "background:#fff;border-radius:12px;max-width:500px;width:90%;max-height:90vh;overflow:auto;position:relative;box-shadow:0 25px 50px -12px rgba(0,0,0,0.25);";

    // Close on overlay click
    modalOverlay.addEventListener("click", function(e) {
      if (e.target === modalOverlay) {
        closeModal();
      }
    });

    // Close on Escape key
    document.addEventListener("keydown", function(e) {
      if (e.key === "Escape" && modalOverlay.style.display === "flex") {
        closeModal();
      }
    });

    modalOverlay.appendChild(modalContainer);
    document.body.appendChild(modalOverlay);
  }

  // Show error message in modal
  function showError(message) {
    var errorDiv = document.getElementById("vd-error-msg");
    if (errorDiv) {
      errorDiv.textContent = message;
      errorDiv.style.display = "block";
    }
  }

  // Hide error message
  function hideError() {
    var errorDiv = document.getElementById("vd-error-msg");
    if (errorDiv) {
      errorDiv.style.display = "none";
    }
  }

  // Show Step 1: Contact Info Form
  function showStep1() {
    var title = currentVehicleData.title || currentVehicleData.vehicleTitle || "Unlock Your Price";
    var subtitle = currentVehicleData.subtitle || "Enter your details to get the verified instant price";

    modalContainer.innerHTML = 
      '<div style="padding:24px;">' +
        '<button id="vd-close-btn" style="position:absolute;top:12px;right:12px;background:none;border:none;font-size:24px;cursor:pointer;color:#666;" aria-label="Close">&times;</button>' +
        '<h2 style="margin:0 0 8px 0;font-size:22px;font-weight:600;color:#111;">' + title + '</h2>' +
        '<p style="margin:0 0 20px 0;color:#666;font-size:14px;">' + subtitle + '</p>' +
        '<div id="vd-error-msg" style="display:none;padding:10px;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;color:#dc2626;font-size:13px;margin-bottom:12px;"></div>' +
        '<form id="vd-step1-form">' +
          '<input type="text" id="vd-name" name="name" placeholder="Full Name *" required style="width:100%;padding:12px;margin-bottom:12px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;" />' +
          '<input type="tel" id="vd-phone" name="phone" placeholder="Phone Number *" required style="width:100%;padding:12px;margin-bottom:12px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;" />' +
          '<input type="email" id="vd-email" name="email" placeholder="Email Address (optional)" style="width:100%;padding:12px;margin-bottom:16px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;" />' +
          '<input type="text" name="company" autocomplete="off" tabindex="-1" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;" />' +
          '<input type="text" name="website" autocomplete="off" tabindex="-1" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;" />' +
          '<button type="submit" id="vd-submit-btn" style="width:100%;padding:14px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">Send Verification Code</button>' +
        '</form>' +
        '<p style="margin:16px 0 0 0;text-align:center;color:#9ca3af;font-size:12px;">We will send a verification code to your phone</p>' +
      '</div>';

    // Attach close button handler
    document.getElementById("vd-close-btn").addEventListener("click", closeModal);

    // Attach form submit handler
    document.getElementById("vd-step1-form").addEventListener("submit", function(e) {
      e.preventDefault();
      hideError();
      
      var formData = new FormData(e.target);
      var name = formData.get("name");
      var phone = formData.get("phone");
      var email = formData.get("email") || "";
      
      // Validate
      if (!name || name.trim().length < 2) {
        showError("Please enter your full name");
        return;
      }
      
      // Phone validation - at least 10 digits
      var phoneDigits = phone.replace(/\\D/g, "");
      if (phoneDigits.length < 10) {
        showError("Please enter a valid phone number (at least 10 digits)");
        return;
      }
      
      // Store lead data for step 2
      currentLeadData = {
        publicKey: config.publicKey,
        name: name.trim(),
        phone: phone.trim(),
        email: email.trim(),
        vehicle: currentVehicleData,
        source_url: window.location.href
      };
      
      // Disable button and show loading
      var btn = document.getElementById("vd-submit-btn");
      btn.disabled = true;
      btn.textContent = "Sending...";
      
      // Request OTP
      requestOTP();
    });
  }

  // Request OTP from server
  function requestOTP(isResend) {
    log("Requesting OTP for:", currentLeadData.phone, isResend ? "(resend)" : "");
    
    var xhr = new XMLHttpRequest();
    xhr.open("POST", config.endpoint + "/api/public/otp/request", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    
    xhr.onreadystatechange = function() {
      if (xhr.readyState === 4) {
        var btn = document.getElementById("vd-submit-btn");
        var resendBtn = document.getElementById("vd-resend-btn");
        
        try {
          var response = JSON.parse(xhr.responseText);
          
          if (xhr.status === 200 && response.ok) {
            log("OTP sent successfully");
            trackEvent("otp_requested", { phone: currentLeadData.phone, isResend: !!isResend });
            
            // Store cooldown duration (default 30s)
            currentLeadData.cooldown = response.cooldown || 30;
            
            // Store dev_code if provided (ONLY in development mode)
            // Safety: only store if explicitly provided by backend
            if (response.dev_code) {
              currentLeadData.dev_code = response.dev_code;
            } else {
              // Clear any previous dev_code on resend in production
              delete currentLeadData.dev_code;
            }
            
            // Move to step 2 or refresh it for resend
            if (isResend) {
              // Show success message and restart cooldown
              showError("");  // Clear any error
              var msgDiv = document.getElementById("vd-success-msg");
              if (msgDiv) {
                msgDiv.textContent = "New code sent!";
                msgDiv.style.display = "block";
                setTimeout(function() { msgDiv.style.display = "none"; }, 3000);
              }
              startResendCooldown();
            } else {
              showStep2(response.message);
            }
          } else {
            // Handle cooldown error specially
            if (response.cooldown_remaining) {
              if (resendBtn) {
                resendBtn.disabled = true;
                startResendCooldown(response.cooldown_remaining);
              }
            }
            
            // Show error
            if (btn) {
              btn.disabled = false;
              btn.textContent = "Send Verification Code";
            }
            if (resendBtn) {
              resendBtn.disabled = false;
              resendBtn.textContent = "Resend";
            }
            showError(response.error || "Failed to send verification code. Please try again.");
            log("OTP request failed:", response.error);
          }
        } catch (err) {
          if (btn) {
            btn.disabled = false;
            btn.textContent = "Send Verification Code";
          }
          if (resendBtn) {
            resendBtn.disabled = false;
            resendBtn.textContent = "Resend";
          }
          showError("An error occurred. Please try again.");
          console.error("[VerifiedDemand] OTP request error:", err);
        }
      }
    };
    
    xhr.onerror = function() {
      var btn = document.getElementById("vd-submit-btn");
      var resendBtn = document.getElementById("vd-resend-btn");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Send Verification Code";
      }
      if (resendBtn) {
        resendBtn.disabled = false;
        resendBtn.textContent = "Resend";
      }
      showError("Network error. Please check your connection and try again.");
    };
    
    xhr.send(JSON.stringify(currentLeadData));
  }

  // Resend cooldown timer
  var resendCooldownInterval = null;
  
  function startResendCooldown(initialSeconds) {
    var seconds = initialSeconds || currentLeadData.cooldown || 30;
    var resendBtn = document.getElementById("vd-resend-btn");
    var countdownSpan = document.getElementById("vd-countdown");
    
    if (resendCooldownInterval) {
      clearInterval(resendCooldownInterval);
    }
    
    if (resendBtn) resendBtn.disabled = true;
    
    function updateCountdown() {
      if (countdownSpan) {
        countdownSpan.textContent = seconds > 0 ? " (" + seconds + "s)" : "";
      }
      if (resendBtn) {
        resendBtn.textContent = seconds > 0 ? "Resend in " + seconds + "s" : "Resend";
        resendBtn.disabled = seconds > 0;
      }
      
      if (seconds <= 0) {
        clearInterval(resendCooldownInterval);
        resendCooldownInterval = null;
      }
      seconds--;
    }
    
    updateCountdown();
    resendCooldownInterval = setInterval(updateCountdown, 1000);
  }

  // Show Step 2: OTP Verification
  function showStep2(message) {
    // DEV MODE hint - ONLY show if dev_code exists (backend controls this)
    var devCodeHint = "";
    if (currentLeadData.dev_code) {
      devCodeHint = '<div style="padding:10px;background:#fef3c7;border:1px solid #fcd34d;border-radius:6px;color:#92400e;font-size:12px;margin-bottom:12px;text-align:center;"><strong>DEV MODE:</strong> Code is ' + currentLeadData.dev_code + '</div>';
    }
    
    modalContainer.innerHTML = 
      '<div style="padding:24px;">' +
        '<button id="vd-close-btn" style="position:absolute;top:12px;right:12px;background:none;border:none;font-size:24px;cursor:pointer;color:#666;" aria-label="Close">&times;</button>' +
        '<h2 style="margin:16px 0 8px 0;font-size:22px;font-weight:600;color:#111;">Verify Your Phone</h2>' +
        '<p style="margin:0 0 8px 0;color:#666;font-size:14px;">Enter the 6-digit code sent to <strong>' + currentLeadData.phone + '</strong></p>' +
        '<p style="margin:0 0 16px 0;"><button id="vd-change-phone-btn" style="background:none;border:none;color:#2563eb;cursor:pointer;font-size:12px;text-decoration:underline;padding:0;">Change phone number</button></p>' +
        devCodeHint +
        '<div id="vd-success-msg" style="display:none;padding:10px;background:#dcfce7;border:1px solid #86efac;border-radius:6px;color:#166534;font-size:13px;margin-bottom:12px;text-align:center;"></div>' +
        '<div id="vd-error-msg" style="display:none;padding:10px;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;color:#dc2626;font-size:13px;margin-bottom:12px;"></div>' +
        '<form id="vd-step2-form">' +
          '<div style="display:flex;gap:8px;justify-content:center;margin-bottom:16px;">' +
            '<input type="text" id="vd-otp-1" maxlength="1" pattern="[0-9]" inputmode="numeric" style="width:45px;height:55px;text-align:center;font-size:24px;font-weight:600;border:2px solid #ddd;border-radius:8px;" />' +
            '<input type="text" id="vd-otp-2" maxlength="1" pattern="[0-9]" inputmode="numeric" style="width:45px;height:55px;text-align:center;font-size:24px;font-weight:600;border:2px solid #ddd;border-radius:8px;" />' +
            '<input type="text" id="vd-otp-3" maxlength="1" pattern="[0-9]" inputmode="numeric" style="width:45px;height:55px;text-align:center;font-size:24px;font-weight:600;border:2px solid #ddd;border-radius:8px;" />' +
            '<input type="text" id="vd-otp-4" maxlength="1" pattern="[0-9]" inputmode="numeric" style="width:45px;height:55px;text-align:center;font-size:24px;font-weight:600;border:2px solid #ddd;border-radius:8px;" />' +
            '<input type="text" id="vd-otp-5" maxlength="1" pattern="[0-9]" inputmode="numeric" style="width:45px;height:55px;text-align:center;font-size:24px;font-weight:600;border:2px solid #ddd;border-radius:8px;" />' +
            '<input type="text" id="vd-otp-6" maxlength="1" pattern="[0-9]" inputmode="numeric" style="width:45px;height:55px;text-align:center;font-size:24px;font-weight:600;border:2px solid #ddd;border-radius:8px;" />' +
          '</div>' +
          '<button type="submit" id="vd-verify-btn" style="width:100%;padding:14px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">Verify & Unlock Price</button>' +
        '</form>' +
        '<p style="margin:16px 0 0 0;text-align:center;color:#9ca3af;font-size:12px;">Did not receive the code? <button id="vd-resend-btn" disabled style="background:none;border:none;color:#9ca3af;cursor:not-allowed;font-size:12px;">Resend in 30s</button></p>' +
      '</div>';

    // Close button
    document.getElementById("vd-close-btn").addEventListener("click", closeModal);
    
    // Change phone button - go back to step 1
    document.getElementById("vd-change-phone-btn").addEventListener("click", function() {
      showStep1();
    });
    
    // OTP input auto-advance
    var otpInputs = [];
    for (var i = 1; i <= 6; i++) {
      otpInputs.push(document.getElementById("vd-otp-" + i));
    }
    
    otpInputs.forEach(function(input, idx) {
      input.addEventListener("input", function(e) {
        // Only allow digits
        this.value = this.value.replace(/[^0-9]/g, "");
        
        if (this.value.length === 1 && idx < 5) {
          otpInputs[idx + 1].focus();
        }
      });
      
      input.addEventListener("keydown", function(e) {
        if (e.key === "Backspace" && !this.value && idx > 0) {
          otpInputs[idx - 1].focus();
        }
      });
      
      // Handle paste
      input.addEventListener("paste", function(e) {
        e.preventDefault();
        var pasteData = (e.clipboardData || window.clipboardData).getData("text");
        var digits = pasteData.replace(/[^0-9]/g, "").slice(0, 6);
        
        for (var j = 0; j < digits.length; j++) {
          if (otpInputs[j]) {
            otpInputs[j].value = digits[j];
          }
        }
        
        // Focus last filled input or next empty
        var lastIdx = Math.min(digits.length, 5);
        otpInputs[lastIdx].focus();
      });
    });
    
    // Focus first input
    otpInputs[0].focus();
    
    // Start resend cooldown timer immediately
    startResendCooldown();
    
    // Resend button
    document.getElementById("vd-resend-btn").addEventListener("click", function() {
      if (this.disabled) return;
      this.disabled = true;
      this.textContent = "Sending...";
      requestOTP(true);  // true = isResend
    });
    
    // Verify form
    document.getElementById("vd-step2-form").addEventListener("submit", function(e) {
      e.preventDefault();
      hideError();
      
      // Collect OTP
      var otp = "";
      for (var i = 1; i <= 6; i++) {
        otp += document.getElementById("vd-otp-" + i).value || "";
      }
      
      if (otp.length !== 6) {
        showError("Please enter the complete 6-digit code");
        return;
      }
      
      // Disable button
      var btn = document.getElementById("vd-verify-btn");
      btn.disabled = true;
      btn.textContent = "Verifying...";
      
      // Verify OTP
      verifyOTP(otp);
    });
  }

  // Verify OTP with server
  function verifyOTP(code) {
    log("Verifying OTP:", code);
    
    var xhr = new XMLHttpRequest();
    xhr.open("POST", config.endpoint + "/api/public/otp/verify", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    
    xhr.onreadystatechange = function() {
      if (xhr.readyState === 4) {
        var btn = document.getElementById("vd-verify-btn");
        
        try {
          var response = JSON.parse(xhr.responseText);
          
          if (xhr.status === 200 && response.ok && response.verified) {
            log("OTP verified successfully, lead created:", response.lead_id, "unlock_code:", response.unlock_code);
            trackEvent("otp_verified", { phone: currentLeadData.phone, lead_id: response.lead_id, unlock_code: response.unlock_code });
            trackEvent("lead_submit_verified", currentLeadData);
            
            // Store unlock code for success screen
            currentLeadData.unlock_code = response.unlock_code;
            
            // Show success with unlock code
            showSuccess();
          } else {
            // Show error
            if (btn) {
              btn.disabled = false;
              btn.textContent = "Verify & Unlock Price";
            }
            showError(response.error || "Invalid verification code. Please try again.");
            log("OTP verification failed:", response.error);
          }
        } catch (err) {
          if (btn) {
            btn.disabled = false;
            btn.textContent = "Verify & Unlock Price";
          }
          showError("An error occurred. Please try again.");
          console.error("[VerifiedDemand] OTP verify error:", err);
        }
      }
    };
    
    xhr.onerror = function() {
      var btn = document.getElementById("vd-verify-btn");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Verify & Unlock Price";
      }
      showError("Network error. Please check your connection and try again.");
    };
    
    xhr.send(JSON.stringify({
      publicKey: config.publicKey,
      phone: currentLeadData.phone,
      code: code
    }));
  }

  // Show Success Screen with unlock code
  function showSuccess() {
    var unlockCode = currentLeadData.unlock_code || "";
    var unlockCodeSection = "";
    
    if (unlockCode) {
      unlockCodeSection = 
        '<div style="background:#f0f9ff;border:2px solid #0ea5e9;border-radius:8px;padding:16px;margin:16px 0;">' +
          '<div style="font-size:11px;color:#0369a1;text-transform:uppercase;font-weight:bold;margin-bottom:6px;letter-spacing:1px;">Your Confirmation Code</div>' +
          '<div id="vd-unlock-code" style="font-size:28px;font-weight:bold;color:#0c4a6e;letter-spacing:3px;margin-bottom:10px;">' + unlockCode + '</div>' +
          '<button id="vd-copy-code-btn" style="padding:8px 16px;background:#0ea5e9;color:#fff;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;">📋 Copy Code</button>' +
          '<span id="vd-copy-success" style="display:none;margin-left:8px;color:#16a34a;font-size:12px;">Copied!</span>' +
        '</div>';
    }
    
    modalContainer.innerHTML = 
      '<div style="padding:40px;text-align:center;">' +
        '<div style="width:64px;height:64px;margin:0 auto 16px;background:#dcfce7;border-radius:50%;display:flex;align-items:center;justify-content:center;">' +
          '<svg style="width:32px;height:32px;color:#16a34a;" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>' +
        '</div>' +
        '<h2 style="margin:0 0 8px 0;font-size:24px;font-weight:600;color:#111;">Unlocked!</h2>' +
        '<p style="margin:0 0 8px 0;color:#16a34a;font-size:14px;font-weight:500;">✓ Phone Verified</p>' +
        unlockCodeSection +
        '<p style="margin:16px 0 24px 0;color:#666;font-size:14px;">A team member will contact you shortly.</p>' +
        '<button id="vd-done-btn" style="padding:12px 32px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;">Done</button>' +
      '</div>';

    // Copy code button handler
    var copyBtn = document.getElementById("vd-copy-code-btn");
    if (copyBtn && unlockCode) {
      copyBtn.addEventListener("click", function() {
        // Try clipboard API first
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(unlockCode).then(function() {
            showCopySuccess();
          }).catch(function() {
            fallbackCopy(unlockCode);
          });
        } else {
          fallbackCopy(unlockCode);
        }
      });
    }
    
    function fallbackCopy(text) {
      var textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand("copy");
        showCopySuccess();
      } catch (e) {
        console.error("Copy failed:", e);
      }
      document.body.removeChild(textarea);
    }
    
    function showCopySuccess() {
      var successSpan = document.getElementById("vd-copy-success");
      if (successSpan) {
        successSpan.style.display = "inline";
        setTimeout(function() { successSpan.style.display = "none"; }, 2000);
      }
    }

    document.getElementById("vd-done-btn").addEventListener("click", closeModal);
  }

  // Open modal with vehicle data
  function openModal(vehicleData) {
    console.log("[VerifiedDemand] openModal called with:", vehicleData);
    
    createModal();
    currentVehicleData = vehicleData || {};
    currentLeadData = null;

    // Track modal open event
    trackEvent("modal_open", currentVehicleData);

    // Show step 1
    showStep1();

    // Show modal
    modalOverlay.style.display = "flex";
    log("Modal opened");
  }

  // Close modal
  function closeModal() {
    if (modalOverlay) {
      modalOverlay.style.display = "none";
      trackEvent("modal_close", currentVehicleData);
      log("Modal closed");
    }
  }

  /**
   * EVENT DELEGATION - Critical for React/Lovable dynamic elements
   * 
   * Attaches listener at document level to catch clicks on elements
   * that are rendered AFTER this script loads (React hydration, etc.)
   */
  function findTrackableElement(el) {
    // Walk up DOM tree to find element with tracking attribute
    var maxDepth = 10;
    var depth = 0;
    while (el && el !== document && depth < maxDepth) {
      if (el.hasAttribute && el.hasAttribute("data-vd-trigger")) {
        return el;
      }
      el = el.parentElement;
      depth++;
    }
    return null;
  }

  // Use capture phase (true) for earliest interception
  document.addEventListener("click", function(e) {
    try {
      console.log("[VD] click captured", e.target);
      
      var trackableEl = findTrackableElement(e.target);
      
      if (trackableEl) {
        console.log("[VerifiedDemand] trigger detected - opening modal");
        
        var trackId = trackableEl.getAttribute("data-vd-trigger");
        var trackData = trackableEl.getAttribute("data-vd-vehicle") || trackableEl.getAttribute("data-track-data");
        
        log("Click detected on:", trackId);
        log("Element:", trackableEl.tagName, trackableEl.innerText || "");

        var vehicleData = {
          trackId: trackId,
          elementTag: trackableEl.tagName,
          elementText: (trackableEl.innerText || trackableEl.textContent || "").substring(0, 100),
          elementId: trackableEl.id || null
        };

        // Parse vehicle data if provided
        if (trackData) {
          try {
            var parsed = JSON.parse(trackData);
            for (var key in parsed) {
              vehicleData[key] = parsed[key];
            }
          } catch (parseErr) {
            vehicleData.rawData = trackData;
          }
        }

        // Track the click
        trackEvent("unlock_click", vehicleData);
        
        // Open the modal
        openModal(vehicleData);
      }
    } catch (err) {
      console.error("[VD] click handler exception", err);
    }
  }, true);

  // Track page view
  function trackPageView() {
    log("Page view tracked");
    trackEvent("pageview", {
      title: document.title,
      path: window.location.pathname
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", trackPageView);
  } else {
    trackPageView();
  }

  // Expose global API
  window.VerifiedDemand = {
    track: trackEvent,
    config: config,
    openModal: openModal,
    closeModal: closeModal
  };

  console.log("[VerifiedDemand] embed loaded. openModal type:", typeof window.VerifiedDemand?.openModal);
  log("Ready - tracking dynamically-rendered elements via event delegation");

})();
'''


@api_router.get("/embed.js", response_class=PlainTextResponse)
async def get_embed_script():
    """Serve the embed.js tracking script"""
    return PlainTextResponse(
        content=EMBED_JS,
        media_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff"
        }
    )


# Include the router in the main app
app.include_router(api_router)

# CORS configuration
# For auth cookies to work, we need allow_credentials=True with specific origins
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    os.environ.get("FRONTEND_URL", "http://localhost:3000"),
]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,  # Required for httpOnly cookies
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


@app.on_event("startup")
async def create_indexes():
    """Create MongoDB indexes for performance"""
    try:
        # Index for tracking_events
        await db.tracking_events.create_index([
            ("publicKey", 1),
            ("server_timestamp", -1),
            ("event", 1)
        ])
        await db.tracking_events.create_index([
            ("publicKey", 1),
            ("timestamp", -1)
        ])
        
        # Index for vehicle_leads
        await db.vehicle_leads.create_index([
            ("publicKey", 1),
            ("server_timestamp", -1)
        ])
        # Unique index for unlock_code (sparse to allow null/missing values for legacy leads)
        await db.vehicle_leads.create_index("unlock_code", unique=True, sparse=True)
        
        # Indexes for sites collection
        await db.sites.create_index("public_key", unique=True)
        await db.sites.create_index("domain")
        await db.sites.create_index("created_at")
        
        # Indexes for otp_verifications collection
        await db.otp_verifications.create_index([
            ("phone", 1),
            ("public_key", 1),
            ("status", 1)
        ])
        await db.otp_verifications.create_index("created_at")
        
        # Indexes for users collection
        await db.users.create_index("email", unique=True)
        await db.users.create_index("id", unique=True)
        
        logger.info("MongoDB indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")