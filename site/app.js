import { createLink } from "https://esm.sh/@meshconnect/web-link-sdk@latest";

const config = window.APP_CONFIG || {};
const apiBase = (config.apiBase || "").replace(/\/$/, "");
const clientId = config.meshClientId || config.clientId || "";

const statusEl = document.getElementById("status");
const diagnosticsEl = document.getElementById("link-diagnostics");
const outputEl = document.getElementById("out");
const connectBtn = document.getElementById("connect-btn");
const payBtn = document.getElementById("pay-btn");
const portfolioBtn = document.getElementById("portfolio-btn");
const clearBtn = document.getElementById("clear-output");
const accessTokenInput = document.getElementById("access-token");
const accountIdInput = document.getElementById("account-id");
const portfolioTypeInput = document.getElementById("portfolio-type");

const state = {
  latestAuthToken: "",
  latestAccountId: "",
};

function setStatus(message, type = "info") {
  if (!statusEl) return;
  statusEl.textContent = message || "";
  statusEl.classList.remove("error", "success");
  if (type === "error" || type === "success") {
    statusEl.classList.add(type);
  }
}

function setDiagnostics(value) {
  if (!diagnosticsEl) return;
  if (!value) {
    diagnosticsEl.textContent = "";
    return;
  }
  diagnosticsEl.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function log(label, payload) {
  if (!outputEl) return;
  const time = new Date().toLocaleTimeString();
  const text = `[${time}] ${label}:\n${JSON.stringify(payload, null, 2)}\n\n`;
  outputEl.textContent = text + (outputEl.textContent || "");
}

function rememberAuth(details) {
  if (details?.token) {
    state.latestAuthToken = details.token;
  }
  if (details?.accountId) {
    state.latestAccountId = details.accountId;
  }
  if (accessTokenInput) {
    accessTokenInput.value = state.latestAuthToken || "";
  }
  if (accountIdInput && !accountIdInput.value && state.latestAccountId) {
    accountIdInput.value = state.latestAccountId;
  }
  if (state.latestAuthToken) {
    setStatus("Access token stored — ready for portfolio calls.", "success");
  }
}

function pickAuthToken(payload) {
  if (typeof payload?.accessToken === "string") return payload.accessToken;
  if (payload?.accessToken?.accessToken) return payload.accessToken.accessToken;
  const nested =
    payload?.accessToken?.accountTokens?.[0]?.token ||
    payload?.accessToken?.accountTokens?.[0]?.accessToken;
  if (nested) return nested;
  const legacy =
    payload?.accessTokens?.[0]?.token ||
    payload?.accessTokens?.[0]?.accessToken;
  return legacy || "";
}

function pickAccountId(payload) {
  return (
    payload?.accessToken?.accountTokens?.[0]?.account?.accountId ||
    payload?.accessTokens?.[0]?.account?.accountId ||
    ""
  );
}

async function meshPost(path, body) {
  if (!apiBase) {
    throw new Error("API base URL is not configured");
  }
  const resp = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(data?.error || `Request failed (${resp.status})`);
    err.details = data;
    err.status = resp.status;
    throw err;
  }
  return data;
}

function ensureConfigured() {
  const problems = [];
  if (!apiBase) problems.push("Missing API base URL (window.APP_CONFIG.apiBase).");
  if (!clientId) problems.push("Missing Mesh client ID (window.APP_CONFIG.meshClientId).");
  if (problems.length) {
    setStatus(problems.join(" "), "error");
    if (connectBtn) connectBtn.disabled = true;
    if (payBtn) payBtn.disabled = true;
    if (portfolioBtn) portfolioBtn.disabled = true;
    return false;
  }
  return true;
}

const meshLink = ensureConfigured()
  ? createLink({
      clientId,
      onIntegrationConnected: (payload) => {
        log("onIntegrationConnected", payload);
        const token = pickAuthToken(payload);
        const accountId = pickAccountId(payload);
        rememberAuth({ token, accountId });
        log("pickedAuthDetails", {
          latestAuthToken: token ? "[set]" : null,
          latestAccountId: accountId || null,
        });
        setDiagnostics("");
        window.alert("Connected! Use MFA code 123456 in the sandbox when prompted.");
      },
      onTransferFinished: (result) => {
        log("onTransferFinished", result || {});
        if (result?.status === "success") {
          window.alert(`USDC transfer completed.\nTxId: ${result.txId || "(see logs)"}`);
        } else if (result) {
          window.alert(`Transfer finished with status ${result.status || "unknown"}`);
        }
      },
      onExit: (err, summary) => {
        log("onExit", { err, summary });
        setStatus("Mesh Link closed.");
      },
      onEvent: (name, metadata) => log(`onEvent:${name}`, metadata || {}),
    })
  : null;

async function handleConnectClick() {
  if (!ensureConfigured()) return;
  setStatus("Requesting Mesh link token...");
  setDiagnostics("");
  connectBtn.disabled = true;
  try {
    const resp = await meshPost("/mesh/link-token/connect");
    log("link-token/connect", resp);
    const token = resp?.content?.linkToken || resp?.linkToken || resp?.token;
    if (!token) {
      throw new Error("Mesh did not return a linkToken. Check diagnostics or secret configuration.");
    }
    meshLink?.openLink(token);
    setStatus("Mesh Link opened — complete the Coinbase flow.");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Failed to launch Mesh Link", "error");
    setDiagnostics(err.details || err.message);
  } finally {
    connectBtn.disabled = false;
  }
}

async function handlePayClick() {
  if (!ensureConfigured()) return;
  setStatus("Preparing transfer Link token...");
  setDiagnostics("");
  payBtn.disabled = true;
  try {
    const resp = await meshPost("/mesh/link-token/pay");
    log("link-token/pay", resp);
    const token = resp?.content?.linkToken || resp?.linkToken || resp?.token;
    if (!token) {
      throw new Error("Mesh did not return a linkToken for payment.");
    }
    meshLink?.openLink(token);
    window.alert("When prompted, use sandbox MFA code 123456 to approve the transfer.");
    setStatus("Mesh Link opened for payment.");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Failed to prepare transfer", "error");
    setDiagnostics(err.details || err.message);
  } finally {
    payBtn.disabled = false;
  }
}

async function handlePortfolioClick() {
  if (!ensureConfigured()) return;
  const authToken = (accessTokenInput?.value || state.latestAuthToken || "").trim();
  if (!authToken) {
    setStatus("Connect first to obtain an auth token.", "error");
    return;
  }

  const accountId = accountIdInput?.value.trim() || state.latestAccountId || undefined;
  const type = portfolioTypeInput?.value.trim() || "coinbase";

  setStatus("Requesting portfolio...");
  try {
    const resp = await meshPost("/mesh/portfolio", {
      authToken,
      accountId,
      type,
    });
    log("portfolio", resp);
    setStatus("Portfolio retrieved.", "success");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Portfolio request failed", "error");
    setDiagnostics(err.details || err.message);
  }
}

function handleClear() {
  if (outputEl) {
    outputEl.textContent = "";
  }
  setStatus("Cleared output.");
}

connectBtn?.addEventListener("click", handleConnectClick);
payBtn?.addEventListener("click", handlePayClick);
portfolioBtn?.addEventListener("click", handlePortfolioClick);
clearBtn?.addEventListener("click", handleClear);

if (ensureConfigured() && !state.latestAuthToken) {
  setStatus("Ready — connect your Coinbase sandbox account to begin.");
}
