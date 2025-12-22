from fastapi import FastAPI, APIRouter
from fastapi.responses import Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any
import uuid
from datetime import datetime, timezone


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


@api_router.post("/track")
async def track_event(event: TrackEvent):
    """Receive tracking events from embed.js"""
    doc = event.model_dump()
    doc['server_timestamp'] = datetime.now(timezone.utc).isoformat()
    await db.tracking_events.insert_one(doc)
    logger.info(f"Tracked event: {event.event} for key: {event.publicKey}")
    return {"status": "ok"}


# Embed.js script - served from /api/embed.js
EMBED_JS = '''
(function() {
  "use strict";

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
      if (el.hasAttribute && el.hasAttribute("data-track-click")) {
        return el;
      }
      el = el.parentElement;
      depth++;
    }
    return null;
  }

  // Use capture phase (true) for earliest interception
  document.addEventListener("click", function(e) {
    var trackableEl = findTrackableElement(e.target);
    
    if (trackableEl) {
      var trackId = trackableEl.getAttribute("data-track-click");
      var trackData = trackableEl.getAttribute("data-track-data");
      
      log("Click detected on:", trackId);
      log("Element:", trackableEl.tagName, trackableEl.innerText || "");

      var eventData = {
        trackId: trackId,
        elementTag: trackableEl.tagName,
        elementText: (trackableEl.innerText || trackableEl.textContent || "").substring(0, 100),
        elementId: trackableEl.id || null,
        elementClass: trackableEl.className || null
      };

      if (trackData) {
        try {
          eventData.customData = JSON.parse(trackData);
        } catch (e) {
          eventData.customData = trackData;
        }
      }

      trackEvent("click", eventData);
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
    config: config
  };

  log("Ready - tracking dynamically-rendered elements via event delegation");

})();
'''


@api_router.get("/embed.js")
async def get_embed_script():
    """Serve the embed.js tracking script"""
    return Response(
        content=EMBED_JS,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*"
        }
    )


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
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