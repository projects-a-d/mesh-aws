const config = window.APP_CONFIG || {};
const apiBase = (config.apiBase || "").replace(/\/$/, "");

const defaultResult = {};
const state = {
  linkToken: null,
  accessToken: "",
  lastResponses: [],
};

const outEl = document.getElementById("out");
const statusEl = document.getElementById("status");
const diagnosticsEl = document.getElementById("link-diagnostics");
const accessTokenInput = document.getElementById("access-token");
const connectBtn = document.getElementById("connect-btn");
const transferForm = document.getElementById("transfer-form");
const portfolioBtn = document.getElementById("portfolio-btn");
const clearBtn = document.getElementById("clear-output");

let meshSdkPromise;

if (!apiBase) {
  setStatus("Missing API base URL. Update window.APP_CONFIG.apiBase in index.html.", "error");
  connectBtn.disabled = true;
  portfolioBtn.disabled = true;
}

function setStatus(message, type = "info") {
  if (!statusEl) return;
  statusEl.textContent = message || "";
  statusEl.classList.remove("error", "success");
  if (type === "error" || type === "success") {
    statusEl.classList.add(type);
  }
}

function appendResult(title, payload) {
  state.lastResponses.unshift({ title, at: new Date().toISOString(), payload });
  if (state.lastResponses.length > 6) {
    state.lastResponses.pop();
  }
  outEl.textContent = JSON.stringify(state.lastResponses, null, 2);
}

function setDiagnostics(msg) {
  diagnosticsEl.textContent = msg || "";
}

function loadScript(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.async = true;
    script.onload = () => resolve(true);
    script.onerror = () => reject(new Error(`Failed to load ${url}`));
    document.head.appendChild(script);
  });
}

async function ensureMeshSdk() {
  if (window.MeshLink || (window.Mesh && (window.Mesh.Link || window.Mesh.open))) {
    return;
  }
  if (!meshSdkPromise) {
    const scriptUrl = window.MESH_LINK_SDK_URL || "https://cdn.meshconnect.com/web-sdk/latest/mesh.js";
    meshSdkPromise = loadScript(scriptUrl).catch((err) => {
      meshSdkPromise = null;
      throw err;
    });
  }
  await meshSdkPromise;
}

function resolveMeshLauncher(config) {
  if (window.MeshLink && typeof window.MeshLink === "function") {
    return window.MeshLink(config);
  }
  if (window.MeshLink && typeof window.MeshLink.create === "function") {
    return window.MeshLink.create(config);
  }
  if (window.Mesh && typeof window.Mesh.Link?.create === "function") {
    return window.Mesh.Link.create(config);
  }
  if (window.Mesh && typeof window.Mesh.open === "function") {
    return {
      open: () => window.Mesh.open(config),
    };
  }
  if (window.MeshConnectLink && typeof window.MeshConnectLink.create === "function") {
    return window.MeshConnectLink.create(config);
  }
  return null;
}

async function meshFetch(path, options = {}) {
  if (!apiBase) {
    throw new Error("API base URL is not configured");
  }
  const resp = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await resp.json().catch(() => defaultResult);
  if (!resp.ok) {
    const err = new Error(data?.error || `Request failed (${resp.status})`);
    err.details = data;
    err.status = resp.status;
    throw err;
  }
  return data;
}

function rememberAccessToken(token) {
  if (!token) return;
  state.accessToken = token;
  accessTokenInput.value = token;
  setStatus("Access token stored — ready for payment and portfolio calls.", "success");
}

async function handleConnectClick() {
  setStatus("Requesting Mesh link token...");
  setDiagnostics("");
  connectBtn.disabled = true;
  try {
    const payload = {
      products: ["transactions", "portfolio", "transfer"],
      provider: "coinbase",
    };
    const tokenResp = await meshFetch("/mesh/link-token", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    appendResult("link-token", tokenResp);
    state.linkToken = tokenResp.linkToken || tokenResp.token || tokenResp.link_token;
    if (!state.linkToken) {
      throw new Error("Mesh did not return a linkToken. Check diagnostics or secret configuration.");
    }
    await ensureMeshSdk();
    const launcher = resolveMeshLauncher({
      linkToken: state.linkToken,
      onSuccess: (result) => {
        appendResult("link-success", result);
        const token =
          result?.accessToken ||
          result?.access_token ||
          result?.data?.accessToken ||
          result?.data?.access_token;
        if (token) {
          rememberAccessToken(token);
        } else {
          setStatus("Link succeeded – please copy the access token from the JSON payload.", "success");
        }
      },
      onExit: (result) => {
        appendResult("link-exit", result || {});
        setStatus("Mesh Link closed.", "info");
      },
      onEvent: (eventName, metadata) => {
        appendResult(`link-event:${eventName}`, metadata || {});
      },
    });
    if (!launcher || typeof launcher.open !== "function") {
      throw new Error("Mesh Web SDK is loaded but no open() function is available. Update MESH_LINK_SDK_URL to the latest script.");
    }
    launcher.open();
    setStatus("Mesh Link opened — complete the Coinbase flow.");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Failed to launch Mesh Link", "error");
    setDiagnostics(err.details ? JSON.stringify(err.details, null, 2) : "");
  } finally {
    connectBtn.disabled = false;
  }
}

async function handleTransferSubmit(event) {
  event.preventDefault();
  const formData = new FormData(transferForm);
  const accessToken = formData.get("accessToken")?.trim();
  const amount = parseFloat(formData.get("amount"));
  const toAddress = formData.get("toAddress")?.trim();
  const network = formData.get("network") || "ethereum";
  const twoFactorCode = formData.get("twoFactorCode")?.trim() || "123456";

  if (!accessToken) {
    setStatus("Enter an access token before sending a transfer.", "error");
    return;
  }
  if (!toAddress) {
    setStatus("Destination wallet address is required.", "error");
    return;
  }

  setStatus("Sending transfer request...");
  try {
    const resp = await meshFetch("/mesh/pay", {
      method: "POST",
      body: JSON.stringify({
        accessToken,
        amount,
        network,
        toAddress,
        memo: "Shoes",
        asset: "USDC",
        twoFactorCode,
      }),
    });
    appendResult("pay", resp);
    setStatus("Transfer created in Mesh sandbox.", "success");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Transfer failed", "error");
    appendResult("pay-error", err.details || { message: err.message });
  }
}

async function handlePortfolioClick() {
  const token = accessTokenInput.value.trim();
  if (!token) {
    setStatus("Enter an access token before fetching portfolio.", "error");
    return;
  }

  setStatus("Requesting portfolio...");
  try {
    const resp = await meshFetch(`/mesh/portfolio?accessToken=${encodeURIComponent(token)}`, {
      method: "GET",
    });
    appendResult("portfolio", resp);
    setStatus("Portfolio retrieved.", "success");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Portfolio request failed", "error");
    appendResult("portfolio-error", err.details || { message: err.message });
  }
}

function handleClear() {
  state.lastResponses = [];
  outEl.textContent = JSON.stringify({}, null, 2);
  setStatus("Cleared output.");
}

connectBtn?.addEventListener("click", handleConnectClick);
transferForm?.addEventListener("submit", handleTransferSubmit);
portfolioBtn?.addEventListener("click", handlePortfolioClick);
clearBtn?.addEventListener("click", handleClear);

if (config.defaultAccessToken) {
  rememberAccessToken(config.defaultAccessToken);
} else {
  setStatus("Ready — connect your Coinbase sandbox account to begin.");
}
