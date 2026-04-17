/**
 * Backend WebSocket communication.
 */

let _ws = null;
let _onSuggestion = null;
let _onReferences = null;
let _onReportReady = null;

// Silence detection for supplementary info
let _silenceTimer = null;
let _transcriptBuffer = [];
const SILENCE_TIMEOUT = 5000; // 5 seconds of silence triggers supplementary info

export function connectWebSocket(
  interviewId,
  { onSuggestion, onReferences, onReportReady },
  lang
) {
  _onSuggestion = onSuggestion;
  _onReferences = onReferences;
  _onReportReady = onReportReady;

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const langParam = lang ? `lang=${encodeURIComponent(lang)}` : "";
  const url = `${protocol}//${location.host}/ws/interview/${interviewId}?${langParam}`;
  _ws = new WebSocket(url);

  _ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case "agent_suggestion":
        if (_onSuggestion) _onSuggestion(msg);
        if (_onReferences && msg.references && msg.references.length > 0) {
          _onReferences(msg.references);
        }
        break;
      case "agent_references":
        if (_onReferences) _onReferences(msg.references);
        break;
      case "report_ready":
        if (_onReportReady) _onReportReady(msg.reportId);
        break;
    }
  };

  _ws.onclose = () => {
    setTimeout(() => {
      if (_ws?.readyState === WebSocket.CLOSED) {
        connectWebSocket(interviewId, {
          onSuggestion,
          onReferences,
          onReportReady,
        }, lang);
      }
    }, 3000);
  };
}

export function sendTranscript(text, speakerId) {
  if (_ws?.readyState === WebSocket.OPEN) {
    // Save to DB
    _ws.send(JSON.stringify({
      type: "transcript",
      text,
      speakerId: speakerId || "Unknown",
      timestamp: new Date().toISOString(),
    }));

    // Buffer for supplementary info (prefix with speaker so the agent can
    // distinguish who said what).
    const speakerPrefix = speakerId && speakerId !== "Unknown" ? `[${speakerId}] ` : "[Unknown] ";
    _transcriptBuffer.push(`${speakerPrefix}${text}`);

    // Reset silence timer
    if (_silenceTimer) clearTimeout(_silenceTimer);
    _silenceTimer = setTimeout(() => {
      _flushSupplementary();
    }, SILENCE_TIMEOUT);
  }
}

function _flushSupplementary() {
  if (_ws?.readyState === WebSocket.OPEN && _transcriptBuffer.length > 0) {
    const buffered = _transcriptBuffer.join("\n");
    _transcriptBuffer = [];
    _ws.send(JSON.stringify({ type: "supplementary_info", text: buffered }));
  }
}

export function sendChatMessage(content) {
  if (_ws?.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify({ type: "chat_message", content }));
  }
}

export function sendGenerateQuestions() {
  if (_ws?.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify({ type: "generate_questions" }));
  }
}

export function disconnectWebSocket() {
  if (_ws) {
    _ws.close();
    _ws = null;
  }
}
