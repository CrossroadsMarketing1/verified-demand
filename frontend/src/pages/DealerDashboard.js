import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Configure axios to send cookies
axios.defaults.withCredentials = true;

// Lead status options
const LEAD_STATUSES = [
  { value: "new", label: "New", color: "bg-blue-100 text-blue-800" },
  { value: "attempted", label: "Attempted", color: "bg-yellow-100 text-yellow-800" },
  { value: "contacted", label: "Contacted", color: "bg-purple-100 text-purple-800" },
  { value: "appt_set", label: "Appt Set", color: "bg-green-100 text-green-800" },
  { value: "sold", label: "Sold", color: "bg-emerald-100 text-emerald-800" },
  { value: "lost", label: "Lost", color: "bg-gray-100 text-gray-800" },
];

const DATE_RANGES = {
  "today": { label: "Today", days: 0 },
  "7d": { label: "7 Days", days: 7 },
  "30d": { label: "30 Days", days: 30 },
  "all": { label: "All Time", days: null }
};

// KPI Card Component
const KPICard = ({ title, value, loading, icon, highlight }) => (
  <div className={`rounded-lg shadow px-4 py-3 border ${highlight ? 'bg-blue-50 border-blue-200' : 'bg-white border-gray-200'}`}>
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{title}</p>
        <p className={`text-2xl font-bold ${highlight ? 'text-blue-600' : 'text-gray-900'} mt-0.5`}>
          {loading ? "..." : (value ?? 0).toLocaleString()}
        </p>
      </div>
      <span className="text-2xl">{icon}</span>
    </div>
  </div>
);

// Verified Badge
const VerifiedBadge = ({ verified }) => {
  if (verified) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-800" title="Phone verified">
        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
        </svg>
        Verified
      </span>
    );
  }
  return null;
};

// Copy Button Component
const CopyButton = ({ text, label }) => {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = async (e) => {
    e.stopPropagation();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.error("Copy failed:", err);
    }
  };
  
  if (!text) return <span className="text-gray-400">—</span>;
  
  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 hover:bg-gray-100 px-1 rounded transition-colors group"
      title={`Click to copy ${label || ''}`}
    >
      <span className="font-mono text-sm">{text}</span>
      <svg className={`w-4 h-4 ${copied ? 'text-green-500' : 'text-gray-400 group-hover:text-gray-600'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
        {copied ? (
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        ) : (
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
        )}
      </svg>
    </button>
  );
};

// Status Badge/Dropdown Component
const StatusBadge = ({ status, onChange, disabled }) => {
  const [isOpen, setIsOpen] = useState(false);
  const currentStatus = LEAD_STATUSES.find(s => s.value === status) || LEAD_STATUSES[0];
  
  if (disabled) {
    return (
      <span className={`px-2 py-1 text-xs font-medium rounded-full ${currentStatus.color}`}>
        {currentStatus.label}
      </span>
    );
  }
  
  return (
    <div className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setIsOpen(!isOpen); }}
        className={`px-2 py-1 text-xs font-medium rounded-full ${currentStatus.color} hover:opacity-80 transition-opacity flex items-center gap-1`}
      >
        {currentStatus.label}
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-1 w-32 bg-white rounded-lg shadow-lg border border-gray-200 z-20 py-1">
            {LEAD_STATUSES.map((s) => (
              <button
                key={s.value}
                onClick={(e) => {
                  e.stopPropagation();
                  onChange(s.value);
                  setIsOpen(false);
                }}
                className={`w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 ${status === s.value ? 'font-medium' : ''}`}
              >
                <span className={`inline-block w-2 h-2 rounded-full mr-2 ${s.color.replace('text-', 'bg-').split(' ')[0]}`} />
                {s.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

// Lead Detail Drawer Component
const LeadDetailDrawer = ({ lead, onClose, onUpdate, currentUser }) => {
  const [note, setNote] = useState("");
  const [nextAction, setNextAction] = useState(lead?.next_action_at ? lead.next_action_at.slice(0, 16) : "");
  const [saving, setSaving] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  
  if (!lead) return null;
  
  const handleSaveNote = async () => {
    if (!note.trim()) return;
    setSaving(true);
    try {
      const payload = { note: note.trim() };
      if (nextAction) {
        payload.next_action_at = new Date(nextAction).toISOString();
      }
      const response = await axios.patch(`${API}/dashboard/leads/${lead.id}`, payload);
      onUpdate(response.data);
      setNote("");
    } catch (err) {
      console.error("Error saving note:", err);
      alert("Failed to save note");
    } finally {
      setSaving(false);
    }
  };
  
  const handleStatusChange = async (newStatus) => {
    try {
      const response = await axios.patch(`${API}/dashboard/leads/${lead.id}`, { status: newStatus });
      onUpdate(response.data);
    } catch (err) {
      console.error("Error updating status:", err);
      alert("Failed to update status");
    }
  };
  
  const handleQuickAction = async (action) => {
    try {
      const payload = { status: action };
      if (action === "contacted" || action === "attempted") {
        payload.last_contacted_at = new Date().toISOString();
      }
      const response = await axios.patch(`${API}/dashboard/leads/${lead.id}`, payload);
      onUpdate(response.data);
    } catch (err) {
      console.error("Error:", err);
      alert("Failed to update");
    }
  };
  
  const formatDateTime = (iso) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleString();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div 
        className="relative w-full max-w-lg bg-white h-full overflow-y-auto shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{lead.name || "Unknown"}</h2>
            <div className="flex items-center gap-2 mt-1">
              <VerifiedBadge verified={lead.is_verified} />
              <StatusBadge status={lead.status} onChange={handleStatusChange} />
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded-full">
            <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        
        <div className="px-6 py-4 space-y-6">
          {/* Quick Actions */}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => handleQuickAction("attempted")}
              className="px-3 py-1.5 text-sm bg-yellow-100 text-yellow-800 rounded-full hover:bg-yellow-200 transition-colors"
              data-testid="quick-attempted"
            >
              📞 Attempted
            </button>
            <button
              onClick={() => handleQuickAction("contacted")}
              className="px-3 py-1.5 text-sm bg-purple-100 text-purple-800 rounded-full hover:bg-purple-200 transition-colors"
              data-testid="quick-contacted"
            >
              ✅ Contacted
            </button>
            <button
              onClick={() => handleQuickAction("appt_set")}
              className="px-3 py-1.5 text-sm bg-green-100 text-green-800 rounded-full hover:bg-green-200 transition-colors"
              data-testid="quick-appt"
            >
              📅 Appt Set
            </button>
          </div>
          
          {/* Contact Info */}
          <div className="bg-gray-50 rounded-lg p-4 space-y-3">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Contact Info</h3>
            
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-500">Phone</label>
                <CopyButton text={lead.phone} label="phone" />
              </div>
              <div>
                <label className="text-xs text-gray-500">Email</label>
                <CopyButton text={lead.email} label="email" />
              </div>
            </div>
            
            <div>
              <label className="text-xs text-gray-500">Confirmation Code</label>
              <div className="mt-0.5">
                {lead.unlock_code ? (
                  <span className="inline-flex items-center gap-2 px-2 py-1 bg-sky-50 border border-sky-200 rounded">
                    <code className="text-sky-700 font-mono font-bold">{lead.unlock_code}</code>
                    <CopyButton text={lead.unlock_code} label="code" />
                  </span>
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </div>
            </div>
          </div>
          
          {/* Vehicle Info */}
          {lead.vehicle_summary && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Vehicle Interest</h3>
              <p className="mt-1 text-gray-900">{lead.vehicle_summary}</p>
            </div>
          )}
          
          {/* Timestamps */}
          <div className="bg-gray-50 rounded-lg p-4 space-y-2">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Timeline</h3>
            <div className="text-sm space-y-1">
              <div className="flex justify-between">
                <span className="text-gray-500">Created</span>
                <span className="text-gray-900">{formatDateTime(lead.created_at)}</span>
              </div>
              {lead.verified_at && (
                <div className="flex justify-between">
                  <span className="text-gray-500">Verified</span>
                  <span className="text-gray-900">{formatDateTime(lead.verified_at)}</span>
                </div>
              )}
              {lead.last_contacted_at && (
                <div className="flex justify-between">
                  <span className="text-gray-500">Last Contacted</span>
                  <span className="text-gray-900">{formatDateTime(lead.last_contacted_at)}</span>
                </div>
              )}
              {lead.next_action_at && (
                <div className="flex justify-between">
                  <span className="text-gray-500">Follow-up</span>
                  <span className="text-orange-600 font-medium">{formatDateTime(lead.next_action_at)}</span>
                </div>
              )}
            </div>
          </div>
          
          {/* Notes Timeline */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Notes</h3>
            
            {/* Add Note Form */}
            <div className="mb-4">
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Add a note..."
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                data-testid="note-input"
              />
              <div className="flex items-center gap-2 mt-2">
                <input
                  type="datetime-local"
                  value={nextAction}
                  onChange={(e) => setNextAction(e.target.value)}
                  className="flex-1 px-3 py-1.5 border border-gray-300 rounded text-sm"
                  placeholder="Set follow-up"
                  data-testid="followup-input"
                />
                <button
                  onClick={handleSaveNote}
                  disabled={saving || !note.trim()}
                  className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  data-testid="save-note-btn"
                >
                  {saving ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
            
            {/* Notes List */}
            <div className="space-y-3">
              {(lead.notes || []).length === 0 ? (
                <p className="text-sm text-gray-500 italic">No notes yet.</p>
              ) : (
                [...(lead.notes || [])].reverse().map((n, i) => (
                  <div key={i} className="bg-white border border-gray-200 rounded-lg p-3">
                    <p className="text-sm text-gray-900">{n.text}</p>
                    <p className="text-xs text-gray-500 mt-1">
                      {n.user_email || "System"} • {formatDateTime(n.created_at)}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
          
          {/* Advanced/Raw Data */}
          <div>
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              {showAdvanced ? "▼ Hide Advanced" : "▶ Show Advanced"}
            </button>
            {showAdvanced && (
              <pre className="mt-2 p-3 bg-gray-100 rounded text-xs overflow-auto max-h-48">
                {JSON.stringify(lead, null, 2)}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// Main Dealer Dashboard Component
const DealerDashboard = () => {
  const [sites, setSites] = useState([]);
  const [selectedSiteKey, setSelectedSiteKey] = useState("");
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [stats, setStats] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [selectedLead, setSelectedLead] = useState(null);
  
  // Filters
  const [dateRange, setDateRange] = useState("7d");
  const [statusFilter, setStatusFilter] = useState("new");
  const [verifiedOnly, setVerifiedOnly] = useState(true);
  const [hasCodeOnly, setHasCodeOnly] = useState(false);
  const [hideMismatch, setHideMismatch] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  
  // Fetch current user
  useEffect(() => {
    const fetchUser = async () => {
      try {
        const response = await axios.get(`${API}/auth/me`);
        if (response.data.ok) {
          setCurrentUser(response.data.user);
        }
      } catch (e) {
        console.error("Failed to fetch user:", e);
      }
    };
    fetchUser();
  }, []);
  
  // Fetch sites
  useEffect(() => {
    const fetchSites = async () => {
      try {
        const response = await axios.get(`${API}/dashboard/sites`);
        const siteList = response.data.sites || [];
        setSites(siteList);
        if (siteList.length > 0 && !selectedSiteKey) {
          setSelectedSiteKey(siteList[0].public_key);
        }
      } catch (e) {
        console.error("Failed to fetch sites:", e);
      } finally {
        setLoading(false);
      }
    };
    fetchSites();
  }, [selectedSiteKey]);
  
  // Fetch stats when site changes
  useEffect(() => {
    if (!selectedSiteKey) return;
    
    const fetchStats = async () => {
      try {
        const response = await axios.get(`${API}/dashboard/leads/queue/stats`, {
          params: { public_key: selectedSiteKey }
        });
        setStats(response.data);
      } catch (e) {
        console.error("Failed to fetch stats:", e);
      }
    };
    fetchStats();
  }, [selectedSiteKey]);
  
  // Fetch leads
  const fetchLeads = useCallback(async () => {
    if (!selectedSiteKey) return;
    
    setLoadingLeads(true);
    try {
      const params = {
        public_key: selectedSiteKey,
        verified_only: verifiedOnly,
        status: statusFilter,
        has_code_only: hasCodeOnly,
        hide_mismatch: hideMismatch,
        page,
        page_size: 50
      };
      
      if (searchQuery) {
        params.q = searchQuery;
      }
      
      if (dateRange !== "all") {
        const now = new Date();
        const days = DATE_RANGES[dateRange]?.days ?? 7;
        if (days === 0) {
          // Today
          params.date_from = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
        } else {
          params.date_from = new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString();
        }
        params.date_to = now.toISOString();
      }
      
      const response = await axios.get(`${API}/dashboard/leads/queue`, { params });
      setLeads(response.data.leads || []);
      setTotalPages(response.data.total_pages || 1);
      setTotal(response.data.total || 0);
    } catch (e) {
      console.error("Failed to fetch leads:", e);
      setLeads([]);
    } finally {
      setLoadingLeads(false);
    }
  }, [selectedSiteKey, verifiedOnly, statusFilter, hasCodeOnly, hideMismatch, searchQuery, dateRange, page]);
  
  useEffect(() => {
    fetchLeads();
  }, [fetchLeads]);
  
  // Handle lead update
  const handleLeadUpdate = (updatedLead) => {
    setLeads(leads.map(l => l.id === updatedLead.id ? updatedLead : l));
    setSelectedLead(updatedLead);
    // Refresh stats
    if (selectedSiteKey) {
      axios.get(`${API}/dashboard/leads/queue/stats`, {
        params: { public_key: selectedSiteKey }
      }).then(r => setStats(r.data)).catch(() => {});
    }
  };
  
  // Inline status update
  const handleInlineStatusChange = async (leadId, newStatus) => {
    try {
      const response = await axios.patch(`${API}/dashboard/leads/${leadId}`, { status: newStatus });
      handleLeadUpdate(response.data);
    } catch (err) {
      console.error("Error updating status:", err);
      alert("Failed to update status");
    }
  };
  
  const formatTime = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };
  
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600"></div>
      </div>
    );
  }
  
  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-3">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-gray-900">Call Queue</h1>
              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs font-medium rounded">v2</span>
            </div>
            
            <div className="flex flex-wrap items-center gap-2">
              {/* Site Selector */}
              <select
                value={selectedSiteKey}
                onChange={(e) => { setSelectedSiteKey(e.target.value); setPage(1); }}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm bg-white focus:ring-2 focus:ring-blue-500"
                data-testid="site-selector"
              >
                {sites.map((site) => (
                  <option key={site.public_key} value={site.public_key}>
                    {site.name}
                  </option>
                ))}
              </select>
              
              {/* Date Range */}
              <select
                value={dateRange}
                onChange={(e) => { setDateRange(e.target.value); setPage(1); }}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm bg-white"
                data-testid="date-range"
              >
                {Object.entries(DATE_RANGES).map(([key, { label }]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
              
              {/* Search */}
              <div className="relative">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
                  placeholder="Search name/phone/code..."
                  className="pl-8 pr-3 py-1.5 border border-gray-300 rounded-lg text-sm w-48 focus:ring-2 focus:ring-blue-500"
                  data-testid="search-input"
                />
                <svg className="w-4 h-4 text-gray-400 absolute left-2.5 top-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>
              
              {/* Nav Links */}
              <Link
                to="/dashboard"
                className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg"
              >
                Analytics
              </Link>
              <Link
                to="/dashboard/sites"
                className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg"
              >
                Sites
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
                className="px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 rounded-lg"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </header>
      
      <main className="max-w-7xl mx-auto px-4 py-4">
        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
          <KPICard 
            title="New Today" 
            value={stats?.new_verified_today} 
            loading={!stats} 
            icon="🆕"
            highlight
          />
          <KPICard 
            title="Contacted Today" 
            value={stats?.contacted_today} 
            loading={!stats} 
            icon="📞"
          />
          <KPICard 
            title="Appts (7d)" 
            value={stats?.appts_set_7d} 
            loading={!stats} 
            icon="📅"
          />
          <KPICard 
            title="Verified (7d)" 
            value={stats?.total_verified_7d} 
            loading={!stats} 
            icon="✅"
          />
          <KPICard 
            title="Need Follow-up" 
            value={stats?.needs_followup} 
            loading={!stats} 
            icon="⏰"
            highlight={stats?.needs_followup > 0}
          />
        </div>
        
        {/* Filters Row */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 px-4 py-3 mb-4">
          <div className="flex flex-wrap items-center gap-4">
            {/* Status Filter */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500">Status:</span>
              <select
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
                className="px-2 py-1 border border-gray-300 rounded text-sm"
                data-testid="status-filter"
              >
                <option value="all">All</option>
                {LEAD_STATUSES.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            
            {/* Toggle Filters */}
            <label className="flex items-center gap-1.5 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={verifiedOnly}
                onChange={(e) => { setVerifiedOnly(e.target.checked); setPage(1); }}
                className="rounded text-blue-600 focus:ring-blue-500"
              />
              <span>Verified only</span>
            </label>
            
            <label className="flex items-center gap-1.5 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={hasCodeOnly}
                onChange={(e) => { setHasCodeOnly(e.target.checked); setPage(1); }}
                className="rounded text-blue-600 focus:ring-blue-500"
              />
              <span>Has code</span>
            </label>
            
            <label className="flex items-center gap-1.5 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={hideMismatch}
                onChange={(e) => { setHideMismatch(e.target.checked); setPage(1); }}
                className="rounded text-blue-600 focus:ring-blue-500"
              />
              <span>Hide mismatches</span>
            </label>
            
            <div className="ml-auto text-sm text-gray-500">
              {total} leads found
            </div>
          </div>
        </div>
        
        {/* Queue Table */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          {loadingLeads ? (
            <div className="p-8 text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
              <p className="mt-2 text-gray-500 text-sm">Loading leads...</p>
            </div>
          ) : leads.length === 0 ? (
            <div className="p-12 text-center">
              <div className="text-4xl mb-3">📭</div>
              <h3 className="text-lg font-medium text-gray-900">No leads found</h3>
              <p className="text-gray-500 text-sm mt-1">Try adjusting your filters or date range.</p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Phone</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Code</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Vehicle</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Follow-up</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {leads.map((lead) => (
                      <tr 
                        key={lead.id} 
                        className="hover:bg-blue-50 cursor-pointer transition-colors"
                        onClick={() => setSelectedLead(lead)}
                        data-testid={`lead-row-${lead.id}`}
                      >
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                          {formatTime(lead.created_at)}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-900">{lead.name || "Unknown"}</span>
                            {lead.is_verified && (
                              <svg className="w-4 h-4 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                              </svg>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                          <CopyButton text={lead.phone} label="phone" />
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                          {lead.unlock_code ? (
                            <CopyButton text={lead.unlock_code} label="code" />
                          ) : (
                            <span className="text-gray-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600 max-w-[200px] truncate" title={lead.vehicle_summary}>
                          {lead.vehicle_summary || "—"}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                          <StatusBadge 
                            status={lead.status} 
                            onChange={(s) => handleInlineStatusChange(lead.id, s)}
                          />
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm">
                          {lead.next_action_at ? (
                            <span className={`${new Date(lead.next_action_at) <= new Date() ? 'text-red-600 font-medium' : 'text-orange-600'}`}>
                              {formatTime(lead.next_action_at)}
                            </span>
                          ) : (
                            <span className="text-gray-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-right">
                          <button
                            onClick={(e) => { e.stopPropagation(); setSelectedLead(lead); }}
                            className="text-blue-600 hover:text-blue-800 text-sm font-medium"
                            data-testid={`view-lead-${lead.id}`}
                          >
                            Details
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              
              {/* Pagination */}
              {totalPages > 1 && (
                <div className="px-4 py-3 border-t border-gray-200 flex items-center justify-between">
                  <p className="text-sm text-gray-500">
                    Page {page} of {totalPages}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setPage(Math.max(1, page - 1))}
                      disabled={page === 1}
                      className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
                    >
                      Previous
                    </button>
                    <button
                      onClick={() => setPage(Math.min(totalPages, page + 1))}
                      disabled={page === totalPages}
                      className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </main>
      
      {/* Lead Detail Drawer */}
      {selectedLead && (
        <LeadDetailDrawer
          lead={selectedLead}
          onClose={() => setSelectedLead(null)}
          onUpdate={handleLeadUpdate}
          currentUser={currentUser}
        />
      )}
    </div>
  );
};

export default DealerDashboard;
