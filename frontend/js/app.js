/**
 * Main application entry point.
 */

import { initModal } from "./modal.js";
import {
  appendTranscript,
  displayIntervieweeInfo,
  displaySuggestion,
  addReferences,
  displayReport,
} from "./ui.js";
import { startSpeechRecognition, stopSpeechRecognition } from "./speech.js";
import {
  connectWebSocket,
  sendTranscript,
  sendChatMessage,
  sendGenerateQuestions,
  disconnectWebSocket,
} from "./websocket.js";
import { getLang, setLang, t, onLangChange, applyTranslations } from "./i18n.js";

let interviewId = null;
let isRunning = false;

const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const btnReport = document.getElementById("btn-report");
const chatInput = document.getElementById("chat-input");
const btnSend = document.getElementById("btn-send");
const btnGenerateQuestions = document.getElementById("btn-generate-questions");
const btnCloseReport = document.getElementById("btn-close-report");
const btnDownloadReport = document.getElementById("btn-download-report");
const reportOverlay = document.getElementById("report-modal-overlay");
let _lastReportMarkdown = "";

// ── Language toggle ──
const btnLangJa = document.getElementById("btn-lang-ja");
const btnLangEn = document.getElementById("btn-lang-en");

function _updateLangButtons(lang) {
  btnLangJa.classList.toggle("active", lang === "ja");
  btnLangEn.classList.toggle("active", lang === "en");
}

btnLangJa.addEventListener("click", () => setLang("ja"));
btnLangEn.addEventListener("click", () => setLang("en"));

onLangChange((lang) => {
  _updateLangButtons(lang);
  applyTranslations();
});

// Initialize language on load
_updateLangButtons(getLang());
applyTranslations();

// ── Modal registration ──
initModal(async (data) => {
  const res = await fetch("/api/interviews", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const interview = await res.json();
  interviewId = interview.id;

  displayIntervieweeInfo(data.intervieweeName, data.intervieweeAffiliation);
  btnStart.disabled = false;
});

// ── Start interview ──
btnStart.addEventListener("click", async () => {
  if (!interviewId) return;

  try {
    btnStart.disabled = true;
    btnStart.textContent = t("btnStarting");

    await fetch(`/api/interviews/${interviewId}/start`, { method: "POST" });

    // Connect WebSocket to backend
    connectWebSocket(interviewId, {
      onSuggestion: (msg) => displaySuggestion(msg),
      onReferences: (refs) => addReferences(refs),
      onReportReady: () => {
        btnReport.disabled = false;
      },
    }, getLang());

    // Start Speech recognition
    try {
      await startSpeechRecognition((transcript) => {
        appendTranscript(transcript);
        sendTranscript(transcript);
      }, getLang());
    } catch (err) {
      console.error("Speech recognition error:", err);
      appendTranscript("[" + t("speechError") + err.message + "]");
    }

    isRunning = true;
    btnStop.disabled = false;
    chatInput.disabled = false;
    btnSend.disabled = false;
    btnGenerateQuestions.disabled = false;
  } catch (err) {
    console.error("Start error:", err);
    alert(t("startFailed") + err.message);
    btnStart.disabled = false;
  } finally {
    btnStart.textContent = t("btnStart");
  }
});

// ── Stop interview ──
btnStop.addEventListener("click", async () => {
  if (!interviewId) return;

  try {
    stopSpeechRecognition();
  } catch (err) {
    console.error("Stop speech recognition error:", err);
  }

  try {
    await fetch(`/api/interviews/${interviewId}/stop?lang=${encodeURIComponent(getLang())}`, { method: "POST" });
  } catch (err) {
    console.error("Stop API error:", err);
  }

  isRunning = false;
  btnStop.disabled = true;
  chatInput.disabled = true;
  btnSend.disabled = true;
  btnGenerateQuestions.disabled = true;

  // Poll for report completion (WebSocket notification may not arrive)
  pollReportStatus(interviewId);
});

// ── Generate Questions ──
btnGenerateQuestions.addEventListener("click", () => {
  sendGenerateQuestions();
  btnGenerateQuestions.disabled = true;
  btnGenerateQuestions.textContent = t("btnGenerating");
  setTimeout(() => {
    btnGenerateQuestions.disabled = false;
    btnGenerateQuestions.textContent = t("btnGenerateQuestions");
  }, 10000);
});

// ── Chat ──
btnSend.addEventListener("click", () => {
  const text = chatInput.value.trim();
  if (!text) return;
  sendChatMessage(text);
  chatInput.value = "";
});

chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    btnSend.click();
  }
});

// ── Report ──
btnReport.addEventListener("click", async () => {
  if (!interviewId) return;
  const res = await fetch(`/api/interviews/${interviewId}/report`);
  if (res.ok) {
    const report = await res.json();
    _lastReportMarkdown = report.markdownContent;
    displayReport(report.markdownContent);
  }
});

btnDownloadReport.addEventListener("click", () => {
  if (!_lastReportMarkdown) return;
  const blob = new Blob([_lastReportMarkdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `interview-report-${interviewId}.md`;
  a.click();
  URL.revokeObjectURL(url);
});

btnCloseReport.addEventListener("click", () => {
  reportOverlay.hidden = true;
});

// ── Report polling ──
function pollReportStatus(iid) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/interviews/${iid}/report/status`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === "completed" || data.status === "failed") {
        clearInterval(interval);
        btnReport.disabled = false;
        showNewInterviewButton();
      }
    } catch (err) {
      console.error("Report poll error:", err);
    }
  }, 5000);
}

// ── New Interview ──
function showNewInterviewButton() {
  const container = document.querySelector(".report-controls");
  if (container.querySelector("#btn-new-interview")) return;
  const btn = document.createElement("button");
  btn.id = "btn-new-interview";
  btn.className = "btn-primary";
  btn.textContent = t("btnNewInterview");
  btn.style.width = "100%";
  btn.style.marginTop = "8px";
  btn.addEventListener("click", () => {
    location.reload();
  });
  container.appendChild(btn);
}
