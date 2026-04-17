/**
 * UI rendering utilities.
 */

import { t } from "./i18n.js";

const transcriptArea = document.getElementById("transcript-area");
const aiArea = document.getElementById("ai-area");
const referencesList = document.getElementById("references-list");
const intervieweeInfo = document.getElementById("interviewee-info");

let firstTranscript = true;
let firstSuggestion = true;

export function displayIntervieweeInfo(name, affiliation) {
  intervieweeInfo.innerHTML = `
    <div class="info-display">
      <strong>${t("intervieweeLabel")}</strong> ${escapeHtml(name)}<br/>
      <strong>${t("affiliationLabel")}</strong> ${escapeHtml(affiliation)}
    </div>
  `;
}

export function appendTranscript(text, speakerId) {
  if (firstTranscript) {
    transcriptArea.innerHTML = "";
    firstTranscript = false;
  }
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8);
  const entry = document.createElement("div");
  entry.className = "transcript-entry";

  // Speaker indicator dot. Color is derived from speakerId via CSS class.
  // speakerId examples from ConversationTranscriber: "Guest-1", "Guest-2", "Unknown".
  const speakerClass = _speakerClass(speakerId);
  const dot = document.createElement("span");
  dot.className = `speaker-dot ${speakerClass}`;
  dot.textContent = "●";
  if (speakerId) {
    dot.title = speakerId;
  }

  const body = document.createElement("span");
  body.className = "transcript-text";
  body.textContent = `[${ts}] ${text}`;

  entry.appendChild(dot);
  entry.appendChild(body);
  transcriptArea.appendChild(entry);
  transcriptArea.scrollTop = transcriptArea.scrollHeight;
}

function _speakerClass(speakerId) {
  if (!speakerId || speakerId === "Unknown") return "speaker-unknown";
  // Extract trailing digit from e.g. "Guest-1" → "1"
  const m = /(\d+)\s*$/.exec(speakerId);
  if (m) {
    // Cycle through 8 colors for Guest-1 .. Guest-N
    const idx = ((parseInt(m[1], 10) - 1) % 8) + 1;
    return `speaker-${idx}`;
  }
  return "speaker-unknown";
}

export function displaySuggestion(data) {
  if (firstSuggestion) {
    aiArea.innerHTML = "";
    firstSuggestion = false;
  }

  const hasInfo = data.relatedInfo && data.relatedInfo.trim();
  const questions = data.suggestedQuestions || [];
  const hasQuestions = questions.length > 0 && questions.some(q => q.question && q.question.trim());

  // Don't add empty cards
  if (!hasInfo && !hasQuestions) return;

  const card = document.createElement("div");
  card.className = "ai-card";

  let html = "";
  if (data.cardTitle) {
    html += `<h4>${escapeHtml(data.cardTitle)}</h4>`;
  }
  if (hasInfo) {
    if (!data.cardTitle) html += `<h4>${t("relatedInfoTitle")}</h4>`;
    html += `<p>${renderInlineLinks(escapeHtml(data.relatedInfo))}</p>`;
  }

  if (hasQuestions) {
    if (!data.cardTitle) html += `<h4>${t("suggestedQuestionsTitle")}</h4>`;
    html += `<ul>`;
    for (const q of questions) {
      if (!q.question || !q.question.trim()) continue;
      const typeLabel = q.type === "deepdive" ? t("questionTypeDeepdive")
        : q.type === "broaden" ? t("questionTypeBroaden")
        : q.type === "challenge" ? t("questionTypeChallenge")
        : "";
      const badge = typeLabel ? `<span class="question-type-badge type-${escapeHtml(q.type)}">${escapeHtml(typeLabel)}</span> ` : "";
      html += `<li class="question-item">
        ${badge}<strong>${escapeHtml(q.question)}</strong>
        <div class="rationale">${escapeHtml(q.rationale || "")}</div>
      </li>`;
    }
    html += `</ul>`;
  }

  card.innerHTML = html;
  aiArea.appendChild(card);
  aiArea.scrollTop = aiArea.scrollHeight;
}

export function addReferences(references) {
  for (const ref of references) {
    // Skip duplicates
    const existing = referencesList.querySelector(
      `a[href="${CSS.escape(ref.url)}"]`
    );
    if (existing) continue;

    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = ref.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = ref.title || ref.url;
    li.appendChild(a);
    referencesList.appendChild(li);
  }
}

export function displayReport(markdown) {
  const content = document.getElementById("report-content");
  content.innerHTML = renderMarkdown(markdown);
  document.getElementById("report-modal-overlay").hidden = false;
}

function renderInlineLinks(escapedHtml) {
  // Convert markdown-style links [text](url) to clickable <a> tags
  // Input is already HTML-escaped, so we need to match escaped brackets
  return escapedHtml.replace(
    /\[([^\]]+)\]\(((https?:\/\/)[^\)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
}

function renderMarkdown(md) {
  let html = escapeHtml(md);
  // Headers
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Italic
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  // Links
  html = html.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  // Unordered lists
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`);
  // Paragraphs (double newline)
  html = html.replace(/\n\n/g, "</p><p>");
  html = `<p>${html}</p>`;
  // Single newlines to <br>
  html = html.replace(/\n/g, "<br>");
  return html;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
