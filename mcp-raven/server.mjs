import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { spawn } from "node:child_process";

// ── Config ──────────────────────────────────────────────────────────────
const SSH_HOST = process.env.DRAGON_HOST || "192.168.1.111";
const SSH_USER = process.env.DRAGON_USER || "kama";
const SSH_KEY  = process.env.DRAGON_KEY  || `${process.env.USERPROFILE || process.env.HOME}/.ssh/id_ed25519`;
const SUDO_PW  = process.env.DRAGON_SUDO || "";
const CMD_TIMEOUT = parseInt(process.env.DRAGON_TIMEOUT || "30000", 10);
const RAVEN_PORT = process.env.RAVEN_PORT || "8080";
const RAVEN_URL = `http://${SSH_HOST}:${RAVEN_PORT}`;

// ── SSH helper (kept for direct shell access) ───────────────────────────
function sshExec(command, { timeout = CMD_TIMEOUT, sudo = false } = {}) {
  return new Promise((resolve, reject) => {
    const actualCmd = sudo && SUDO_PW
      ? `echo '${SUDO_PW.replace(/'/g, "'\\''")}' | sudo -S bash -c ${shellQuote(command)} 2>&1`
      : sudo ? `sudo ${command}` : command;

    const args = [
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=5",
      "-o", "StrictHostKeyChecking=accept-new",
      "-i", SSH_KEY,
      `${SSH_USER}@${SSH_HOST}`,
      actualCmd,
    ];

    const proc = spawn("ssh", args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "", stderr = "", killed = false;

    const timer = setTimeout(() => { killed = true; proc.kill("SIGTERM"); }, timeout);

    proc.stdout.on("data", (d) => { stdout += d.toString(); });
    proc.stderr.on("data", (d) => { stderr += d.toString(); });

    proc.on("close", (code) => {
      clearTimeout(timer);
      if (killed) {
        resolve({ code: -1, stdout, stderr: stderr + "\n[TIMEOUT]" });
      } else {
        resolve({ code: code ?? -1, stdout, stderr });
      }
    });
    proc.on("error", reject);
  });
}

function shellQuote(s) {
  return "'" + s.replace(/'/g, "'\"'\"'") + "'";
}

// ── API helper ──────────────────────────────────────────────────────────
async function ravenAPI(path, method = "GET", body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${RAVEN_URL}/api${path}`, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ── MCP Server ──────────────────────────────────────────────────────────
const server = new McpServer({
  name: "raven-sigint",
  version: "0.1.0",
});

// 1. Direct shell exec (legacy, still useful)
server.tool(
  "raven_exec",
  "Execute a shell command on the Dragon box via SSH",
  {
    command: z.string().describe("Shell command to execute"),
    sudo: z.boolean().default(false).describe("Run with sudo"),
    timeout: z.number().default(CMD_TIMEOUT).describe("Timeout in ms"),
  },
  async ({ command, sudo, timeout }) => {
    const r = await sshExec(command, { timeout, sudo });
    return { content: [{ type: "text", text: `[exit: ${r.code}]\n${r.stdout}${r.stderr}` }] };
  }
);

// 2. Platform status
server.tool(
  "raven_status",
  "Get Recon-Raven platform health status (devices, GPS, active captures)",
  {},
  async () => {
    try {
      const health = await ravenAPI("/health");
      const devices = await ravenAPI("/devices");
      const gps = await ravenAPI("/gps/current");
      const captures = await ravenAPI("/captures/active");

      let text = `=== Recon-Raven Status ===\n`;
      text += `Uptime: ${Math.round(health.uptime_s)}s\n`;
      text += `Devices: ${health.devices}\n`;
      text += `GPS: ${gps.has_fix ? `${gps.latitude.toFixed(6)}, ${gps.longitude.toFixed(6)} (${gps.satellites} sats)` : "No fix"}\n`;
      text += `Active captures: ${captures.length}\n\n`;

      text += `--- Devices ---\n`;
      for (const d of devices) {
        text += `  [${d.sdr_index}] ${d.model} (${d.device_type}) — ${d.status}${d.assigned_task ? ` [${d.assigned_task}]` : ""}\n`;
      }

      if (captures.length > 0) {
        text += `\n--- Active Captures ---\n`;
        for (const c of captures) {
          text += `  [${c.task_id}] ${c.task_type} on SDR ${c.sdr_index} @ ${c.freq_mhz} MHz — ${c.status}\n`;
        }
      }

      return { content: [{ type: "text", text }] };
    } catch (e) {
      return { content: [{ type: "text", text: `[ERROR] ${e.message}\nIs Raven running on ${RAVEN_URL}?` }] };
    }
  }
);

// 3. Start capture
server.tool(
  "raven_capture_start",
  "Start a capture task (burst_detect, squelch_record, power_sweep, signal_alert, baseline_capture)",
  {
    task_type: z.string().describe("Task type"),
    sdr_index: z.number().default(0).describe("SDR device index"),
    freq_mhz: z.number().default(433.92).describe("Frequency in MHz"),
    duration: z.number().default(0).describe("Duration in seconds (0=continuous)"),
    gain: z.number().default(38).describe("RF gain"),
    squelch: z.number().default(-40).describe("Squelch threshold dB"),
    threshold: z.number().default(-40).describe("Alert threshold dB"),
  },
  async ({ task_type, sdr_index, freq_mhz, duration, gain, squelch, threshold }) => {
    try {
      const result = await ravenAPI("/captures/start", "POST", {
        task_type, sdr_index, freq_mhz, duration, gain, squelch, threshold,
      });
      return { content: [{ type: "text", text: `Started: ${result.task_type} (id=${result.task_id}) on SDR ${result.sdr_index} @ ${result.freq_mhz} MHz` }] };
    } catch (e) {
      return { content: [{ type: "text", text: `[ERROR] ${e.message}` }] };
    }
  }
);

// 4. Stop capture
server.tool(
  "raven_capture_stop",
  "Stop a running capture task",
  {
    task_id: z.string().describe("Task ID to stop"),
  },
  async ({ task_id }) => {
    try {
      await ravenAPI(`/captures/${task_id}/stop`, "POST");
      return { content: [{ type: "text", text: `Stopped task ${task_id}` }] };
    } catch (e) {
      return { content: [{ type: "text", text: `[ERROR] ${e.message}` }] };
    }
  }
);

// 5. List events
server.tool(
  "raven_events",
  "Query signal events (bursts, alerts) from the database",
  {
    event_type: z.string().optional().describe("Filter by type: burst, alert"),
    freq: z.number().optional().describe("Filter by frequency MHz"),
    limit: z.number().default(50).describe("Max results"),
  },
  async ({ event_type, freq, limit }) => {
    try {
      let path = `/events?limit=${limit}`;
      if (event_type) path += `&event_type=${event_type}`;
      if (freq) path += `&freq=${freq}`;
      const events = await ravenAPI(path);

      if (events.length === 0) return { content: [{ type: "text", text: "No events found." }] };

      let text = `${events.length} event(s):\n`;
      for (const e of events) {
        text += `  [${e.timestamp}] ${e.event_type} @ ${e.freq_mhz || "?"} MHz`;
        if (e.peak_power_db) text += ` peak=${e.peak_power_db}dB`;
        if (e.duration_ms) text += ` dur=${e.duration_ms}ms`;
        text += `\n`;
      }
      return { content: [{ type: "text", text }] };
    } catch (e) {
      return { content: [{ type: "text", text: `[ERROR] ${e.message}` }] };
    }
  }
);

// 6. SDR status (direct hardware check)
server.tool(
  "raven_sdr_status",
  "Check SDR hardware directly via USB (rtl_test, hackrf_info)",
  {},
  async () => {
    const r = await sshExec("lsusb | grep -iE 'realtek|rtl|hackrf|sdr' && echo '---' && rtl_test -t 2>&1 | head -5 && echo '---' && hackrf_info 2>&1 | head -10 || true", { timeout: 10000 });
    return { content: [{ type: "text", text: r.stdout || r.stderr || "No output" }] };
  }
);

// 7. Device list/control
server.tool(
  "raven_devices",
  "List and manage SDR devices via the Raven API",
  {
    action: z.enum(["list", "enumerate", "health"]).default("list").describe("Action"),
    sdr_index: z.number().optional().describe("Device index (for health check)"),
  },
  async ({ action, sdr_index }) => {
    try {
      if (action === "enumerate") {
        const r = await ravenAPI("/devices/enumerate", "POST");
        return { content: [{ type: "text", text: `Enumerated ${r.count} device(s)` }] };
      }
      if (action === "health" && sdr_index !== undefined) {
        const r = await ravenAPI(`/devices/${sdr_index}/health`);
        return { content: [{ type: "text", text: `Device ${sdr_index}: ${r.healthy ? "healthy" : "ERROR"}` }] };
      }
      // list
      const devices = await ravenAPI("/devices");
      let text = `${devices.length} device(s):\n`;
      for (const d of devices) {
        text += `  [${d.sdr_index}] ${d.model} (${d.device_type}) — ${d.status}\n`;
      }
      return { content: [{ type: "text", text }] };
    } catch (e) {
      return { content: [{ type: "text", text: `[ERROR] ${e.message}` }] };
    }
  }
);

// ── Start ───────────────────────────────────────────────────────────────
const transport = new StdioServerTransport();
await server.connect(transport);
