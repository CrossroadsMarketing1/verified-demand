import { useState, useEffect, createContext, useContext, useCallback, useRef } from "react";
import "@/App.css";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// ============== Toast Context with Deduplication ==============
const ToastContext = createContext(null);

const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
};

const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);
  const lastToastRef = useRef({});

  const addToast = useCallback((message, type = "success", key = null) => {
    // Deduplicate: if same key shown in last 3 seconds, skip
    const toastKey = key || `${type}_${message}`;
    const now = Date.now();
    if (lastToastRef.current[toastKey] && now - lastToastRef.current[toastKey] < 3000) {
      return; // Skip duplicate
    }
    lastToastRef.current[toastKey] = now;

    const id = now;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4000);
  }, []);

  const success = useCallback((message, key) => addToast(message, "success", key), [addToast]);
  const error = useCallback((message, key) => addToast(message, "error", key), [addToast]);
  const info = useCallback((message, key) => addToast(message, "info", key), [addToast]);

  const clearDuplicateKey = useCallback((key) => {
    delete lastToastRef.current[key];
  }, []);

  return (
    <ToastContext.Provider value={{ success, error, info, clearDuplicateKey }}>
      {children}
      <div className="toast-container">
        {toasts.map(toast => (
          <div key={toast.id} className={`toast toast-${toast.type}`}>
            {toast.type === "success" && "✓ "}
            {toast.type === "error" && "✗ "}
            {toast.type === "info" && "ℹ "}
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

// ============== Auth Context with API Helper ==============
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

  // Create stable API instance
  const apiFetch = useCallback(async (endpoint, options = {}) => {
    const currentToken = localStorage.getItem("token");
    const config = {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(currentToken ? { Authorization: `Bearer ${currentToken}` } : {}),
        ...options.headers,
      },
    };

    try {
      const response = await axios({
        url: `${API}${endpoint}`,
        ...config,
      });
      return response;
    } catch (err) {
      if (err.response?.status === 401 || err.response?.status === 403) {
        // Session expired
        localStorage.removeItem("token");
        setToken(null);
        setUser(null);
      }
      throw err;
    }
  }, []);

  const fetchUser = useCallback(async () => {
    const currentToken = localStorage.getItem("token");
    if (!currentToken) {
      setLoading(false);
      return;
    }
    try {
      const response = await apiFetch("/auth/me", { method: "GET" });
      setUser(response.data);
    } catch (e) {
      localStorage.removeItem("token");
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (email, password) => {
    const response = await axios.post(`${API}/auth/login`, { email, password });
    const { access_token, user: userData } = response.data;
    localStorage.setItem("token", access_token);
    setToken(access_token);
    setUser(userData);
    return userData;
  };

  const register = async (email, password, firstName, lastName) => {
    const response = await axios.post(`${API}/auth/register`, {
      email, password, first_name: firstName, last_name: lastName
    });
    const { access_token, user: userData } = response.data;
    localStorage.setItem("token", access_token);
    setToken(access_token);
    setUser(userData);
    return userData;
  };

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    setToken(null);
    setUser(null);
  }, []);

  const resetPassword = async (email) => {
    const response = await axios.post(`${API}/auth/reset-password`, { email });
    return response.data;
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, resetPassword, apiFetch }}>
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
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err.response?.data?.detail || "Login failed");
    } finally {
      setIsLoading(false);
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
          <button type="submit" className="btn-primary" disabled={isLoading} data-testid="login-submit">
            {isLoading ? "Signing in..." : "Sign in"}
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
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await register(email, password, firstName, lastName);
    } catch (err) {
      setError(err.response?.data?.detail || "Registration failed");
    } finally {
      setIsLoading(false);
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
          <button type="submit" className="btn-primary" disabled={isLoading} data-testid="register-submit">
            {isLoading ? "Creating account..." : "Create account"}
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
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      const result = await resetPassword(email);
      setMessage(result.message);
    } catch (err) {
      setMessage("Error sending reset email");
    } finally {
      setIsLoading(false);
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
          <button type="submit" className="btn-primary" disabled={isLoading}>
            {isLoading ? "Sending..." : "Send reset link"}
          </button>
        </form>
        <p className="auth-footer">
          <button type="button" className="link-button" onClick={onBackToLogin}>← Back to sign in</button>
        </p>
      </div>
    </div>
  );
};

// ============== Confirmation Dialog ==============
const ConfirmDialog = ({ isOpen, title, message, confirmLabel, onConfirm, onCancel, isDestructive }) => {
  if (!isOpen) return null;
  
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal confirm-dialog" onClick={e => e.stopPropagation()}>
        <h3>{title}</h3>
        <p className="confirm-message">{message}</p>
        <div className="modal-actions">
          <button className="btn-secondary" onClick={onCancel}>Cancel</button>
          <button className={isDestructive ? "btn-danger" : "btn-primary"} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
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
        <img 
          src="/verified-demand-logo.png" 
          alt="Verified Demand" 
          className="sidebar-logo"
        />
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
  const { apiFetch } = useAuth();
  const toast = useToast();
  const [stats, setStats] = useState(null);
  const [recentActivity, setRecentActivity] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const errorShownRef = useRef(false);

  useEffect(() => {
    let isMounted = true;
    
    const fetchData = async () => {
      try {
        const [statsRes, activityRes] = await Promise.all([
          apiFetch("/analytics/overview", { method: "GET" }),
          apiFetch("/analytics/recent-activity?limit=10", { method: "GET" })
        ]);
        if (isMounted) {
          setStats(statsRes.data);
          setRecentActivity(activityRes.data);
          setIsLoading(false);
        }
      } catch (e) {
        if (isMounted) {
          console.error(e);
          setIsLoading(false);
          if (!errorShownRef.current) {
            errorShownRef.current = true;
            toast.error("Failed to load overview", "load_overview");
          }
        }
      }
    };
    
    fetchData();
    return () => { isMounted = false; };
  }, [apiFetch, toast]);

  if (isLoading) return <div className="loading">Loading...</div>;

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

// ============== OFFERS PAGE - FIXED ==============
const OffersPage = () => {
  const { apiFetch } = useAuth();
  const toast = useToast();
  const [offers, setOffers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [selectedOffer, setSelectedOffer] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [formData, setFormData] = useState({ 
    title: "", 
    description: "", 
    discount_percent: "",
    discount_code: "",
    is_active: true
  });
  
  // Ref to track if error toast was shown (to prevent spam)
  const loadErrorShownRef = useRef(false);

  // Fetch offers on mount
  useEffect(() => {
    let isMounted = true;
    
    const loadOffers = async () => {
      try {
        const res = await apiFetch("/offers", { method: "GET" });
        if (isMounted) {
          setOffers(res.data);
          setIsLoading(false);
          loadErrorShownRef.current = false;
        }
      } catch (e) {
        if (isMounted) {
          console.error("Failed to load offers:", e);
          setIsLoading(false);
          // Only show error toast once per mount
          if (!loadErrorShownRef.current) {
            loadErrorShownRef.current = true;
            toast.error("Failed to load offers", "load_offers_error");
          }
        }
      }
    };
    
    loadOffers();
    
    return () => {
      isMounted = false;
    };
  }, [apiFetch, toast]);

  // Manual refresh function (for after create/edit/delete)
  const refreshOffers = async () => {
    try {
      const res = await apiFetch("/offers", { method: "GET" });
      setOffers(res.data);
      loadErrorShownRef.current = false;
    } catch (e) {
      console.error("Failed to refresh offers:", e);
    }
  };

  const resetForm = () => {
    setFormData({ title: "", description: "", discount_percent: "", discount_code: "", is_active: true });
  };

  // CREATE
  const createOffer = async () => {
    if (isSaving) return;
    setIsSaving(true);
    try {
      await apiFetch("/offers", {
        method: "POST",
        data: {
          title: formData.title,
          description: formData.description,
          discount_percent: formData.discount_percent ? parseFloat(formData.discount_percent) : null,
          discount_code: formData.discount_code || undefined
        }
      });
      setShowCreateModal(false);
      resetForm();
      await refreshOffers();
      toast.success("Offer created successfully");
    } catch (e) {
      toast.error("Error creating offer");
    } finally {
      setIsSaving(false);
    }
  };

  // EDIT
  const openEditModal = (offer) => {
    setSelectedOffer(offer);
    setFormData({
      title: offer.title || "",
      description: offer.description || "",
      discount_percent: offer.discount_percent ? String(offer.discount_percent) : "",
      discount_code: offer.discount_code || "",
      is_active: offer.is_active
    });
    setShowEditModal(true);
  };

  const updateOffer = async () => {
    if (!selectedOffer || isSaving) return;
    setIsSaving(true);
    try {
      await apiFetch(`/offers/${selectedOffer.id}`, {
        method: "PUT",
        data: {
          title: formData.title,
          description: formData.description,
          discount_percent: formData.discount_percent ? parseFloat(formData.discount_percent) : null,
          is_active: formData.is_active
        }
      });
      setShowEditModal(false);
      setSelectedOffer(null);
      resetForm();
      await refreshOffers();
      toast.success("Offer updated successfully");
    } catch (e) {
      toast.error("Error updating offer");
    } finally {
      setIsSaving(false);
    }
  };

  // DELETE
  const openDeleteConfirm = (offer) => {
    setSelectedOffer(offer);
    setShowDeleteConfirm(true);
  };

  const deleteOffer = async () => {
    if (!selectedOffer || isSaving) return;
    setIsSaving(true);
    try {
      await apiFetch(`/offers/${selectedOffer.id}`, { method: "DELETE" });
      setShowDeleteConfirm(false);
      // Immediately remove from list (optimistic update)
      setOffers(prev => prev.filter(o => o.id !== selectedOffer.id));
      setSelectedOffer(null);
      toast.success("Offer deleted successfully");
    } catch (e) {
      toast.error("Error deleting offer");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) return <div className="loading">Loading...</div>;

  return (
    <div className="page" data-testid="offers-page">
      <div className="page-header">
        <h2>Offers</h2>
        <button className="btn-primary" onClick={() => { resetForm(); setShowCreateModal(true); }}>+ New Offer</button>
      </div>
      
      {offers.length === 0 ? (
        <div className="empty-state-box">
          <h3>No offers yet</h3>
          <p>Create your first offer to start capturing leads.</p>
        </div>
      ) : (
        <div className="offers-grid">
          {offers.map(offer => (
            <div key={offer.id} className={`offer-card ${!offer.is_active ? "inactive" : ""}`} data-testid={`offer-card-${offer.id}`}>
              <div className="offer-header">
                <h3>{offer.title}</h3>
                <span className={`status-badge ${offer.is_active ? "active" : "inactive"}`}>
                  {offer.is_active ? "Active" : "Inactive"}
                </span>
              </div>
              <p className="offer-description">{offer.description}</p>
              {offer.discount_percent && (
                <div className="offer-discount">{offer.discount_percent}% off</div>
              )}
              <div className="offer-stats">
                <span>Code: <code>{offer.discount_code}</code></span>
                <span>Redeemed: {offer.current_redemptions}/{offer.max_redemptions || "∞"}</span>
              </div>
              <div className="offer-actions">
                <button className="btn-secondary" onClick={() => openEditModal(offer)} data-testid={`edit-offer-${offer.id}`}>
                  Edit
                </button>
                <button className="btn-danger-outline" onClick={() => openDeleteConfirm(offer)} data-testid={`delete-offer-${offer.id}`}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Create New Offer</h3>
            <div className="form-group">
              <label>Title *</label>
              <input 
                type="text" 
                value={formData.title} 
                onChange={(e) => setFormData({ ...formData, title: e.target.value })} 
                placeholder="e.g., Early Bird Special" 
              />
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea 
                value={formData.description} 
                onChange={(e) => setFormData({ ...formData, description: e.target.value })} 
                placeholder="Describe your offer..." 
              />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Discount Percent</label>
                <input 
                  type="number" 
                  value={formData.discount_percent} 
                  onChange={(e) => setFormData({ ...formData, discount_percent: e.target.value })} 
                  placeholder="e.g., 20" 
                  min="0"
                  max="100"
                />
              </div>
              <div className="form-group">
                <label>Discount Code (optional)</label>
                <input 
                  type="text" 
                  value={formData.discount_code} 
                  onChange={(e) => setFormData({ ...formData, discount_code: e.target.value.toUpperCase() })} 
                  placeholder="e.g., SAVE20" 
                />
                <small className="form-hint">Auto-generated if left blank</small>
              </div>
            </div>
            <div className="modal-actions">
              <button className="btn-secondary" onClick={() => setShowCreateModal(false)}>Cancel</button>
              <button className="btn-primary" onClick={createOffer} disabled={!formData.title || isSaving}>
                {isSaving ? "Creating..." : "Create Offer"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && selectedOffer && (
        <div className="modal-overlay" onClick={() => { setShowEditModal(false); setSelectedOffer(null); }}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Edit Offer</h3>
            <div className="form-group">
              <label>Title *</label>
              <input 
                type="text" 
                value={formData.title} 
                onChange={(e) => setFormData({ ...formData, title: e.target.value })} 
                placeholder="e.g., Early Bird Special" 
              />
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea 
                value={formData.description} 
                onChange={(e) => setFormData({ ...formData, description: e.target.value })} 
                placeholder="Describe your offer..." 
              />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Discount Percent</label>
                <input 
                  type="number" 
                  value={formData.discount_percent} 
                  onChange={(e) => setFormData({ ...formData, discount_percent: e.target.value })} 
                  placeholder="e.g., 20" 
                  min="0"
                  max="100"
                />
              </div>
              <div className="form-group">
                <label>Discount Code</label>
                <input 
                  type="text" 
                  value={formData.discount_code} 
                  readOnly
                  className="input-readonly"
                />
                <small className="form-hint">Code cannot be changed after creation</small>
              </div>
            </div>
            <div className="form-group">
              <label className="toggle-label">
                <input 
                  type="checkbox" 
                  checked={formData.is_active} 
                  onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })} 
                />
                <span className="toggle-text">Active</span>
              </label>
              <small className="form-hint">Inactive offers won't be shown on your website</small>
            </div>
            <div className="modal-actions">
              <button className="btn-secondary" onClick={() => { setShowEditModal(false); setSelectedOffer(null); }}>Cancel</button>
              <button className="btn-primary" onClick={updateOffer} disabled={!formData.title || isSaving}>
                {isSaving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      <ConfirmDialog
        isOpen={showDeleteConfirm}
        title="Delete Offer"
        message={`Are you sure you want to delete "${selectedOffer?.title}"? This will deactivate the offer and hide it from your website.`}
        confirmLabel={isSaving ? "Deleting..." : "Delete"}
        onConfirm={deleteOffer}
        onCancel={() => { setShowDeleteConfirm(false); setSelectedOffer(null); }}
        isDestructive={true}
      />
    </div>
  );
};

const LeadsPage = () => {
  const { apiFetch } = useAuth();
  const toast = useToast();
  const [leads, setLeads] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const errorShownRef = useRef(false);

  useEffect(() => {
    let isMounted = true;
    
    const fetchLeads = async () => {
      setIsLoading(true);
      try {
        const params = filter === "verified" ? "?is_verified=true" : filter === "unverified" ? "?is_verified=false" : "";
        const res = await apiFetch(`/leads${params}`, { method: "GET" });
        if (isMounted) {
          setLeads(res.data);
          setIsLoading(false);
          errorShownRef.current = false;
        }
      } catch (e) {
        if (isMounted) {
          console.error(e);
          setIsLoading(false);
          if (!errorShownRef.current) {
            errorShownRef.current = true;
            toast.error("Failed to load leads", "load_leads");
          }
        }
      }
    };
    
    fetchLeads();
    return () => { isMounted = false; };
  }, [apiFetch, toast, filter]);

  const exportLeads = async () => {
    try {
      const res = await apiFetch("/leads/export", { method: "GET", responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "leads.csv");
      document.body.appendChild(link);
      link.click();
      link.remove();
      toast.success("Leads exported successfully");
    } catch (e) {
      toast.error("Error exporting leads");
    }
  };

  if (isLoading) return <div className="loading">Loading...</div>;

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
  const { apiFetch } = useAuth();
  const toast = useToast();
  const [sources, setSources] = useState([]);
  const [geography, setGeography] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [debugInfo, setDebugInfo] = useState(null);
  const [showDebug, setShowDebug] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const errorShownRef = useRef(false);
  const fetchAnalyticsRef = useRef(null);

  // Memoize fetchAnalytics to avoid re-creating on each render
  fetchAnalyticsRef.current = async () => {
    try {
      const [srcRes, geoRes, campRes, debugRes] = await Promise.all([
        apiFetch("/analytics/sources", { method: "GET" }),
        apiFetch("/analytics/geography", { method: "GET" }),
        apiFetch("/analytics/utm-campaigns", { method: "GET" }),
        apiFetch("/debug/analytics", { method: "GET" })
      ]);
      setSources(srcRes.data);
      setGeography(geoRes.data);
      setCampaigns(campRes.data);
      setDebugInfo(debugRes.data);
      setIsLoading(false);
      errorShownRef.current = false;
    } catch (e) {
      console.error(e);
      setIsLoading(false);
      if (!errorShownRef.current) {
        errorShownRef.current = true;
        toast.error("Failed to load analytics", "load_analytics");
      }
    }
  };

  useEffect(() => {
    let isMounted = true;
    
    const fetchData = async () => {
      if (isMounted && fetchAnalyticsRef.current) {
        await fetchAnalyticsRef.current();
      }
    };
    
    fetchData();
    return () => { isMounted = false; };
  }, [apiFetch, toast]);

  const generateDemoData = async () => {
    setGenerating(true);
    try {
      await apiFetch("/demo/generate", { method: "POST" });
      toast.success("Demo data generated! Refreshing...");
      if (fetchAnalyticsRef.current) {
        await fetchAnalyticsRef.current();
      }
    } catch (e) {
      toast.error("Error generating demo data");
    } finally {
      setGenerating(false);
    }
  };

  if (isLoading) return <div className="loading">Loading...</div>;

  const hasNoData = sources.length === 0 && geography.length === 0 && campaigns.length === 0;

  return (
    <div className="page" data-testid="analytics-page">
      <div className="page-header">
        <h2>Analytics</h2>
        <button className="btn-secondary" onClick={() => setShowDebug(!showDebug)}>
          {showDebug ? "Hide Debug" : "Debug Info"}
        </button>
      </div>
      
      {/* Debug Panel */}
      {showDebug && debugInfo && (
        <div className="debug-panel">
          <h4>Analytics Debug Info</h4>
          <div className="debug-grid">
            <div className="debug-item">
              <span className="debug-label">Business ID:</span>
              <code>{debugInfo.business_id}</code>
            </div>
            <div className="debug-item">
              <span className="debug-label">Public Key:</span>
              <code>{debugInfo.public_key}</code>
            </div>
            <div className="debug-item">
              <span className="debug-label">Visitors:</span>
              <span className={debugInfo.counts.visitors > 0 ? "debug-ok" : "debug-warn"}>{debugInfo.counts.visitors}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">Traffic Events:</span>
              <span className={debugInfo.counts.traffic_events > 0 ? "debug-ok" : "debug-warn"}>{debugInfo.counts.traffic_events}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">Leads:</span>
              <span className={debugInfo.counts.leads > 0 ? "debug-ok" : "debug-warn"}>{debugInfo.counts.leads}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">Events with UTM Source:</span>
              <span>{debugInfo.counts.events_with_utm_source}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">Events with Country:</span>
              <span>{debugInfo.counts.events_with_country}</span>
            </div>
          </div>
          {debugInfo.last_5_events.length > 0 && (
            <div className="debug-events">
              <h5>Last 5 Traffic Events:</h5>
              <table className="debug-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Page</th>
                    <th>UTM Source</th>
                    <th>Country</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {debugInfo.last_5_events.map(e => (
                    <tr key={e.id}>
                      <td>{e.event_type}</td>
                      <td>{e.page_url}</td>
                      <td>{e.utm_source || "-"}</td>
                      <td>{e.country || "-"}</td>
                      <td>{new Date(e.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="debug-recommendation">
            <strong>Diagnosis:</strong> {debugInfo.diagnosis.recommendation}
          </div>
        </div>
      )}

      {/* No Data State */}
      {hasNoData && (
        <div className="empty-state-box analytics-empty">
          <h3>No analytics data yet</h3>
          <p>Analytics will populate when visitors interact with your embedded offers, or you can generate demo data to preview the dashboard.</p>
          <button className="btn-primary" onClick={generateDemoData} disabled={generating}>
            {generating ? "Generating..." : "Generate Demo Data"}
          </button>
        </div>
      )}

      {/* Analytics Cards */}
      {!hasNoData && (
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
      )}
    </div>
  );
};

const SettingsPage = () => {
  const { apiFetch } = useAuth();
  const toast = useToast();
  const [business, setBusiness] = useState(null);
  const [offers, setOffers] = useState([]);
  const [systemStatus, setSystemStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);
  const errorShownRef = useRef(false);

  useEffect(() => {
    let isMounted = true;
    
    const fetchData = async () => {
      try {
        const [bizRes, offersRes, statusRes] = await Promise.all([
          apiFetch("/settings/business", { method: "GET" }),
          apiFetch("/offers", { method: "GET" }),
          apiFetch("/settings/status", { method: "GET" }).catch(() => ({ data: null }))
        ]);
        if (isMounted) {
          setBusiness(bizRes.data);
          setOffers(offersRes.data.filter(o => o.is_active));
          setSystemStatus(statusRes.data);
          setIsLoading(false);
        }
      } catch (e) {
        if (isMounted) {
          console.error(e);
          setIsLoading(false);
          if (!errorShownRef.current) {
            errorShownRef.current = true;
            toast.error("Failed to load settings", "load_settings");
          }
        }
      }
    };
    
    fetchData();
    return () => { isMounted = false; };
  }, [apiFetch, toast]);

  const generateDemoData = async () => {
    setGenerating(true);
    try {
      await apiFetch("/demo/generate", { method: "POST" });
      toast.success("Demo data generated! Refreshing...");
      setTimeout(() => window.location.reload(), 1000);
    } catch (e) {
      toast.error("Error generating demo data");
    } finally {
      setGenerating(false);
    }
  };

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopySuccess(true);
      toast.success("Copied to clipboard");
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (e) {
      toast.info("Please select and copy the code manually");
    }
  };

  if (isLoading) return <div className="loading">Loading...</div>;

  const isPreview = window.location.hostname.includes('preview.emergentagent.com') || window.location.hostname === 'localhost';
  const isProduction = window.location.hostname === 'app.verifieddemand.com';
  
  const selectedOfferId = offers[0]?.id || 'YOUR_OFFER_ID';
  
  // Use production URL for embed instructions
  const embedBaseUrl = isProduction ? 'https://app.verifieddemand.com' : BACKEND_URL;

  const embedSnippet = `<!-- Verified Demand Embed Script -->
<script 
  src="${embedBaseUrl}/api/embed.js" 
  data-public-key="${business?.public_key}" 
  data-offer-id="${selectedOfferId}"
  data-debug="false">
</script>`;

  const triggerExample = `<!-- Add data-vd-trigger to any element to open the modal -->
<button data-vd-trigger>Get Your Offer</button>

<!-- Works on any element -->
<a href="#" data-vd-trigger>View Pricing</a>
<div data-vd-trigger class="cta-banner">Click for discount</div>`;

  return (
    <div className="page" data-testid="settings-page">
      <h2>Settings</h2>
      
      {/* System Status */}
      <div className="settings-section">
        <h3>System Status</h3>
        <div className="status-grid">
          <div className="status-item">
            <span className="status-label">Database</span>
            <span className={`status-value ${systemStatus?.database === 'healthy' ? 'status-ok' : 'status-warning'}`}>
              {systemStatus?.database === 'healthy' ? '● Connected' : '○ Not connected'}
            </span>
          </div>
          <div className="status-item">
            <span className="status-label">Twilio (OTP)</span>
            <span className={`status-value ${systemStatus?.twilio ? 'status-ok' : 'status-warning'}`}>
              {systemStatus?.twilio ? '● Configured' : '○ Not configured (mock mode)'}
            </span>
          </div>
          <div className="status-item">
            <span className="status-label">Environment</span>
            <span className={`status-value ${isProduction ? 'status-ok' : 'status-warning'}`}>
              {isProduction ? '● Production' : isPreview ? '○ Preview' : '○ Development'}
            </span>
          </div>
        </div>
      </div>

      {/* Business Info */}
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

      {/* Embed Script */}
      <div className="settings-section">
        <h3>Embed Script</h3>
        <p className="section-description">
          Add this script to your website to enable lead capture. Place it before the closing <code>&lt;/body&gt;</code> tag.
        </p>
        
        <div className="embed-step">
          <div className="step-number">1</div>
          <div className="step-content">
            <h4>Add the script tag</h4>
            <pre className="code-block">{embedSnippet}</pre>
            <button 
              className={`btn-secondary ${copySuccess ? 'btn-success' : ''}`} 
              onClick={() => copyToClipboard(embedSnippet)}
            >
              {copySuccess ? '✓ Copied!' : 'Copy Script'}
            </button>
          </div>
        </div>

        <div className="embed-step">
          <div className="step-number">2</div>
          <div className="step-content">
            <h4>Add trigger elements</h4>
            <p className="step-description">Add <code>data-vd-trigger</code> to any element that should open the offer modal:</p>
            <pre className="code-block">{triggerExample}</pre>
          </div>
        </div>

        {offers.length === 0 && (
          <div className="embed-warning">
            ⚠️ You don't have any active offers. Create an offer first to use the embed.
          </div>
        )}

        {offers.length > 1 && (
          <div className="embed-info">
            ℹ️ Using offer "{offers[0]?.title}". To use a different offer, replace the <code>data-offer-id</code> value with the desired offer ID.
          </div>
        )}
      </div>

      {/* Demo Data */}
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
    <ToastProvider>
      <AuthProvider>
        <AppContent view={view} setView={setView} />
      </AuthProvider>
    </ToastProvider>
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
