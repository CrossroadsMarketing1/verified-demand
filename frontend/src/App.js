import { useState, useEffect } from "react";
import "@/App.css";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Auth context/state management
const useAuth = () => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("token"));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (token) {
      fetchUser();
    } else {
      setLoading(false);
    }
  }, [token]);

  const fetchUser = async () => {
    try {
      const response = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setUser(response.data);
    } catch (e) {
      console.error("Failed to fetch user:", e);
      localStorage.removeItem("token");
      setToken(null);
    } finally {
      setLoading(false);
    }
  };

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
      email,
      password,
      first_name: firstName,
      last_name: lastName
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

  return { user, token, loading, login, register, logout, resetPassword };
};

// Login Form Component
const LoginForm = ({ onLogin, onSwitchToRegister, onForgotPassword }) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await onLogin(email, password);
    } catch (err) {
      setError(err.response?.data?.detail || "Login failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>Welcome back</h2>
        <p className="auth-subtitle">Sign in to your account</p>
        
        {error && <div className="error-message" data-testid="login-error">{error}</div>}
        
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="email">Email address</label>
            <input
              type="email"
              id="email"
              data-testid="login-email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
            />
          </div>
          
          <div className="form-group">
            <div className="label-row">
              <label htmlFor="password">Password</label>
              <button 
                type="button" 
                className="link-button"
                onClick={onForgotPassword}
                data-testid="forgot-password-link"
              >
                Forgot password?
              </button>
            </div>
            <input
              type="password"
              id="password"
              data-testid="login-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              placeholder="••••••••"
            />
          </div>
          
          <button 
            type="submit" 
            className="btn-primary" 
            disabled={loading}
            data-testid="login-submit"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>
        
        <p className="auth-footer">
          Don't have an account?{" "}
          <button 
            type="button" 
            className="link-button"
            onClick={onSwitchToRegister}
            data-testid="switch-to-register"
          >
            Create account
          </button>
        </p>
      </div>
    </div>
  );
};

// Register Form Component
const RegisterForm = ({ onRegister, onSwitchToLogin }) => {
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
      await onRegister(email, password, firstName, lastName);
    } catch (err) {
      setError(err.response?.data?.detail || "Registration failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>Create account</h2>
        <p className="auth-subtitle">Sign up to get started</p>
        
        {error && <div className="error-message" data-testid="register-error">{error}</div>}
        
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor="firstName">First name</label>
              <input
                type="text"
                id="firstName"
                data-testid="register-firstname"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                placeholder="John"
              />
            </div>
            <div className="form-group">
              <label htmlFor="lastName">Last name</label>
              <input
                type="text"
                id="lastName"
                data-testid="register-lastname"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder="Doe"
              />
            </div>
          </div>
          
          <div className="form-group">
            <label htmlFor="registerEmail">Email address</label>
            <input
              type="email"
              id="registerEmail"
              data-testid="register-email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
            />
          </div>
          
          <div className="form-group">
            <label htmlFor="registerPassword">Password</label>
            <input
              type="password"
              id="registerPassword"
              data-testid="register-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              placeholder="At least 8 characters"
            />
          </div>
          
          <button 
            type="submit" 
            className="btn-primary" 
            disabled={loading}
            data-testid="register-submit"
          >
            {loading ? "Creating account..." : "Create account"}
          </button>
        </form>
        
        <p className="auth-footer">
          Already have an account?{" "}
          <button 
            type="button" 
            className="link-button"
            onClick={onSwitchToLogin}
            data-testid="switch-to-login"
          >
            Sign in
          </button>
        </p>
      </div>
    </div>
  );
};

// Forgot Password Component
const ForgotPasswordForm = ({ onResetPassword, onBackToLogin }) => {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const result = await onResetPassword(email);
      setMessage(result.message);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to send reset email. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>Reset password</h2>
        <p className="auth-subtitle">Enter your email to receive a reset link</p>
        
        {error && <div className="error-message" data-testid="reset-error">{error}</div>}
        {message && <div className="success-message" data-testid="reset-success">{message}</div>}
        
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="resetEmail">Email address</label>
            <input
              type="email"
              id="resetEmail"
              data-testid="reset-email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
            />
          </div>
          
          <button 
            type="submit" 
            className="btn-primary" 
            disabled={loading}
            data-testid="reset-submit"
          >
            {loading ? "Sending..." : "Send reset link"}
          </button>
        </form>
        
        <p className="auth-footer">
          <button 
            type="button" 
            className="link-button"
            onClick={onBackToLogin}
            data-testid="back-to-login"
          >
            ← Back to sign in
          </button>
        </p>
      </div>
    </div>
  );
};

// Dashboard Component (after login)
const Dashboard = ({ user, onLogout }) => {
  return (
    <div className="dashboard" data-testid="dashboard">
      <header className="dashboard-header">
        <h1>Traffic Insight</h1>
        <div className="user-menu">
          <span data-testid="user-email">{user.email}</span>
          <button 
            onClick={onLogout} 
            className="btn-secondary"
            data-testid="logout-button"
          >
            Sign out
          </button>
        </div>
      </header>
      
      <main className="dashboard-main">
        <div className="welcome-card">
          <h2>Welcome{user.first_name ? `, ${user.first_name}` : ""}!</h2>
          <p>You're now logged in to Traffic Insight.</p>
          <div className="user-info">
            <p><strong>Email:</strong> {user.email}</p>
            <p><strong>Account ID:</strong> {user.id}</p>
            <p><strong>Status:</strong> {user.is_active ? "Active" : "Inactive"}</p>
            <p><strong>Verified:</strong> {user.is_verified ? "Yes" : "No"}</p>
          </div>
        </div>
      </main>
    </div>
  );
};

// Main App Component
function App() {
  const { user, loading, login, register, logout, resetPassword } = useAuth();
  const [view, setView] = useState("login"); // login, register, forgot-password

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading...</p>
      </div>
    );
  }

  if (user) {
    return <Dashboard user={user} onLogout={logout} />;
  }

  return (
    <div className="App">
      {view === "login" && (
        <LoginForm
          onLogin={login}
          onSwitchToRegister={() => setView("register")}
          onForgotPassword={() => setView("forgot-password")}
        />
      )}
      {view === "register" && (
        <RegisterForm
          onRegister={register}
          onSwitchToLogin={() => setView("login")}
        />
      )}
      {view === "forgot-password" && (
        <ForgotPasswordForm
          onResetPassword={resetPassword}
          onBackToLogin={() => setView("login")}
        />
      )}
    </div>
  );
}

export default App;
