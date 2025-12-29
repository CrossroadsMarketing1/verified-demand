from fastapi import FastAPI, APIRouter, Query, BackgroundTasks
from fastapi.responses import Response, PlainTextResponse
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

def is_smtp_configured() -> bool:
    """Check if SMTP is properly configured"""
    return all([
        SMTP_CONFIG["host"],
        SMTP_CONFIG["user"],
        SMTP_CONFIG["password"],
        SMTP_CONFIG["from_email"]
    ])

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
                <h2 style="margin: 0;">🎉 New Lead Received!</h2>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">{site.get('name', 'Unknown Site')}</p>
            </div>
            <div class="content">
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
    
    text = f"""
New Lead Received!
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
async def track_event(event: TrackEvent):
    """Receive tracking events from embed.js"""
    doc = event.model_dump()
    doc['server_timestamp'] = datetime.now(timezone.utc).isoformat()
    await db.tracking_events.insert_one(doc)
    logger.info(f"Tracked event: {event.event} for key: {event.publicKey}")
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
async def public_track_event(event: TrackEvent):
    """Public tracking endpoint for embed.js"""
    doc = event.model_dump()
    doc['server_timestamp'] = datetime.now(timezone.utc).isoformat()
    await db.tracking_events.insert_one(doc)
    logger.info(f"Public tracked event: {event.event} for key: {event.publicKey}")
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
async def submit_vehicle_lead(lead: VehicleLead, background_tasks: BackgroundTasks):
    """Receive lead submissions from embed.js modal"""
    doc = lead.model_dump()
    doc['id'] = str(uuid.uuid4())
    doc['server_timestamp'] = datetime.now(timezone.utc).isoformat()
    doc['status'] = 'new'
    await db.vehicle_leads.insert_one(doc)
    logger.info(f"Lead submitted: {lead.email} for key: {lead.publicKey}")
    
    # Send notification email in background (don't block response)
    background_tasks.add_task(send_lead_notification, doc)
    
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
    public_key: Optional[str] = Query(None, alias="public_key", description="Public key to filter by"),
    publicKey: Optional[str] = Query(None, description="Public key (alternative param name)"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)")
):
    """Get summary statistics for a public key"""
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"error": "public_key parameter is required"}
    
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
    public_key: Optional[str] = Query(None, alias="public_key", description="Public key to filter by"),
    publicKey: Optional[str] = Query(None, description="Public key (alternative param name)"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(50, ge=1, le=500, description="Number of results"),
    skip: int = Query(0, ge=0, description="Number of results to skip")
):
    """Get leads for a public key with pagination"""
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"error": "public_key parameter is required", "leads": [], "total": 0}
    
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
    public_key: Optional[str] = Query(None, alias="public_key", description="Public key to filter by"),
    publicKey: Optional[str] = Query(None, description="Public key (alternative param name)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(50, ge=1, le=500, description="Number of results"),
    skip: int = Query(0, ge=0, description="Number of results to skip")
):
    """Get tracking events for a public key with pagination"""
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"error": "public_key parameter is required", "events": [], "total": 0}
    
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
    public_key: Optional[str] = Query(None, alias="public_key", description="Public key to filter by"),
    publicKey: Optional[str] = Query(None, description="Public key (alternative param name)")
):
    """Get distinct event types for a public key"""
    
    # Accept either public_key or publicKey parameter
    key = public_key or publicKey
    if not key:
        return {"event_types": []}
    
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
# Site Management API Endpoints
# ============================================

import secrets
import re

# Site models
class SiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    domain: Optional[str] = Field(None, max_length=253)
    notification_emails: Optional[List[str]] = Field(default_factory=list)


class SiteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    domain: Optional[str] = Field(None, max_length=253)
    is_active: Optional[bool] = None
    notification_emails: Optional[List[str]] = None


def generate_public_key() -> str:
    """Generate a cryptographically secure public key (32 hex chars)"""
    return secrets.token_hex(16)


def validate_domain(domain: str) -> bool:
    """Basic domain format validation"""
    if not domain:
        return True
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
    return bool(re.match(pattern, domain))


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


@api_router.post("/dashboard/sites")
async def create_site(site: SiteCreate):
    """Create a new site with auto-generated public key"""
    
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
    
    doc = {
        "site_id": f"site_{secrets.token_hex(8)}",
        "name": site.name,
        "domain": site.domain,
        "public_key": public_key,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "is_active": True,
        "notification_emails": site.notification_emails or [],
        "previous_public_keys": []
    }
    
    await db.sites.insert_one(doc)
    logger.info(f"Created site: {site.name} with key: {public_key}")
    
    return serialize_site(doc)


@api_router.get("/dashboard/sites")
async def list_sites():
    """List all sites, newest first"""
    cursor = db.sites.find({}).sort([("created_at", -1), ("_id", -1)])
    sites = await cursor.to_list(length=1000)
    return {"sites": [serialize_site(s) for s in sites]}


@api_router.get("/dashboard/sites/{public_key}")
async def get_site(public_key: str):
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
    
    return serialize_site(site)


@api_router.patch("/dashboard/sites/{public_key}")
async def update_site(public_key: str, update: SiteUpdate):
    """Update a site's settings"""
    
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
    
    await db.sites.update_one(
        {"public_key": public_key},
        {"$set": update_doc}
    )
    
    # Fetch and return updated site
    updated_site = await db.sites.find_one({"public_key": public_key})
    logger.info(f"Updated site: {public_key}")
    
    return serialize_site(updated_site)


@api_router.post("/dashboard/sites/{public_key}/rotate-key")
async def rotate_site_key(public_key: str):
    """Rotate a site's public key, preserving the old key in history"""
    
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
async def send_test_email(public_key: str):
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

  // Open modal with vehicle data
  function openModal(vehicleData) {
    console.log("[VerifiedDemand] openModal called with:", vehicleData);
    
    createModal();
    currentVehicleData = vehicleData || {};

    // Track modal open event
    trackEvent("modal_open", currentVehicleData);

    // Build modal content
    var title = currentVehicleData.title || currentVehicleData.vehicleTitle || "Get Verified Price";
    var subtitle = currentVehicleData.subtitle || "Enter your details to unlock the instant price";

    modalContainer.innerHTML = 
      '<div style="padding:24px;">' +
        '<button id="vd-close-btn" style="position:absolute;top:12px;right:12px;background:none;border:none;font-size:24px;cursor:pointer;color:#666;">&times;</button>' +
        '<h2 style="margin:0 0 8px 0;font-size:22px;font-weight:600;color:#111;">' + title + '</h2>' +
        '<p style="margin:0 0 20px 0;color:#666;font-size:14px;">' + subtitle + '</p>' +
        '<form id="vd-lead-form">' +
          '<input type="text" name="name" placeholder="Full Name" required style="width:100%;padding:12px;margin-bottom:12px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;" />' +
          '<input type="email" name="email" placeholder="Email Address" required style="width:100%;padding:12px;margin-bottom:12px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;" />' +
          '<input type="tel" name="phone" placeholder="Phone Number" required style="width:100%;padding:12px;margin-bottom:16px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box;" />' +
          '<button type="submit" style="width:100%;padding:14px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">Unlock Price</button>' +
        '</form>' +
      '</div>';

    // Attach close button handler
    document.getElementById("vd-close-btn").addEventListener("click", closeModal);

    // Attach form submit handler
    document.getElementById("vd-lead-form").addEventListener("submit", function(e) {
      e.preventDefault();
      var formData = new FormData(e.target);
      var leadData = {
        publicKey: config.publicKey,
        name: formData.get("name"),
        email: formData.get("email"),
        phone: formData.get("phone"),
        vehicle: currentVehicleData,
        url: window.location.href,
        referrer: document.referrer
      };
      
      // Submit lead to dedicated endpoint
      console.log("[VerifiedDemand] Submitting lead:", leadData);
      try {
        var xhr = new XMLHttpRequest();
        xhr.open("POST", config.endpoint + "/api/public/vehicle-lead", true);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function() {
          if (xhr.readyState === 4) {
            if (xhr.status === 200) {
              console.log("[VerifiedDemand] Lead submitted successfully");
              log("Lead submitted successfully");
            } else {
              console.error("[VerifiedDemand] Lead submission failed:", xhr.status, xhr.responseText);
            }
          }
        };
        xhr.send(JSON.stringify(leadData));
      } catch (err) {
        console.error("[VerifiedDemand] Lead submission error:", err);
      }
      
      // Also track the event
      trackEvent("lead_submit", leadData);
      log("Lead submitted:", leadData);

      // Show success message
      modalContainer.innerHTML = 
        '<div style="padding:40px;text-align:center;">' +
          '<div style="font-size:48px;margin-bottom:16px;">✓</div>' +
          '<h2 style="margin:0 0 8px 0;font-size:22px;font-weight:600;color:#111;">Thank You!</h2>' +
          '<p style="margin:0 0 20px 0;color:#666;font-size:14px;">We will contact you shortly with your verified price.</p>' +
          '<button id="vd-done-btn" style="padding:12px 32px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;">Done</button>' +
        '</div>';

      document.getElementById("vd-done-btn").addEventListener("click", closeModal);
    });

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

# CORS configuration - allow all origins for embed script usage
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,  # Must be False when using allow_origins=["*"]
    allow_origins=["*"],  # Allow all origins for embed.js cross-origin requests
    allow_methods=["GET", "POST", "OPTIONS"],
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
        
        # Indexes for sites collection
        await db.sites.create_index("public_key", unique=True)
        await db.sites.create_index("domain")
        await db.sites.create_index("created_at")
        
        logger.info("MongoDB indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")