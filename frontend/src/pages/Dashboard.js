import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Configure axios to send cookies
axios.defaults.withCredentials = true;

// Date range options
const DATE_RANGES = {
  "7d": { label: "Last 7 Days", days: 7 },
  "30d": { label: "Last 30 Days", days: 30 },
  "90d": { label: "Last 90 Days", days: 90 },
  "custom": { label: "Custom Range", days: null }
};

// Summary Card Component
const SummaryCard = ({ title, value, icon, loading }) => (
  <div className="bg-white rounded-lg shadow p-6 border border-gray-200">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-gray-500">{title}</p>
        <p className="text-3xl font-bold text-gray-900 mt-1">
          {loading ? "..." : value.toLocaleString()}
        </p>
      </div>
      <div className="text-3xl">{icon}</div>
    </div>
  </div>
);

// Expandable JSON Component
const ExpandableJSON = ({ data, label = "View Details" }) => {
  const [expanded, setExpanded] = useState(false);
  
  if (!data) return <span className="text-gray-400">-</span>;
  
  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-blue-600 hover:text-blue-800 text-sm font-medium"
      >
        {expanded ? "Hide" : label}
      </button>
      {expanded && (
        <pre className="mt-2 p-3 bg-gray-100 rounded text-xs overflow-auto max-h-48">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
};

// Format vehicle display
const formatVehicle = (vehicle) => {
  if (!vehicle) return "(no vehicle data)";
  const { year, make, model, trim } = vehicle;
  if (year || make || model) {
    return [year, make, model, trim].filter(Boolean).join(" ");
  }
  return "(vehicle data)";
};

// Lead flags badge component
const LeadFlags = ({ lead }) => {
  const flags = [];
  
  if (lead.is_suspected_spam) {
    flags.push(
      <span key="spam" className="px-1.5 py-0.5 text-xs rounded bg-red-100 text-red-700" title="Suspected spam (honeypot triggered)">
        🚫 Spam
      </span>
    );
  }
  
  if (lead.is_invalid_contact) {
    flags.push(
      <span key="invalid" className="px-1.5 py-0.5 text-xs rounded bg-yellow-100 text-yellow-700" title={`Email valid: ${lead.email_valid}, Phone valid: ${lead.phone_valid}`}>
        ⚠️ Invalid
      </span>
    );
  }
  
  if (flags.length === 0) {
    return <span className="text-gray-400 text-xs">-</span>;
  }
  
  return <div className="flex flex-col gap-1">{flags}</div>;
};

// Phone verified badge component
const VerifiedBadge = ({ lead }) => {
  if (lead.is_verified) {
    const verifiedAt = lead.verified_at ? new Date(lead.verified_at).toLocaleString() : 'N/A';
    return (
      <span 
        className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-800" 
        title={`Phone verified via ${lead.verification_method || 'SMS OTP'} at ${verifiedAt}`}
      >
        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
        </svg>
        Verified
      </span>
    );
  }
  return (
    <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-500">
      Unverified
    </span>
  );
};

// Unlock code display with copy button
const UnlockCodeCell = ({ code }) => {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = async () => {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      // Fallback for older browsers
      const textarea = document.createElement('textarea');
      textarea.value = code;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };
  
  if (!code) {
    return <span className="text-gray-400 text-xs">-</span>;
  }
  
  return (
    <div className="flex items-center gap-1">
      <code className="px-1.5 py-0.5 bg-sky-50 text-sky-700 text-xs font-mono rounded border border-sky-200">
        {code}
      </code>
      <button
        onClick={handleCopy}
        className="p-1 text-gray-400 hover:text-sky-600 transition-colors"
        title={copied ? "Copied!" : "Copy code"}
      >
        {copied ? (
          <svg className="w-3.5 h-3.5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
        )}
      </button>
    </div>
  );
};

// Domain status badge component
const DomainStatusBadge = ({ status, domain }) => {
  if (status === 'verified') {
    return (
      <span className="px-1.5 py-0.5 text-xs rounded bg-green-100 text-green-700" title={`Domain: ${domain || 'N/A'}`}>
        ✓ Verified
      </span>
    );
  }
  if (status === 'mismatch') {
    return (
      <span className="px-1.5 py-0.5 text-xs rounded bg-orange-100 text-orange-700" title={`Domain: ${domain || 'N/A'}`}>
        ⚠ Mismatch
      </span>
    );
  }
  return (
    <span className="px-1.5 py-0.5 text-xs rounded bg-gray-100 text-gray-600" title={`Domain: ${domain || 'N/A'}`}>
      ? Unknown
    </span>
  );
};

// Leads Table Component
const LeadsTable = ({ leads, loading, total, skip, limit, onPageChange, hideFlagged, onToggleHideFlagged, hideDomainMismatch, onToggleHideDomainMismatch, showOnlyVerified, onToggleShowOnlyVerified, showOnlyWithCode, onToggleShowOnlyWithCode }) => {
  if (loading) {
    return <div className="text-center py-8 text-gray-500">Loading leads...</div>;
  }
  
  // Filter leads based on toggle states
  let displayLeads = leads;
  if (hideFlagged) {
    displayLeads = displayLeads.filter(lead => !lead.is_suspected_spam && !lead.is_invalid_contact);
  }
  if (hideDomainMismatch) {
    displayLeads = displayLeads.filter(lead => lead.domain_status !== 'mismatch');
  }
  if (showOnlyVerified) {
    displayLeads = displayLeads.filter(lead => lead.is_verified === true);
  }
  if (showOnlyWithCode) {
    displayLeads = displayLeads.filter(lead => lead.unlock_code);
  }
  
  const hiddenCount = leads.length - displayLeads.length;
  const verifiedCount = leads.filter(l => l.is_verified === true).length;
  const withCodeCount = leads.filter(l => l.unlock_code).length;
  
  return (
    <div>
      {/* Filter toggles */}
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={showOnlyVerified}
            onChange={() => onToggleShowOnlyVerified(!showOnlyVerified)}
            className="rounded border-gray-300 text-green-600 focus:ring-green-500"
          />
          <span className="flex items-center gap-1">
            Show only verified
            <span className="px-1.5 py-0.5 text-xs bg-green-100 text-green-700 rounded-full">{verifiedCount}</span>
          </span>
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={showOnlyWithCode}
            onChange={() => onToggleShowOnlyWithCode(!showOnlyWithCode)}
            className="rounded border-gray-300 text-sky-600 focus:ring-sky-500"
          />
          <span className="flex items-center gap-1">
            Has code only
            <span className="px-1.5 py-0.5 text-xs bg-sky-100 text-sky-700 rounded-full">{withCodeCount}</span>
          </span>
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={hideFlagged}
            onChange={() => onToggleHideFlagged(!hideFlagged)}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Hide flagged (spam/invalid)
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={hideDomainMismatch}
            onChange={() => onToggleHideDomainMismatch(!hideDomainMismatch)}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Hide domain mismatches
        </label>
        {hiddenCount > 0 && (
          <span className="text-xs text-gray-500">
            ({hiddenCount} hidden)
          </span>
        )}
      </div>
      
      {!displayLeads.length ? (
        <div className="text-center py-8 text-gray-500">
          {leads.length > 0 ? "All leads are hidden by filters. Uncheck filters to view." : "No leads found"}
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date/Time</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Email</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Phone</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Verified</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Code</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Vehicle</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Flags</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {displayLeads.map((lead, idx) => (
                  <tr 
                    key={lead._id || idx} 
                    className={`hover:bg-gray-50 ${lead.is_verified ? 'bg-green-50/30' : ''} ${lead.is_suspected_spam ? 'bg-red-50' : lead.is_invalid_contact ? 'bg-yellow-50' : lead.domain_status === 'mismatch' ? 'bg-orange-50' : ''}`}
                  >
                    <td className="px-3 py-3 text-sm text-gray-900 whitespace-nowrap">
                      {lead.created_at ? new Date(lead.created_at).toLocaleString() : "-"}
                    </td>
                    <td className="px-3 py-3 text-sm text-gray-900">{lead.name || "-"}</td>
                    <td className="px-3 py-3 text-sm text-gray-900">
                      <span className={!lead.email_valid && lead.email_valid !== undefined ? 'text-red-600' : ''}>
                        {lead.email || "-"}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-sm text-gray-900">
                      <span className={!lead.phone_valid && lead.phone_valid !== undefined ? 'text-red-600' : ''}>
                        {lead.phone || "-"}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-sm">
                      <VerifiedBadge lead={lead} />
                    </td>
                    <td className="px-3 py-3 text-sm">
                      <UnlockCodeCell code={lead.unlock_code} />
                    </td>
                    <td className="px-3 py-3 text-sm text-gray-900">
                      <span title={JSON.stringify(lead.vehicle, null, 2)}>
                        {formatVehicle(lead.vehicle)}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-sm text-gray-500 max-w-24 truncate" title={lead.source_domain}>
                      {lead.source_domain || "-"}
                    </td>
                    <td className="px-3 py-3 text-sm">
                      <DomainStatusBadge status={lead.domain_status} domain={lead.source_domain} />
                    </td>
                    <td className="px-3 py-3 text-sm">
                      <LeadFlags lead={lead} />
                    </td>
                    <td className="px-3 py-3 text-sm">
                      <ExpandableJSON data={lead} label="View" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          
          {/* Pagination */}
          <div className="flex items-center justify-between mt-4 px-4">
            <span className="text-sm text-gray-700">
              Showing {skip + 1} - {Math.min(skip + leads.length, total)} of {total}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => onPageChange(Math.max(0, skip - limit))}
                disabled={skip === 0}
                className="px-3 py-1 text-sm border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                Previous
              </button>
              <button
                onClick={() => onPageChange(skip + limit)}
                disabled={skip + limit >= total}
                className="px-3 py-1 text-sm border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

// Events Table Component
const EventsTable = ({ events, loading, total, skip, limit, onPageChange, eventTypes, selectedType, onTypeChange }) => {
  if (loading) {
    return <div className="text-center py-8 text-gray-500">Loading events...</div>;
  }
  
  return (
    <div>
      {/* Event type filter */}
      <div className="mb-4">
        <select
          value={selectedType}
          onChange={(e) => onTypeChange(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
        >
          <option value="">All Event Types</option>
          {eventTypes.map(type => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>
      </div>
      
      {!events.length ? (
        <div className="text-center py-8 text-gray-500">No events found</div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date/Time</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Event Type</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Page URL</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Referrer</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Data</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {events.map((event, idx) => (
                  <tr key={event._id || idx} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap">
                      {event.timestamp ? new Date(event.timestamp).toLocaleString() : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className="px-2 py-1 text-xs font-medium rounded-full bg-blue-100 text-blue-800">
                        {event.event_type || event.event || "-"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">
                      {event.url ? (
                        <a
                          href={event.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:text-blue-800 truncate block max-w-xs"
                          title={event.url}
                        >
                          {new URL(event.url).pathname || "/"}
                        </a>
                      ) : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 truncate max-w-xs" title={event.referrer}>
                      {event.referrer || "-"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <ExpandableJSON data={event.custom_data || event.data} label="View" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          
          {/* Pagination */}
          <div className="flex items-center justify-between mt-4 px-4">
            <span className="text-sm text-gray-700">
              Showing {skip + 1} - {Math.min(skip + events.length, total)} of {total}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => onPageChange(Math.max(0, skip - limit))}
                disabled={skip === 0}
                className="px-3 py-1 text-sm border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                Previous
              </button>
              <button
                onClick={() => onPageChange(skip + limit)}
                disabled={skip + limit >= total}
                className="px-3 py-1 text-sm border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

// Main Dashboard Component
const Dashboard = () => {
  // State
  const [publicKey, setPublicKey] = useState(() => {
    // Load from localStorage if available
    return localStorage.getItem("vd_selected_site") || "";
  });
  const [inputKey, setInputKey] = useState(() => {
    return localStorage.getItem("vd_selected_site") || "";
  });
  const [dateRange, setDateRange] = useState("7d");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [activeTab, setActiveTab] = useState("leads");
  
  // Sites state
  const [sites, setSites] = useState([]);
  const [selectedSiteId, setSelectedSiteId] = useState("");
  
  // Data state
  const [summary, setSummary] = useState(null);
  const [leads, setLeads] = useState([]);
  const [events, setEvents] = useState([]);
  const [eventTypes, setEventTypes] = useState([]);
  const [selectedEventType, setSelectedEventType] = useState("");
  
  // Filter state
  const [hideFlaggedLeads, setHideFlaggedLeads] = useState(false);
  const [hideDomainMismatch, setHideDomainMismatch] = useState(false);
  const [showOnlyVerified, setShowOnlyVerified] = useState(false);
  const [showOnlyWithCode, setShowOnlyWithCode] = useState(false);
  
  // Pagination
  const [leadsSkip, setLeadsSkip] = useState(0);
  const [leadsTotal, setLeadsTotal] = useState(0);
  const [eventsSkip, setEventsSkip] = useState(0);
  const [eventsTotal, setEventsTotal] = useState(0);
  const limit = 50;
  
  // Loading/error state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  // Fetch sites on mount
  useEffect(() => {
    const fetchSites = async () => {
      try {
        const response = await axios.get(`${API}/dashboard/sites`);
        setSites(response.data.sites || []);
        
        // If we have a saved key, try to find the matching site
        const savedKey = localStorage.getItem("vd_selected_site");
        if (savedKey) {
          const matchingSite = response.data.sites?.find(s => s.public_key === savedKey);
          if (matchingSite) {
            setSelectedSiteId(matchingSite.public_key);
          }
        }
      } catch (err) {
        console.error("Error fetching sites:", err);
      }
    };
    fetchSites();
  }, []);
  
  // Handle site selection from dropdown
  const handleSiteSelect = (e) => {
    const siteKey = e.target.value;
    setSelectedSiteId(siteKey);
    if (siteKey) {
      setInputKey(siteKey);
      setPublicKey(siteKey);
      setLeadsSkip(0);
      setEventsSkip(0);
      localStorage.setItem("vd_selected_site", siteKey);
    }
  };
  
  // Get date range params
  const getDateParams = useCallback(() => {
    const now = new Date();
    let start, end;
    
    if (dateRange === "custom") {
      start = customStart;
      end = customEnd;
    } else {
      const days = DATE_RANGES[dateRange]?.days || 7;
      end = now.toISOString();
      start = new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString();
    }
    
    return { start, end };
  }, [dateRange, customStart, customEnd]);
  
  // Fetch summary
  const fetchSummary = useCallback(async () => {
    if (!publicKey) return;
    
    try {
      const { start, end } = getDateParams();
      const response = await axios.get(`${API}/dashboard/summary`, {
        params: { public_key: publicKey, start, end }
      });
      setSummary(response.data);
    } catch (err) {
      console.error("Error fetching summary:", err);
      setError("Failed to load summary data");
    }
  }, [publicKey, getDateParams]);
  
  // Fetch leads
  const fetchLeads = useCallback(async (skip = 0) => {
    if (!publicKey) return;
    
    try {
      const { start, end } = getDateParams();
      const response = await axios.get(`${API}/dashboard/leads`, {
        params: { public_key: publicKey, start, end, limit, skip }
      });
      setLeads(response.data.leads);
      setLeadsTotal(response.data.total);
      setLeadsSkip(skip);
    } catch (err) {
      console.error("Error fetching leads:", err);
      setError("Failed to load leads");
    }
  }, [publicKey, getDateParams]);
  
  // Fetch events
  const fetchEvents = useCallback(async (skip = 0, eventType = "") => {
    if (!publicKey) return;
    
    try {
      const { start, end } = getDateParams();
      const params = { public_key: publicKey, start, end, limit, skip };
      if (eventType) params.event_type = eventType;
      
      const response = await axios.get(`${API}/dashboard/events`, { params });
      setEvents(response.data.events);
      setEventsTotal(response.data.total);
      setEventsSkip(skip);
    } catch (err) {
      console.error("Error fetching events:", err);
      setError("Failed to load events");
    }
  }, [publicKey, getDateParams]);
  
  // Fetch event types
  const fetchEventTypes = useCallback(async () => {
    if (!publicKey) return;
    
    try {
      const response = await axios.get(`${API}/dashboard/event-types`, {
        params: { public_key: publicKey }
      });
      setEventTypes(response.data.event_types || []);
    } catch (err) {
      console.error("Error fetching event types:", err);
    }
  }, [publicKey]);
  
  // Load all data
  const loadData = useCallback(async () => {
    if (!publicKey) return;
    
    setLoading(true);
    setError(null);
    
    try {
      await Promise.all([
        fetchSummary(),
        fetchLeads(0),
        fetchEvents(0, selectedEventType),
        fetchEventTypes()
      ]);
    } catch (err) {
      setError("Failed to load data. Please check your public key.");
    } finally {
      setLoading(false);
    }
  }, [publicKey, selectedEventType, fetchSummary, fetchLeads, fetchEvents, fetchEventTypes]);
  
  // Handle load button click
  const handleLoadData = () => {
    if (!inputKey.trim()) {
      setError("Please enter a public key");
      return;
    }
    const key = inputKey.trim();
    setPublicKey(key);
    setLeadsSkip(0);
    setEventsSkip(0);
    localStorage.setItem("vd_selected_site", key);
    
    // Update dropdown if the key matches a site
    const matchingSite = sites.find(s => s.public_key === key);
    if (matchingSite) {
      setSelectedSiteId(key);
    } else {
      setSelectedSiteId("");
    }
  };
  
  // Load data when public key changes
  useEffect(() => {
    if (publicKey) {
      loadData();
    }
  }, [publicKey, loadData]);
  
  // Handle event type change
  const handleEventTypeChange = (type) => {
    setSelectedEventType(type);
    setEventsSkip(0);
    fetchEvents(0, type);
  };
  
  // Copy public key
  const copyPublicKey = () => {
    navigator.clipboard.writeText(publicKey);
  };
  
  // Use test key
  const useTestKey = () => {
    const testKey = "ef0f22841f1cbb777784ee71665c06d0";
    setInputKey(testKey);
    setPublicKey(testKey);
    setSelectedSiteId("");
    setLeadsSkip(0);
    setEventsSkip(0);
    localStorage.setItem("vd_selected_site", testKey);
  };
  
  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">VerifiedDemand Dashboard</h1>
            <p className="text-sm text-gray-500 mt-1">Analytics & Lead Tracking</p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to="/dashboard/sites"
              className="px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50 text-gray-700"
            >
              Sites / Install
            </Link>
            <button
              onClick={async () => {
                try {
                  await axios.post(`${API}/auth/logout`);
                  window.location.href = '/login';
                } catch (e) {
                  console.error('Logout error:', e);
                }
              }}
              className="px-4 py-2 text-red-600 border border-red-200 rounded-md hover:bg-red-50"
            >
              Logout
            </button>
          </div>
        </div>
      </header>
      
      <main className="max-w-7xl mx-auto px-4 py-6">
        {/* Filters */}
        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <div className="flex flex-wrap gap-4 items-end">
            {/* Site Selector */}
            {sites.length > 0 && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Select Site
                </label>
                <select
                  value={selectedSiteId}
                  onChange={handleSiteSelect}
                  className="px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 min-w-48"
                >
                  <option value="">-- Select a site --</option>
                  {sites.map(site => (
                    <option key={site.public_key} value={site.public_key}>
                      {site.name} {site.domain ? `(${site.domain})` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}
            
            {/* Public Key Input */}
            <div className="flex-1 min-w-64">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Public Key
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={inputKey}
                  onChange={(e) => setInputKey(e.target.value)}
                  placeholder="Enter your public key"
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                />
                <button
                  onClick={useTestKey}
                  className="px-3 py-2 text-sm bg-gray-100 border border-gray-300 rounded-md hover:bg-gray-200 whitespace-nowrap"
                  title="Use test public key"
                >
                  Use Test Key
                </button>
                {publicKey && (
                  <button
                    onClick={copyPublicKey}
                    className="px-3 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
                    title="Copy public key"
                  >
                    Copy
                  </button>
                )}
              </div>
            </div>
            
            {/* Date Range */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Date Range
              </label>
              <select
                value={dateRange}
                onChange={(e) => setDateRange(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
              >
                {Object.entries(DATE_RANGES).map(([key, { label }]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </div>
            
            {/* Custom Date Inputs */}
            {dateRange === "custom" && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Start</label>
                  <input
                    type="date"
                    value={customStart}
                    onChange={(e) => setCustomStart(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-md"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">End</label>
                  <input
                    type="date"
                    value={customEnd}
                    onChange={(e) => setCustomEnd(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-md"
                  />
                </div>
              </>
            )}
            
            {/* Load Button */}
            <button
              onClick={handleLoadData}
              disabled={loading}
              className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {loading ? "Loading..." : "Load Data"}
            </button>
          </div>
          
          {/* Error Message */}
          {error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm">
              {error}
            </div>
          )}
        </div>
        
        {/* Empty State */}
        {!publicKey && (
          <div className="bg-white rounded-lg shadow p-12 text-center">
            <div className="text-5xl mb-4">📊</div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Welcome to the Dashboard</h2>
            <p className="text-gray-500">Enter your public key above to load your leads and tracking data.</p>
          </div>
        )}
        
        {/* Dashboard Content */}
        {publicKey && (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <SummaryCard
                title="Total Vehicle Views"
                value={summary?.total_vehicle_views || 0}
                icon="👁️"
                loading={loading}
              />
              <SummaryCard
                title="Total Unlock Clicks"
                value={summary?.total_unlock_clicks || 0}
                icon="🔓"
                loading={loading}
              />
              <SummaryCard
                title="Total Leads Captured"
                value={summary?.total_leads || 0}
                icon="📋"
                loading={loading}
              />
              <SummaryCard
                title="Total Events"
                value={summary?.total_events || 0}
                icon="📈"
                loading={loading}
              />
            </div>
            
            {/* Tabs */}
            <div className="bg-white rounded-lg shadow">
              <div className="border-b border-gray-200">
                <nav className="flex -mb-px">
                  <button
                    onClick={() => setActiveTab("leads")}
                    className={`px-6 py-4 text-sm font-medium border-b-2 ${
                      activeTab === "leads"
                        ? "border-blue-500 text-blue-600"
                        : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                    }`}
                  >
                    Leads ({leadsTotal})
                  </button>
                  <button
                    onClick={() => setActiveTab("events")}
                    className={`px-6 py-4 text-sm font-medium border-b-2 ${
                      activeTab === "events"
                        ? "border-blue-500 text-blue-600"
                        : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                    }`}
                  >
                    Events ({eventsTotal})
                  </button>
                </nav>
              </div>
              
              <div className="p-4">
                {activeTab === "leads" && (
                  <LeadsTable
                    leads={leads}
                    loading={loading}
                    total={leadsTotal}
                    skip={leadsSkip}
                    limit={limit}
                    onPageChange={(newSkip) => fetchLeads(newSkip)}
                    hideFlagged={hideFlaggedLeads}
                    onToggleHideFlagged={setHideFlaggedLeads}
                    hideDomainMismatch={hideDomainMismatch}
                    onToggleHideDomainMismatch={setHideDomainMismatch}
                    showOnlyVerified={showOnlyVerified}
                    onToggleShowOnlyVerified={setShowOnlyVerified}
                    showOnlyWithCode={showOnlyWithCode}
                    onToggleShowOnlyWithCode={setShowOnlyWithCode}
                  />
                )}
                {activeTab === "events" && (
                  <EventsTable
                    events={events}
                    loading={loading}
                    total={eventsTotal}
                    skip={eventsSkip}
                    limit={limit}
                    onPageChange={(newSkip) => fetchEvents(newSkip, selectedEventType)}
                    eventTypes={eventTypes}
                    selectedType={selectedEventType}
                    onTypeChange={handleEventTypeChange}
                  />
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
};

export default Dashboard;
