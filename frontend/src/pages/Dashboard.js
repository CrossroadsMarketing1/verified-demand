import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

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

// Leads Table Component
const LeadsTable = ({ leads, loading, total, skip, limit, onPageChange }) => {
  if (loading) {
    return <div className="text-center py-8 text-gray-500">Loading leads...</div>;
  }
  
  if (!leads.length) {
    return <div className="text-center py-8 text-gray-500">No leads found</div>;
  }
  
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date/Time</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Email</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Phone</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Vehicle</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {leads.map((lead, idx) => (
              <tr key={lead._id || idx} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap">
                  {lead.created_at ? new Date(lead.created_at).toLocaleString() : "-"}
                </td>
                <td className="px-4 py-3 text-sm text-gray-900">{lead.name || "-"}</td>
                <td className="px-4 py-3 text-sm text-gray-900">{lead.email || "-"}</td>
                <td className="px-4 py-3 text-sm text-gray-900">{lead.phone || "-"}</td>
                <td className="px-4 py-3 text-sm text-gray-900">
                  <span title={JSON.stringify(lead.vehicle, null, 2)}>
                    {formatVehicle(lead.vehicle)}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm">
                  {lead.source_url ? (
                    <a
                      href={lead.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-800 truncate block max-w-xs"
                      title={lead.source_url}
                    >
                      {new URL(lead.source_url).pathname || "/"}
                    </a>
                  ) : "-"}
                </td>
                <td className="px-4 py-3 text-sm">
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
  const [publicKey, setPublicKey] = useState("");
  const [inputKey, setInputKey] = useState("");
  const [dateRange, setDateRange] = useState("7d");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [activeTab, setActiveTab] = useState("leads");
  
  // Data state
  const [summary, setSummary] = useState(null);
  const [leads, setLeads] = useState([]);
  const [events, setEvents] = useState([]);
  const [eventTypes, setEventTypes] = useState([]);
  const [selectedEventType, setSelectedEventType] = useState("");
  
  // Pagination
  const [leadsSkip, setLeadsSkip] = useState(0);
  const [leadsTotal, setLeadsTotal] = useState(0);
  const [eventsSkip, setEventsSkip] = useState(0);
  const [eventsTotal, setEventsTotal] = useState(0);
  const limit = 50;
  
  // Loading/error state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
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
    setPublicKey(inputKey.trim());
    setLeadsSkip(0);
    setEventsSkip(0);
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
    setLeadsSkip(0);
    setEventsSkip(0);
  };
  
  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-6">
          <h1 className="text-2xl font-bold text-gray-900">VerifiedDemand Dashboard</h1>
        </div>
      </header>
      
      <main className="max-w-7xl mx-auto px-4 py-6">
        {/* Filters */}
        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <div className="flex flex-wrap gap-4 items-end">
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
