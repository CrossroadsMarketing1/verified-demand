/**
 * Embed Analytics Script
 * 
 * Works with dynamically-rendered elements (React, Lovable, etc.)
 * Uses event delegation to capture clicks on elements that may be rendered after page load.
 * 
 * Usage:
 *   <script src="https://YOUR_DOMAIN/embed.js" data-site-id="YOUR_SITE_ID"></script>
 *   
 *   Add data-debug="true" to the script tag for console logging:
 *   <script src="https://YOUR_DOMAIN/embed.js" data-site-id="YOUR_SITE_ID" data-debug="true"></script>
 * 
 * Track clicks by adding data-track-click attribute:
 *   <button data-track-click="signup-cta">Sign Up</button>
 */
(function() {
  'use strict';

  // Get script element and configuration
  var scriptEl = document.currentScript || (function() {
    var scripts = document.getElementsByTagName('script');
    for (var i = scripts.length - 1; i >= 0; i--) {
      if (scripts[i].src && scripts[i].src.indexOf('embed.js') !== -1) {
        return scripts[i];
      }
    }
    return null;
  })();

  var config = {
    siteId: scriptEl ? scriptEl.getAttribute('data-site-id') : null,
    debug: scriptEl ? scriptEl.getAttribute('data-debug') === 'true' : false,
    endpoint: scriptEl ? (scriptEl.getAttribute('data-endpoint') || '') : ''
  };

  // Debug logger
  function log() {
    if (config.debug) {
      var args = ['[Embed Analytics]'].concat(Array.prototype.slice.call(arguments));
      console.log.apply(console, args);
    }
  }

  log('Initialized with config:', config);

  // Track event function
  function trackEvent(eventType, data) {
    log('Track event:', eventType, data);

    var payload = {
      event: eventType,
      siteId: config.siteId,
      timestamp: new Date().toISOString(),
      url: window.location.href,
      referrer: document.referrer,
      data: data
    };

    // Send to backend if endpoint configured
    if (config.endpoint) {
      try {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', config.endpoint + '/api/track', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(JSON.stringify(payload));
        log('Event sent to endpoint');
      } catch (e) {
        log('Error sending event:', e);
      }
    }

    // Also fire custom event for local handling
    var customEvent;
    try {
      customEvent = new CustomEvent('embed-analytics', { detail: payload });
    } catch (e) {
      // IE fallback
      customEvent = document.createEvent('CustomEvent');
      customEvent.initCustomEvent('embed-analytics', true, true, payload);
    }
    document.dispatchEvent(customEvent);
  }

  /**
   * EVENT DELEGATION - Key for dynamically-rendered elements
   * 
   * Instead of attaching handlers to individual elements (which wouldn't work
   * for elements rendered after script load), we listen at the document level
   * and check if the clicked element (or its parents) has our tracking attribute.
   */
  function findTrackableElement(el) {
    // Walk up the DOM tree to find element with tracking attribute
    while (el && el !== document) {
      if (el.hasAttribute && el.hasAttribute('data-track-click')) {
        return el;
      }
      el = el.parentElement;
    }
    return null;
  }

  // Attach click handler using event delegation (captures dynamically-added elements)
  document.addEventListener('click', function(e) {
    var trackableEl = findTrackableElement(e.target);
    
    if (trackableEl) {
      var trackId = trackableEl.getAttribute('data-track-click');
      var trackData = trackableEl.getAttribute('data-track-data');
      
      log('Click detected on trackable element:', trackId);
      log('Element:', trackableEl);
      log('Element tag:', trackableEl.tagName);
      log('Element text:', trackableEl.innerText || trackableEl.textContent);

      var eventData = {
        trackId: trackId,
        elementTag: trackableEl.tagName,
        elementText: (trackableEl.innerText || trackableEl.textContent || '').substring(0, 100),
        elementId: trackableEl.id || null,
        elementClass: trackableEl.className || null
      };

      // Parse custom data if provided
      if (trackData) {
        try {
          eventData.customData = JSON.parse(trackData);
        } catch (e) {
          eventData.customData = trackData;
        }
      }

      trackEvent('click', eventData);
    }
  }, true); // Use capture phase for earliest interception

  // Track page view on load
  function trackPageView() {
    log('Page view tracked');
    trackEvent('pageview', {
      title: document.title,
      path: window.location.pathname
    });
  }

  // Run when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', trackPageView);
  } else {
    trackPageView();
  }

  // Expose API globally
  window.EmbedAnalytics = {
    track: function(eventType, data) {
      trackEvent(eventType, data);
    },
    config: config,
    version: '1.0.0'
  };

  log('Script fully loaded. Ready to track dynamically-rendered elements.');
  log('To track clicks, add data-track-click="your-id" to any element.');

})();
