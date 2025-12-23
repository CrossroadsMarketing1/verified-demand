from fastapi import FastAPI, APIRouter, Query
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


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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


# CORS headers for public endpoints
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


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
async def submit_vehicle_lead(lead: VehicleLead):
    """Receive lead submissions from embed.js modal"""
    doc = lead.model_dump()
    doc['id'] = str(uuid.uuid4())
    doc['server_timestamp'] = datetime.now(timezone.utc).isoformat()
    doc['status'] = 'new'
    await db.vehicle_leads.insert_one(doc)
    logger.info(f"Lead submitted: {lead.email} for key: {lead.publicKey}")
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
    except:
        return None


@api_router.get("/dashboard/summary")
async def get_dashboard_summary(
    public_key: str = Query(..., description="Public key to filter by"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)")
):
    """Get summary statistics for a public key"""
    
    # Parse dates, default to last 7 days
    end_date = parse_date(end) or datetime.now(timezone.utc)
    start_date = parse_date(start) or (end_date - timedelta(days=7))
    
    # Build date filter - handle both string and datetime formats in DB
    date_filter_events = {
        "publicKey": public_key,
        "$or": [
            {"timestamp": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
            {"server_timestamp": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}}
        ]
    }
    
    date_filter_leads = {
        "publicKey": public_key,
        "$or": [
            {"server_timestamp": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
            {"timestamp": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}}
        ]
    }
    
    # Count vehicle views
    vehicle_views = await db.tracking_events.count_documents({
        **date_filter_events,
        "event": {"$in": ["vehicle_view", "pageview"]}
    })
    
    # Count unlock clicks
    unlock_clicks = await db.tracking_events.count_documents({
        **date_filter_events,
        "event": {"$in": ["unlock_click", "unlock_price", "vd_trigger_click"]}
    })
    
    # Count leads
    total_leads = await db.vehicle_leads.count_documents(date_filter_leads)
    
    # Count total events
    total_events = await db.tracking_events.count_documents(date_filter_events)
    
    return {
        "public_key": public_key,
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
    public_key: str = Query(..., description="Public key to filter by"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(50, ge=1, le=500, description="Number of results"),
    skip: int = Query(0, ge=0, description="Number of results to skip")
):
    """Get leads for a public key with pagination"""
    
    # Parse dates
    end_date = parse_date(end) or datetime.now(timezone.utc)
    start_date = parse_date(start) or (end_date - timedelta(days=30))
    
    # Build query
    query = {
        "publicKey": public_key,
        "$or": [
            {"server_timestamp": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
            {"timestamp": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}}
        ]
    }
    
    # Get total count
    total_count = await db.vehicle_leads.count_documents(query)
    
    # Get leads sorted by newest first
    cursor = db.vehicle_leads.find(query).sort("server_timestamp", -1).skip(skip).limit(limit)
    leads = await cursor.to_list(length=limit)
    
    # Serialize leads
    serialized_leads = []
    for lead in leads:
        item = serialize_doc(lead)
        # Normalize field names for frontend
        item['created_at'] = item.get('server_timestamp') or item.get('timestamp')
        item['source_url'] = item.get('url') or item.get('source_url') or item.get('page_url')
        serialized_leads.append(item)
    
    return {
        "leads": serialized_leads,
        "total": total_count,
        "limit": limit,
        "skip": skip
    }


@api_router.get("/dashboard/events")
async def get_dashboard_events(
    public_key: str = Query(..., description="Public key to filter by"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    start: Optional[str] = Query(None, description="Start date (ISO format)"),
    end: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(50, ge=1, le=500, description="Number of results"),
    skip: int = Query(0, ge=0, description="Number of results to skip")
):
    """Get tracking events for a public key with pagination"""
    
    # Parse dates
    end_date = parse_date(end) or datetime.now(timezone.utc)
    start_date = parse_date(start) or (end_date - timedelta(days=30))
    
    # Build query
    query = {
        "publicKey": public_key,
        "$or": [
            {"timestamp": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}},
            {"server_timestamp": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}}
        ]
    }
    
    if event_type:
        query["event"] = event_type
    
    # Get total count
    total_count = await db.tracking_events.count_documents(query)
    
    # Get events sorted by newest first
    cursor = db.tracking_events.find(query).sort([("server_timestamp", -1), ("timestamp", -1)]).skip(skip).limit(limit)
    events = await cursor.to_list(length=limit)
    
    # Serialize events
    serialized_events = []
    for event in events:
        item = serialize_doc(event)
        # Normalize field names
        item['event_type'] = item.get('event')
        item['timestamp'] = item.get('server_timestamp') or item.get('timestamp')
        item['custom_data'] = item.get('data')
        serialized_events.append(item)
    
    return {
        "events": serialized_events,
        "total": total_count,
        "limit": limit,
        "skip": skip
    }


@api_router.get("/dashboard/event-types")
async def get_event_types(
    public_key: str = Query(..., description="Public key to filter by")
):
    """Get distinct event types for a public key"""
    event_types = await db.tracking_events.distinct("event", {"publicKey": public_key})
    return {"event_types": event_types}


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
        
        logger.info("MongoDB indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")