#!/usr/bin/env -S deno run -A
/**
 * ElevenLabs Scribe v2 Realtime transcriber - Deno single-file implementation.
 * Captures mic audio, streams to ElevenLabs WebSocket, injects text into active window.
 */

import { encodeBase64 } from "jsr:@std/encoding@1/base64";
import WebSocket from "npm:ws@8";

// --- Constants ---

const SAMPLE_RATE = 16000;
const CHUNK_BYTES = 2048; // 1024 samples * 2 bytes (16-bit)
const SILENCE_TIMEOUT_MS = 5000;
const MAX_DURATION_MS = 300_000; // 5 minutes
const INDICATOR_INTERVAL_MS = 50;
const MONITOR_INTERVAL_MS = 500;
const VAD_SILENCE_SECS = 1.5;

const LOCK_FILE = "/tmp/voice_transcription.pid";
const STOP_FILE = "/tmp/voice_transcription_stop.flag";
const LEVEL_FILE = "/tmp/voice_indicator_level";
const LANG_FILE = "/tmp/voice_transcription_lang";
const LOG_FILE = "/tmp/voice_transcription.log";

const CONTEXT_PROMPT = [
  "Claude", "Claude Code", "Anthropic", "ChatGPT", "OpenAI",
  "Cursor", "Copilot", "LLM", "MCP", "API",
  "Vue", "Nuxt", "React", "Next.js", "Svelte",
  "TypeScript", "JavaScript", "Tailwind", "Vite",
  "pnpm", "npm", "npx", "Node.js", "ESLint", "Prettier",
  "Docker", "GitHub", "Git",
  "Linux", "Cosmic", "Pop!_OS", "PipeWire", "PulseAudio",
  "PostgreSQL", "Prisma", "Redis",
  "refactor", "deploy", "localhost", "webhook",
].join(" ");

const FILLER_RE = /\b(uh|um|er|ah|eh|uhm|hmm|hm|mm)\b/gi;
const AUDIO_EVENT_FULL_RE = /\s*\(\s*\w+\s*\)/g;
const AUDIO_EVENT_OPEN_RE = /\s*\(\s*$/;
const AUDIO_EVENT_CLOSE_RE = /^\s*\w+\s*\)/;
const JUST_ENTER_RE = /(.*)just\s+enter[.\s]*$/i;

// --- Logging ---

let logFd: Deno.FsFile | null = null;

function log(level: string, msg: string) {
  const ts = new Date().toISOString().replace("T", " ").replace("Z", "");
  const line = `${ts} - ${level} - ${msg}`;
  if (level === "ERROR") console.error(line);
  else console.log(line);
  try {
    logFd?.writeSync(new TextEncoder().encode(line + "\n"));
  } catch { /* ignore */ }
}

function info(msg: string) { log("INFO", msg); }
function debug(msg: string) { log("DEBUG", msg); }
function error(msg: string) { log("ERROR", msg); }

// --- Utilities ---

function calcRms(pcm: Uint8Array): number {
  const view = new Int16Array(pcm.buffer, pcm.byteOffset, pcm.byteLength >> 1);
  let sum = 0;
  for (let i = 0; i < view.length; i++) sum += view[i] * view[i];
  return Math.sqrt(sum / view.length);
}

function stripAudioEvents(text: string): string {
  return text
    .replace(AUDIO_EVENT_FULL_RE, "")
    .replace(AUDIO_EVENT_OPEN_RE, "")
    .replace(AUDIO_EVENT_CLOSE_RE, "")
    .trim();
}

function cleanFillers(text: string): string {
  let r = text.replace(FILLER_RE, "");
  r = r.replace(/\s+/g, " ");
  r = r.replace(/\s*,\s*,\s*/g, ", ");
  r = r.replace(/^[,\s]+/, "");
  r = r.replace(/[,\s]+$/, "");
  r = r.replace(/\s+([,.!?;:])/g, "$1");
  return r.trim();
}

function notify(message: string, urgency = "normal") {
  try {
    new Deno.Command("notify-send", {
      args: ["-u", urgency, "Voice Transcription", message],
      stdout: "null", stderr: "null",
    }).spawn();
  } catch { /* ignore */ }
}

async function fileExists(path: string): Promise<boolean> {
  try { await Deno.stat(path); return true; } catch { return false; }
}

function fileExistsSync(path: string): boolean {
  try { Deno.statSync(path); return true; } catch { return false; }
}

async function readTextFile(path: string): Promise<string | null> {
  try { return await Deno.readTextFile(path); } catch { return null; }
}

// --- Instance locking ---

async function acquireLock(): Promise<boolean> {
  if (await fileExists(LOCK_FILE)) {
    const content = await readTextFile(LOCK_FILE);
    if (content) {
      const oldPid = parseInt(content.trim(), 10);
      if (!isNaN(oldPid) && processAlive(oldPid)) {
        info("Another transcription session is already active");
        notify("Already recording", "normal");
        return false;
      }
      info("Removing stale lock file");
    }
    await Deno.remove(LOCK_FILE).catch(() => {});
  }
  await Deno.writeTextFile(LOCK_FILE, String(Deno.pid));
  return true;
}

function releaseLock() {
  try {
    const content = Deno.readTextFileSync(LOCK_FILE);
    if (parseInt(content.trim(), 10) === Deno.pid) {
      Deno.removeSync(LOCK_FILE);
    }
  } catch { /* ignore */ }
}

function processAlive(pid: number): boolean {
  try {
    // Check /proc/{pid}/stat on Linux
    Deno.statSync(`/proc/${pid}/stat`);
    return true;
  } catch {
    return false;
  }
}

// --- Visual indicator ---

function spawnIndicator(): Deno.ChildProcess | null {
  // Initialize level file
  try { Deno.writeTextFileSync(LEVEL_FILE, "0\n"); } catch { /* ignore */ }

  const scriptDir = new URL(".", import.meta.url).pathname;
  const pyScript = scriptDir + "visual_indicator.py";

  if (!fileExistsSync(pyScript)) {
    info("Indicator script not found, continuing without visual indicator");
    return null;
  }

  try {
    const proc = new Deno.Command("/usr/bin/python3", {
      args: [pyScript],
      stdin: "null", stdout: "null", stderr: "null",
    }).spawn();
    return proc;
  } catch (e) {
    error(`Failed to spawn indicator: ${e}`);
    return null;
  }
}

let lastLevelWrite = 0;

function updateLevel(volume: number) {
  const now = Date.now();
  if (now - lastLevelWrite < INDICATOR_INTERVAL_MS) return;
  lastLevelWrite = now;
  try {
    const tmp = LEVEL_FILE + ".tmp";
    Deno.writeTextFileSync(tmp, `${volume}\n`);
    Deno.renameSync(tmp, LEVEL_FILE);
  } catch { /* ignore */ }
}

function stopIndicator(proc: Deno.ChildProcess | null) {
  // Signal stop flash
  try { Deno.writeTextFileSync(LEVEL_FILE, "stop\n"); } catch { /* ignore */ }
  // Wait for flash, then kill
  setTimeout(() => {
    try { proc?.kill("SIGTERM"); } catch { /* ignore */ }
    // Cleanup level files
    try { Deno.removeSync(LEVEL_FILE); } catch { /* ignore */ }
    try { Deno.removeSync(LEVEL_FILE + ".tmp"); } catch { /* ignore */ }
  }, 350);
}


// --- Text injection ---

async function injectText(text: string): Promise<boolean> {
  if (!text.trim()) return false;

  const hasTrailingSpace = text.endsWith(" ");
  let cleaned = cleanFillers(text);
  if (!cleaned.trim()) {
    debug(`Skipped injection - only filler words: '${text}'`);
    return false;
  }
  if (hasTrailingSpace && !cleaned.endsWith(" ")) cleaned += " ";

  // Small delay for focus stability
  await new Promise((r) => setTimeout(r, 100));

  // Check for "just enter" command
  const enterMatch = cleaned.trim().match(JUST_ENTER_RE);
  if (enterMatch) {
    const preceding = enterMatch[1].trim();
    const toInject = preceding ? `${preceding} (enter)` : "(enter)";
    await clipboardInject(toInject);
    await new Deno.Command("wtype", { args: ["-k", "Return"], stdout: "null", stderr: "null" }).output();
  } else {
    await clipboardInject(cleaned);
  }

  return true;
}

async function clipboardInject(text: string) {
  // Copy to clipboard via wl-copy
  const wlCopy = new Deno.Command("wl-copy", {
    stdin: "piped", stdout: "null", stderr: "null",
  }).spawn();
  const writer = wlCopy.stdin.getWriter();
  await writer.write(new TextEncoder().encode(text));
  await writer.close();
  await wlCopy.status;

  // Brief delay for clipboard
  await new Promise((r) => setTimeout(r, 50));

  // Paste with Ctrl+Shift+V (works in both terminals and GUI apps on Wayland)
  await new Deno.Command("wtype", {
    args: ["-M", "ctrl", "-M", "shift", "-P", "v", "-m", "shift", "-m", "ctrl"],
    stdout: "null", stderr: "null",
  }).output();
}

// --- Language ---

async function getLanguage(): Promise<string | null> {
  // Check lang file first, fall back to auto
  const content = await readTextFile(LANG_FILE);
  if (content) {
    const lang = content.trim().toLowerCase();
    if (lang === "auto") return null;
    if (lang) return lang;
  }
  return null; // auto-detect
}

// --- Main transcription ---

async function transcribe() {
  // Check Wayland tools are available
  for (const tool of ["wl-copy", "wtype"]) {
    if (!(await findCommand(tool))) {
      error(`Required tool '${tool}' not found. Install wl-clipboard and wtype.`);
      notify(`Missing ${tool} - install wl-clipboard and wtype`, "critical");
      return;
    }
  }

  if (!(await acquireLock())) return;

  const ac = new AbortController();
  let indicatorProc: Deno.ChildProcess | null = null;
  let recorderProc: Deno.ChildProcess | null = null;
  let ws: WebSocket | null = null;
  let fullText = "";
  let lastActivityTime = Date.now();
  async function cleanup() {
    ac.abort();
    try { recorderProc?.kill("SIGTERM"); } catch { /* ignore */ }
    try { ws?.close(); } catch { /* ignore */ }
    stopIndicator(indicatorProc);
    await new Promise((r) => setTimeout(r, 400));
    try { await Deno.remove(STOP_FILE).catch(() => {}); } catch { /* ignore */ }
    releaseLock();
  }

  try {
    const apiKey = Deno.env.get("ELEVENLABS_API_KEY");
    if (!apiKey) {
      error("ELEVENLABS_API_KEY not set");
      notify("No API key configured", "critical");
      releaseLock();
      return;
    }

    // Remove stale stop file
    await Deno.remove(STOP_FILE).catch(() => {});

    // Read language
    const language = await getLanguage();
    info(`Language: ${language ?? "auto-detect"}`);

    // Build WebSocket URL
    const params = new URLSearchParams({
      model_id: "scribe_v2_realtime",
      commit_strategy: "vad",
      vad_silence_threshold_secs: String(VAD_SILENCE_SECS),
      audio_format: `pcm_${SAMPLE_RATE}`,
    });
    if (language) params.set("language_code", language);
    const wsUrl = `wss://api.elevenlabs.io/v1/speech-to-text/realtime?${params}`;

    // Connect WebSocket
    info("Connecting to ElevenLabs WebSocket...");
    ws = new WebSocket(wsUrl, { headers: { "xi-api-key": apiKey } });

    await new Promise<void>((resolve, reject) => {
      ws!.once("open", () => { info("WebSocket connected"); resolve(); });
      ws!.once("error", (e: Error) => reject(e));
      setTimeout(() => reject(new Error("WebSocket connection timeout")), 10_000);
    });

    // Spawn visual indicator
    indicatorProc = spawnIndicator();

    // Find recorder command (prefer pw-record > parecord > arecord)
    const pwRecordPath = await findCommand("pw-record");
    const parecordPath = await findCommand("parecord");
    const arecordPath = await findCommand("arecord");

    let recorderCmd: string[];
    if (pwRecordPath) {
      recorderCmd = [pwRecordPath, "--format=s16", `--rate=${SAMPLE_RATE}`, "--channels=1", "-"];
    } else if (parecordPath) {
      recorderCmd = [parecordPath, "--raw", "--rate", String(SAMPLE_RATE), "--channels", "1", "--format=s16le", "--latency-msec=50"];
    } else if (arecordPath) {
      recorderCmd = [arecordPath, "-q", "-f", "S16_LE", "-r", String(SAMPLE_RATE), "-c", "1", "-t", "raw"];
    } else {
      throw new Error("No audio recorder found. Install pipewire or pulseaudio-utils or alsa-utils.");
    }

    // Spawn recorder
    recorderProc = new Deno.Command(recorderCmd[0], {
      args: recorderCmd.slice(1),
      stdout: "piped", stderr: "null",
    }).spawn();
    info("Audio recorder started");

    const startTime = Date.now();

    // --- Send audio loop ---
    async function sendAudioLoop() {
      const reader = recorderProc!.stdout.getReader();
      let buffer = new Uint8Array(0);
      let firstChunk = true;

      try {
        while (!ac.signal.aborted) {
          const { value, done } = await reader.read();
          if (done || !value) break;

          // Accumulate into buffer
          const newBuf = new Uint8Array(buffer.length + value.length);
          newBuf.set(buffer);
          newBuf.set(value, buffer.length);
          buffer = newBuf;

          // Process full chunks
          while (buffer.length >= CHUNK_BYTES) {
            const chunk = buffer.slice(0, CHUNK_BYTES);
            buffer = buffer.slice(CHUNK_BYTES);

            // Calculate RMS for visual indicator
            updateLevel(calcRms(chunk));

            // Build WS message
            const msg: Record<string, unknown> = {
              message_type: "input_audio_chunk",
              audio_base_64: encodeBase64(chunk),
              commit: false,
              sample_rate: SAMPLE_RATE,
            };
            if (firstChunk && CONTEXT_PROMPT) {
              msg.previous_text = CONTEXT_PROMPT;
              firstChunk = false;
            }

            try {
              ws!.send(JSON.stringify(msg));
            } catch {
              return; // WS closed
            }
          }
        }
      } catch (e) {
        if (!ac.signal.aborted) debug(`Send loop error: ${e}`);
      } finally {
        reader.releaseLock();
      }
    }

    // --- Receive loop ---
    async function receiveLoop() {
      return new Promise<void>((resolve) => {
        // deno-lint-ignore no-explicit-any
        ws!.on("message", async (data: any) => {
          if (ac.signal.aborted) return;
          try {
            const msg = JSON.parse(data.toString());
            const msgType = msg.message_type ?? "";

            if (msgType === "session_started") {
              info(`Session started: ${msg.session_id}`);
            } else if (msgType === "partial_transcript") {
              const text = (msg.text ?? "").trim();
              if (text) {
                lastActivityTime = Date.now();
                debug(`Partial: '${text.slice(0, 60)}'`);
              }
            } else if (msgType === "committed_transcript" || msgType === "committed_transcript_with_timestamps") {
              const text = stripAudioEvents(msg.text ?? "");
              if (text) {
                lastActivityTime = Date.now();
                info(`Committed: '${text}'`);
                if (fullText && !fullText.endsWith(" ")) fullText += " ";
                fullText += text;

                // Inject text
                const injected = await injectText(text + " ");
                if (injected) {
                  info(`Injected: '${text}'`);
                } else {
                  error(`Injection failed: '${text}'`);
                }
              }
            } else if (msgType.includes("error")) {
              error(`WebSocket error: ${msg.error ?? msgType}`);
              ac.abort();
            }
          } catch (e) {
            debug(`Message parse error: ${e}`);
          }
        });
        ws!.on("close", () => resolve());
        ws!.on("error", (e: Error) => {
          if (!ac.signal.aborted) debug(`WebSocket error: ${e.message}`);
          resolve();
        });
        // Also resolve on abort
        ac.signal.addEventListener("abort", () => resolve());
      });
    }

    // --- Monitor loop ---
    async function monitorLoop() {
      while (!ac.signal.aborted) {
        await new Promise((r) => setTimeout(r, MONITOR_INTERVAL_MS));

        // Max duration
        if (Date.now() - startTime > MAX_DURATION_MS) {
          info("Maximum duration reached, stopping...");
          break;
        }

        // Silence timeout (only if we have text)
        const silenceMs = Date.now() - lastActivityTime;
        if (silenceMs > SILENCE_TIMEOUT_MS && fullText.trim()) {
          info(`Silence detected for ${(silenceMs / 1000).toFixed(1)}s, stopping...`);
          break;
        }

        // Stop file (inter-process)
        if (fileExistsSync(STOP_FILE)) {
          info("Stop file detected, stopping...");
          break;
        }
      }
      ac.abort();
    }

    // Run all three loops concurrently
    await Promise.race([
      Promise.all([sendAudioLoop(), receiveLoop(), monitorLoop()]),
      new Promise<void>((resolve) => {
        const sigHandler = () => { info("Interrupted by user"); ac.abort(); resolve(); };
        Deno.addSignalListener("SIGINT", sigHandler);
        Deno.addSignalListener("SIGTERM", sigHandler);
        ac.signal.addEventListener("abort", () => resolve());
      }),
    ]);

    if (fullText.trim()) {
      info(`Transcription complete: '${fullText.trim()}'`);
    } else {
      info("No speech detected");
    }
  } catch (e) {
    error(`Transcription error: ${e}`);
    notify("Transcription failed", "critical");
  } finally {
    await cleanup();
  }
}

async function findCommand(name: string): Promise<string | null> {
  try {
    const result = await new Deno.Command("which", { args: [name], stdout: "piped", stderr: "null" }).output();
    if (result.success) return new TextDecoder().decode(result.stdout).trim();
  } catch { /* ignore */ }
  return null;
}

// --- CLI subcommands ---

async function cmdStop() {
  try {
    await Deno.writeTextFile(STOP_FILE, String(Date.now()));
    // Remove lock for immediate restart
    await Deno.remove(LOCK_FILE).catch(() => {});
    console.log("Stop signal sent");
  } catch (e) {
    console.error(`Error: ${e}`);
  }
}

async function cmdStatus() {
  const apiKey = Deno.env.get("ELEVENLABS_API_KEY");
  if (!apiKey) {
    console.log("ElevenLabs: no API key (set ELEVENLABS_API_KEY)");
    return;
  }
  console.log("Testing ElevenLabs API connectivity...");
  try {
    const resp = await fetch("https://api.elevenlabs.io/v1/models", {
      headers: { "xi-api-key": apiKey },
      signal: AbortSignal.timeout(5000),
    });
    if (resp.ok) {
      console.log("ElevenLabs: connected");
    } else {
      console.log(`ElevenLabs: HTTP ${resp.status}`);
    }
  } catch (e) {
    console.log(`ElevenLabs: connection failed (${e})`);
  }
}

// --- Main ---

async function main() {
  logFd = await Deno.open(LOG_FILE, { write: true, create: true, append: true });

  const cmd = Deno.args[0]?.toLowerCase();

  switch (cmd) {
    case "stop":
      await cmdStop();
      break;
    case "status":
    case "ping":
      await cmdStatus();
      break;
    default:
      await transcribe();
      break;
  }

  logFd.close();
}

main();
