import { useState, useEffect, createContext, useContext, useCallback } from "react";
import "@/App.css";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Auth Context
const AuthContext = createContext(null);

const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
};

const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("token"));
  const [loading, setLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const response = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setUser(response.data);
    } catch (e) {
      localStorage.removeItem("token");
      setToken(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (email, password) => {
    const response = await axios.post(`${API}/auth/login`, { email, password });
    const { access_token, user } = response.data;
    localStorage.setItem("token", access_token);
    setToken(access_token);
    setUser(user);
    return user;
  };

  const register = async (email, password, firstName, lastName) => {
    const response = await axios.post(`${API}/auth/register`, {
      email, password, first_name: firstName, last_name: lastName
    });
    const { access_token, user } = response.data;
    localStorage.setItem("token", access_token);
    setToken(access_token);
    setUser(user);
    return user;
  };

  const logout = () => {
    localStorage.removeItem("token");
    setToken(null);
    setUser(null);
  };

  const resetPassword = async (email) => {
    const response = await axios.post(`${API}/auth/reset-password`, { email });
    return response.data;
  };

  const api = axios.create({ baseURL: API, headers: { Authorization: `Bearer ${token}` } });

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, resetPassword, api }}>
      {children}
    </AuthContext.Provider>
  );
};

// ============== Auth Components ==============
const LoginForm = ({ onSwitchToRegister, onForgotPassword }) => {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>Welcome back</h2>
        <p className="auth-subtitle">Sign in to your Verified Demand account</p>
        {error && <div className="error-message">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Email address</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@example.com" data-testid="login-email" />
          </div>
          <div className="form-group">
            <div className="label-row">
              <label>Password</label>
              <button type="button" className="link-button" onClick={onForgotPassword}>Forgot password?</button>
            </div>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="••••••••" data-testid="login-password" />
          </div>
          <button type="submit" className="btn-primary" disabled={loading} data-testid="login-submit">
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>
        <p className="auth-footer">
          Don't have an account? <button type="button" className="link-button" onClick={onSwitchToRegister}>Create account</button>
        </p>
      </div>
    </div>
  );
};

const RegisterForm = ({ onSwitchToLogin }) => {
  const { register } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register(email, password, firstName, lastName);
    } catch (err) {
      setError(err.response?.data?.detail || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>Create account</h2>
        <p className="auth-subtitle">Sign up to get started with Verified Demand</p>
        {error && <div className="error-message">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="form-group">
              <label>First name</label>
              <input type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder="John" data-testid="register-firstname" />
            </div>
            <div className="form-group">
              <label>Last name</label>
              <input type="text" value={lastName} onChange={(e) => setLastName(e.target.value)} placeholder="Doe" data-testid="register-lastname" />
            </div>
          </div>
          <div className="form-group">
            <label>Email address</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@example.com" data-testid="register-email" />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} placeholder="At least 8 characters" data-testid="register-password" />
          </div>
          <button type="submit" className="btn-primary" disabled={loading} data-testid="register-submit">
            {loading ? "Creating account..." : "Create account"}
          </button>
        </form>
        <p className="auth-footer">
          Already have an account? <button type="button" className="link-button" onClick={onSwitchToLogin}>Sign in</button>
        </p>
      </div>
    </div>
  );
};

const ForgotPasswordForm = ({ onBackToLogin }) => {
  const { resetPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const result = await resetPassword(email);
      setMessage(result.message);
    } catch (err) {
      setMessage("Error sending reset email");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>Reset password</h2>
        <p className="auth-subtitle">Enter your email to receive a reset link</p>
        {message && <div className="success-message">{message}</div>}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Email address</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@example.com" />
          </div>
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Sending..." : "Send reset link"}
          </button>
        </form>
        <p className="auth-footer">
          <button type="button" className="link-button" onClick={onBackToLogin}>← Back to sign in</button>
        </p>
      </div>
    </div>
  );
};

// ============== Dashboard Components ==============
const Sidebar = ({ currentPage, setCurrentPage }) => {
  const { logout, user } = useAuth();
  const navItems = [
    { id: "overview", label: "Overview", icon: "📊" },
    { id: "offers", label: "Offers", icon: "🎁" },
    { id: "leads", label: "Leads", icon: "👥" },
    { id: "analytics", label: "Analytics", icon: "📈" },
    { id: "settings", label: "Settings", icon: "⚙️" }
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>Verified Demand</h1>
      </div>
      <nav className="sidebar-nav">
        {navItems.map(item => (
          <button key={item.id} className={`nav-item ${currentPage === item.id ? "active" : ""}`} onClick={() => setCurrentPage(item.id)} data-testid={`nav-${item.id}`}>
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="user-info-small">{user?.email}</div>
        <button onClick={logout} className="logout-btn" data-testid="logout-button">Sign out</button>
      </div>
    </aside>
  );
};

const OverviewPage = () => {
  const { api } = useAuth();
  const [stats, setStats] = useState(null);
  const [recentActivity, setRecentActivity] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, activityRes] = await Promise.all([
          api.get("/analytics/overview"),
          api.get("/analytics/recent-activity?limit=10")
        ]);
        setStats(statsRes.data);
        setRecentActivity(activityRes.data);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [api]);

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div className="page" data-testid="overview-page">
      <h2>Overview</h2>
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{stats?.total_visitors || 0}</div>
          <div className="stat-label">Total Visitors</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats?.total_leads || 0}</div>
          <div className="stat-label">Total Leads</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats?.verified_leads || 0}</div>
          <div className="stat-label">Verified Leads</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats?.conversion_rate || 0}%</div>
          <div className="stat-label">Conversion Rate</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats?.active_offers || 0}</div>
          <div className="stat-label">Active Offers</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats?.total_pageviews || 0}</div>
          <div className="stat-label">Page Views</div>
        </div>
      </div>
      <div className="section">
        <h3>Recent Activity</h3>
        <div className="activity-list">
          {recentActivity.length === 0 ? (
            <p className="empty-state">No recent activity. Generate demo data from Settings.</p>
          ) : (
            recentActivity.map(event => (
              <div key={event.id} className="activity-item">
                <span className="activity-type">{event.event_type}</span>
                <span className="activity-url">{event.page_url}</span>
                <span className="activity-source">{event.utm_source || "direct"}</span>
                <span className="activity-time">{new Date(event.created_at).toLocaleString()}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

const OffersPage = () => {
  const { api } = useAuth();
  const [offers, setOffers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [newOffer, setNewOffer] = useState({ title: "", description: "", discount_percent: "" });

  const fetchOffers = useCallback(async () => {
    try {
      const res = await api.get("/offers");
      setOffers(res.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    fetchOffers();
  }, [fetchOffers]);

  const createOffer = async () => {
    try {
      await api.post("/offers", {
        title: newOffer.title,
        description: newOffer.description,
        discount_percent: newOffer.discount_percent ? parseFloat(newOffer.discount_percent) : null
      });
      setShowModal(false);
      setNewOffer({ title: "", description: "", discount_percent: "" });
      fetchOffers();
    } catch (e) {
      alert("Error creating offer");
    }
  };

  const toggleOffer = async (offer) => {
    try {
      await api.put(`/offers/${offer.id}`, { is_active: !offer.is_active });
      fetchOffers();
    } catch (e) {
      alert("Error updating offer");
    }
  };

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div className="page" data-testid="offers-page">
      <div className="page-header">
        <h2>Offers</h2>
        <button className="btn-primary" onClick={() => setShowModal(true)}>+ New Offer</button>
      </div>
      {offers.length === 0 ? (
        <div className="empty-state-box">
          <h3>No offers yet</h3>
          <p>Create your first offer to start capturing leads.</p>
        </div>
      ) : (
        <div className="offers-grid">
          {offers.map(offer => (
            <div key={offer.id} className={`offer-card ${!offer.is_active ? "inactive" : ""}`}>
              <div className="offer-header">
                <h3>{offer.title}</h3>
                <span className={`status-badge ${offer.is_active ? "active" : "inactive"}`}>
                  {offer.is_active ? "Active" : "Inactive"}
                </span>
              </div>
              <p className="offer-description">{offer.description}</p>
              {offer.discount_percent && <div className="offer-discount">{offer.discount_percent}% off</div>}
              <div className="offer-stats">
                <span>Code: {offer.discount_code}</span>
                <span>Redeemed: {offer.current_redemptions}/{offer.max_redemptions || "∞"}</span>
              </div>
              <div className="offer-actions">
                <button className="btn-secondary" onClick={() => toggleOffer(offer)}>
                  {offer.is_active ? "Deactivate" : "Activate"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {showModal && (
        <div className="modal-overlay">
          <div className="modal">
            <h3>Create New Offer</h3>
            <div className="form-group">
              <label>Title</label>
              <input type="text" value={newOffer.title} onChange={(e) => setNewOffer({ ...newOffer, title: e.target.value })} placeholder="e.g., Early Bird Special" />
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea value={newOffer.description} onChange={(e) => setNewOffer({ ...newOffer, description: e.target.value })} placeholder="Describe your offer..." />
            </div>
            <div className="form-group">
              <label>Discount Percent</label>
              <input type="number" value={newOffer.discount_percent} onChange={(e) => setNewOffer({ ...newOffer, discount_percent: e.target.value })} placeholder="e.g., 20" />
            </div>
            <div className="modal-actions">
              <button className="btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary" onClick={createOffer}>Create Offer</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const LeadsPage = () => {
  const { api } = useAuth();
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    const fetchLeads = async () => {
      try {
        const params = filter === "verified" ? "?is_verified=true" : filter === "unverified" ? "?is_verified=false" : "";
        const res = await api.get(`/leads${params}`);
        setLeads(res.data);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    fetchLeads();
  }, [api, filter]);

  const exportLeads = async () => {
    try {
      const res = await api.get("/leads/export", { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "leads.csv");
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (e) {
      alert("Error exporting leads");
    }
  };

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div className="page" data-testid="leads-page">
      <div className="page-header">
        <h2>Leads</h2>
        <div className="header-actions">
          <select value={filter} onChange={(e) => setFilter(e.target.value)} className="filter-select">
            <option value="all">All Leads</option>
            <option value="verified">Verified Only</option>
            <option value="unverified">Unverified Only</option>
          </select>
          <button className="btn-primary" onClick={exportLeads}>Export CSV</button>
        </div>
      </div>
      {leads.length === 0 ? (
        <div className="empty-state-box">
          <h3>No leads yet</h3>
          <p>Leads captured through your embed will appear here.</p>
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Name</th>
              <th>Source</th>
              <th>Campaign</th>
              <th>Verified</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {leads.map(lead => (
              <tr key={lead.id}>
                <td>{lead.email}</td>
                <td>{lead.name || "-"}</td>
                <td>{lead.utm_source || lead.source || "-"}</td>
                <td>{lead.utm_campaign || "-"}</td>
                <td><span className={`badge ${lead.is_verified ? "verified" : "unverified"}`}>{lead.is_verified ? "✓" : "○"}</span></td>
                <td>{new Date(lead.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

const AnalyticsPage = () => {
  const { api } = useAuth();
  const [sources, setSources] = useState([]);
  const [geography, setGeography] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [srcRes, geoRes, campRes] = await Promise.all([
          api.get("/analytics/sources"),
          api.get("/analytics/geography"),
          api.get("/analytics/utm-campaigns")
        ]);
        setSources(srcRes.data);
        setGeography(geoRes.data);
        setCampaigns(campRes.data);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [api]);

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div className="page" data-testid="analytics-page">
      <h2>Analytics</h2>
      <div className="analytics-grid">
        <div className="analytics-card">
          <h3>Traffic Sources</h3>
          {sources.length === 0 ? <p className="empty-text">No data yet</p> : (
            <div className="bar-list">
              {sources.map(s => (
                <div key={s.source} className="bar-item">
                  <span className="bar-label">{s.source}</span>
                  <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, s.count * 2)}%` }}></div></div>
                  <span className="bar-value">{s.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="analytics-card">
          <h3>Geography</h3>
          {geography.length === 0 ? <p className="empty-text">No data yet</p> : (
            <div className="bar-list">
              {geography.map(g => (
                <div key={g.country} className="bar-item">
                  <span className="bar-label">{g.country}</span>
                  <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, g.count * 2)}%` }}></div></div>
                  <span className="bar-value">{g.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="analytics-card">
          <h3>UTM Campaigns</h3>
          {campaigns.length === 0 ? <p className="empty-text">No data yet</p> : (
            <div className="bar-list">
              {campaigns.map(c => (
                <div key={c.campaign} className="bar-item">
                  <span className="bar-label">{c.campaign}</span>
                  <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, c.count * 2)}%` }}></div></div>
                  <span className="bar-value">{c.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const SettingsPage = () => {
  const { api } = useAuth();
  const [business, setBusiness] = useState(null);
  const [offers, setOffers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [bizRes, offersRes] = await Promise.all([
          api.get("/settings/business"),
          api.get("/offers")
        ]);
        setBusiness(bizRes.data);
        setOffers(offersRes.data.filter(o => o.is_active));
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [api]);

  const generateDemoData = async () => {
    setGenerating(true);
    try {
      await api.post("/demo/generate");
      alert("Demo data generated! Refresh to see the data.");
      window.location.reload();
    } catch (e) {
      alert("Error generating demo data");
    } finally {
      setGenerating(false);
    }
  };

  if (loading) return <div className="loading">Loading...</div>;

  const embedSnippet = `<script 
  src="${BACKEND_URL}/embed.js" 
  data-public-key="${business?.public_key}" 
  data-offer-id="${offers[0]?.id || 'YOUR_OFFER_ID'}">
</script>

<!-- Add this to any element to trigger the modal -->
<button data-vd-trigger>Get Your Offer</button>`;

  return (
    <div className="page" data-testid="settings-page">
      <h2>Settings</h2>
      <div className="settings-section">
        <h3>Business Info</h3>
        <div className="setting-item">
          <label>Business Name</label>
          <div className="setting-value">{business?.name}</div>
        </div>
        <div className="setting-item">
          <label>Public Key</label>
          <div className="setting-value code">{business?.public_key}</div>
        </div>
      </div>
      <div className="settings-section">
        <h3>Embed Script</h3>
        <p className="section-description">Add this script to your website to enable lead capture. The modal opens when users click any element with <code>data-vd-trigger</code>.</p>
        <pre className="code-block">{embedSnippet}</pre>
        <button className="btn-secondary" onClick={() => navigator.clipboard.writeText(embedSnippet)}>Copy to Clipboard</button>
      </div>
      <div className="settings-section">
        <h3>Demo Data</h3>
        <p className="section-description">Generate sample data to test the dashboard features.</p>
        <button className="btn-primary" onClick={generateDemoData} disabled={generating} data-testid="generate-demo-btn">
          {generating ? "Generating..." : "Generate Demo Data"}
        </button>
      </div>
    </div>
  );
};

const Dashboard = () => {
  const [currentPage, setCurrentPage] = useState("overview");

  const renderPage = () => {
    switch (currentPage) {
      case "overview": return <OverviewPage />;
      case "offers": return <OffersPage />;
      case "leads": return <LeadsPage />;
      case "analytics": return <AnalyticsPage />;
      case "settings": return <SettingsPage />;
      default: return <OverviewPage />;
    }
  };

  return (
    <div className="dashboard-layout" data-testid="dashboard">
      <Sidebar currentPage={currentPage} setCurrentPage={setCurrentPage} />
      <main className="main-content">{renderPage()}</main>
    </div>
  );
};

// ============== Main App ==============
function App() {
  const [view, setView] = useState("login");

  return (
    <AuthProvider>
      <AppContent view={view} setView={setView} />
    </AuthProvider>
  );
}

function AppContent({ view, setView }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading...</p>
      </div>
    );
  }

  if (user) return <Dashboard />;

  return (
    <div className="App">
      {view === "login" && <LoginForm onSwitchToRegister={() => setView("register")} onForgotPassword={() => setView("forgot")} />}
      {view === "register" && <RegisterForm onSwitchToLogin={() => setView("login")} />}
      {view === "forgot" && <ForgotPasswordForm onBackToLogin={() => setView("login")} />}
    </div>
  );
}

export default App;
