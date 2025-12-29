import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const EMBED_URL = `${BACKEND_URL}/api/embed.js`;

// Modal Component
const Modal = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null;
  
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full mx-4 max-h-[90vh] overflow-auto">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
          >
            &times;
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
};

// Masked key display
const MaskedKey = ({ publicKey, showCopy = true }) => {
  const masked = publicKey ? `${publicKey.slice(0, 4)}...${publicKey.slice(-4)}` : "-";
  
  const copyKey = () => {
    navigator.clipboard.writeText(publicKey);
  };
  
  return (
    <div className="flex items-center gap-2">
      <code className="text-sm bg-gray-100 px-2 py-1 rounded">{masked}</code>
      {showCopy && (
        <button
          onClick={copyKey}
          className="text-blue-600 hover:text-blue-800 text-sm"
          title="Copy full key"
        >
          Copy
        </button>
      )}
    </div>
  );
};

// Create Site Form
const CreateSiteForm = ({ onSuccess, onCancel }) => {
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [emails, setEmails] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    
    try {
      const emailList = emails
        .split(",")
        .map(e => e.trim())
        .filter(e => e.length > 0);
      
      const response = await axios.post(`${API}/dashboard/sites`, {
        name,
        domain: domain || null,
        notification_emails: emailList
      });
      
      if (response.data.error) {
        setError(response.data.error);
      } else {
        onSuccess(response.data);
      }
    } catch (err) {
      setError(err.response?.data?.error || "Failed to create site");
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Site Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="e.g., Madera Ford"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
      </div>
      
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Domain (optional)
        </label>
        <input
          type="text"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          placeholder="e.g., maderaford.com"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
      </div>
      
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Notification Emails (comma-separated)
        </label>
        <input
          type="text"
          value={emails}
          onChange={(e) => setEmails(e.target.value)}
          placeholder="leads@example.com, sales@example.com"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
      </div>
      
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm">
          {error}
        </div>
      )}
      
      <div className="flex gap-3 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={loading || !name}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Creating..." : "Create Site"}
        </button>
      </div>
    </form>
  );
};

// Site Detail/Edit Component
const SiteDetail = ({ site, onClose, onUpdate }) => {
  const [name, setName] = useState(site.name);
  const [domain, setDomain] = useState(site.domain || "");
  const [emails, setEmails] = useState((site.notification_emails || []).join(", "));
  const [allowedDomains, setAllowedDomains] = useState((site.allowed_domains || []).join("\n"));
  const [isActive, setIsActive] = useState(site.is_active);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(null);
  const [testEmailStatus, setTestEmailStatus] = useState(null);
  const [sendingTestEmail, setSendingTestEmail] = useState(false);
  
  const handleSendTestEmail = async () => {
    setSendingTestEmail(true);
    setTestEmailStatus(null);
    
    try {
      const response = await axios.post(`${API}/dashboard/sites/${site.public_key}/send-test-email`);
      if (response.data.success) {
        setTestEmailStatus({ type: "success", message: response.data.message });
      } else {
        setTestEmailStatus({ type: "error", message: response.data.error });
      }
    } catch (err) {
      setTestEmailStatus({ 
        type: "error", 
        message: err.response?.data?.error || "Failed to send test email" 
      });
    } finally {
      setSendingTestEmail(false);
    }
  };
  
  const handleSave = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const emailList = emails
        .split(",")
        .map(e => e.trim())
        .filter(e => e.length > 0);
      
      const domainList = allowedDomains
        .split("\n")
        .map(d => d.trim())
        .filter(d => d.length > 0);
      
      const response = await axios.patch(`${API}/dashboard/sites/${site.public_key}`, {
        name,
        domain: domain || null,
        is_active: isActive,
        notification_emails: emailList,
        allowed_domains: domainList
      });
      
      if (response.data.error) {
        setError(response.data.error);
      } else {
        onUpdate(response.data);
      }
    } catch (err) {
      setError(err.response?.data?.error || "Failed to update site");
    } finally {
      setLoading(false);
    }
  };
  
  const copyToClipboard = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  };
  
  const embedSnippet = `<script
  src="${EMBED_URL}"
  data-public-key="${site.public_key}"
  data-debug="false">
</script>`;

  const buttonMarkup = `<button data-vd-trigger="unlock-price">Unlock Instant Price</button>`;
  
  return (
    <div className="space-y-6">
      {/* Public Key Section */}
      <div className="bg-gray-50 p-4 rounded-lg">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Public Key
        </label>
        <div className="flex items-center gap-2">
          <code className="flex-1 bg-white px-3 py-2 rounded border text-sm font-mono">
            {site.public_key}
          </code>
          <button
            onClick={() => copyToClipboard(site.public_key, "key")}
            className="px-3 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            {copied === "key" ? "Copied!" : "Copy"}
          </button>
        </div>
      </div>
      
      {/* Install Snippet */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Install Snippet
        </label>
        <div className="relative">
          <pre className="bg-gray-900 text-green-400 p-4 rounded-lg text-sm overflow-x-auto">
            {embedSnippet}
          </pre>
          <button
            onClick={() => copyToClipboard(embedSnippet, "snippet")}
            className="absolute top-2 right-2 px-2 py-1 text-xs bg-gray-700 text-white rounded hover:bg-gray-600"
          >
            {copied === "snippet" ? "Copied!" : "Copy Snippet"}
          </button>
        </div>
      </div>
      
      {/* Button Markup */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Trigger Button Example
        </label>
        <div className="relative">
          <pre className="bg-gray-900 text-green-400 p-4 rounded-lg text-sm overflow-x-auto">
            {buttonMarkup}
          </pre>
          <button
            onClick={() => copyToClipboard(buttonMarkup, "button")}
            className="absolute top-2 right-2 px-2 py-1 text-xs bg-gray-700 text-white rounded hover:bg-gray-600"
          >
            {copied === "button" ? "Copied!" : "Copy"}
          </button>
        </div>
      </div>
      
      <hr className="my-4" />
      
      {/* Editable Fields */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Site Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
      </div>
      
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Primary Domain
        </label>
        <input
          type="text"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          placeholder="maderaford.com"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
      </div>
      
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Allowed Domains (one per line)
        </label>
        <textarea
          value={allowedDomains}
          onChange={(e) => setAllowedDomains(e.target.value)}
          placeholder={"maderaford.com\nwww.maderaford.com\nstaging.maderaford.com"}
          rows={3}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
        />
        <p className="text-xs text-gray-500 mt-1">
          If empty, the primary domain is used. Leads from unlisted domains will be flagged as &quot;mismatch&quot;.
        </p>
      </div>
      
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Notification Emails
        </label>
        <input
          type="text"
          value={emails}
          onChange={(e) => setEmails(e.target.value)}
          placeholder="leads@example.com, sales@example.com"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
        />
        <div className="mt-2">
          <button
            onClick={handleSendTestEmail}
            disabled={sendingTestEmail || !emails.trim()}
            className="px-3 py-1 text-sm bg-gray-100 border border-gray-300 rounded-md hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {sendingTestEmail ? "Sending..." : "📧 Send Test Email"}
          </button>
        </div>
        {testEmailStatus && (
          <div className={`mt-2 p-2 rounded-md text-sm ${
            testEmailStatus.type === "success" 
              ? "bg-green-50 border border-green-200 text-green-700"
              : "bg-red-50 border border-red-200 text-red-700"
          }`}>
            {testEmailStatus.type === "success" ? "✅ " : "❌ "}
            {testEmailStatus.message}
          </div>
        )}
      </div>
      
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-gray-700">Status:</label>
        <button
          onClick={() => setIsActive(!isActive)}
          className={`px-3 py-1 rounded-full text-sm font-medium ${
            isActive
              ? "bg-green-100 text-green-800"
              : "bg-red-100 text-red-800"
          }`}
        >
          {isActive ? "Active" : "Inactive"}
        </button>
      </div>
      
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm">
          {error}
        </div>
      )}
      
      <div className="flex gap-3 justify-end pt-4 border-t">
        <button
          onClick={onClose}
          className="px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50"
        >
          Close
        </button>
        <button
          onClick={handleSave}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Saving..." : "Save Changes"}
        </button>
      </div>
    </div>
  );
};

// Main Sites Page Component
const SitesPage = () => {
  const [sites, setSites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedSite, setSelectedSite] = useState(null);
  const [rotateConfirm, setRotateConfirm] = useState(null);
  const [rotating, setRotating] = useState(false);
  
  const fetchSites = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/dashboard/sites`);
      setSites(response.data.sites || []);
    } catch (err) {
      setError("Failed to load sites");
    } finally {
      setLoading(false);
    }
  }, []);
  
  useEffect(() => {
    fetchSites();
  }, [fetchSites]);
  
  const handleCreateSuccess = (newSite) => {
    setSites([newSite, ...sites]);
    setShowCreateModal(false);
  };
  
  const handleUpdateSite = (updatedSite) => {
    setSites(sites.map(s => 
      s.public_key === updatedSite.public_key ? updatedSite : s
    ));
    setSelectedSite(null);
  };
  
  const handleRotateKey = async (publicKey) => {
    setRotating(true);
    try {
      const response = await axios.post(`${API}/dashboard/sites/${publicKey}/rotate-key`);
      if (response.data.error) {
        alert(response.data.error);
      } else {
        setSites(sites.map(s => 
          s.public_key === publicKey ? response.data.site : s
        ));
        alert(`Key rotated! New key: ${response.data.new_key}`);
      }
    } catch (err) {
      alert("Failed to rotate key");
    } finally {
      setRotating(false);
      setRotateConfirm(null);
    }
  };
  
  const copySnippet = (publicKey) => {
    const snippet = `<script
  src="${EMBED_URL}"
  data-public-key="${publicKey}"
  data-debug="false">
</script>`;
    navigator.clipboard.writeText(snippet);
    alert("Snippet copied to clipboard!");
  };
  
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="text-gray-500">Loading sites...</div>
      </div>
    );
  }
  
  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Sites & Install</h1>
            <p className="text-sm text-gray-500 mt-1">Manage your sites and get install snippets</p>
          </div>
          <div className="flex gap-3">
            <a
              href="/dashboard"
              className="px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50 text-gray-700"
            >
              Analytics
            </a>
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
            >
              + Create Site
            </button>
          </div>
        </div>
      </header>
      
      <main className="max-w-7xl mx-auto px-4 py-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-red-700">
            {error}
          </div>
        )}
        
        {sites.length === 0 ? (
          <div className="bg-white rounded-lg shadow p-12 text-center">
            <div className="text-5xl mb-4">🏢</div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">No Sites Yet</h2>
            <p className="text-gray-500 mb-6">Create your first site to get started with lead tracking.</p>
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
            >
              Create Your First Site
            </button>
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Site Name</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Public Key</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {sites.map((site) => (
                  <tr key={site.public_key} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="font-medium text-gray-900">{site.name}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {site.domain || "-"}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <MaskedKey publicKey={site.public_key} />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`px-2 py-1 text-xs rounded-full font-medium ${
                        site.is_active
                          ? "bg-green-100 text-green-800"
                          : "bg-red-100 text-red-800"
                      }`}>
                        {site.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {site.created_at ? new Date(site.created_at).toLocaleDateString() : "-"}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm">
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => setSelectedSite(site)}
                          className="text-blue-600 hover:text-blue-800"
                        >
                          View/Edit
                        </button>
                        <button
                          onClick={() => copySnippet(site.public_key)}
                          className="text-green-600 hover:text-green-800"
                        >
                          Copy Snippet
                        </button>
                        <button
                          onClick={() => setRotateConfirm(site.public_key)}
                          className="text-orange-600 hover:text-orange-800"
                        >
                          Rotate Key
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
      
      {/* Create Site Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        title="Create New Site"
      >
        <CreateSiteForm
          onSuccess={handleCreateSuccess}
          onCancel={() => setShowCreateModal(false)}
        />
      </Modal>
      
      {/* Site Detail Modal */}
      <Modal
        isOpen={!!selectedSite}
        onClose={() => setSelectedSite(null)}
        title={selectedSite?.name || "Site Details"}
      >
        {selectedSite && (
          <SiteDetail
            site={selectedSite}
            onClose={() => setSelectedSite(null)}
            onUpdate={handleUpdateSite}
          />
        )}
      </Modal>
      
      {/* Rotate Key Confirmation Modal */}
      <Modal
        isOpen={!!rotateConfirm}
        onClose={() => setRotateConfirm(null)}
        title="Rotate Public Key"
      >
        <div className="space-y-4">
          <p className="text-gray-600">
            Are you sure you want to rotate this site&apos;s public key? The old key will be preserved
            in history, but new tracking requests should use the new key.
          </p>
          <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3 text-yellow-800 text-sm">
            ⚠️ You will need to update your embed snippet with the new key.
          </div>
          <div className="flex gap-3 justify-end">
            <button
              onClick={() => setRotateConfirm(null)}
              className="px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={() => handleRotateKey(rotateConfirm)}
              disabled={rotating}
              className="px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 disabled:opacity-50"
            >
              {rotating ? "Rotating..." : "Rotate Key"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default SitesPage;
