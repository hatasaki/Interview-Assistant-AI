/**
 * Internationalization (i18n) module.
 * Supports JP (Japanese) and EN (English) languages.
 */

const translations = {
  ja: {
    // Header
    appTitle: "Interview Assistant AI",

    // Buttons
    btnStart: "開始",
    btnStarting: "開始中...",
    btnStop: "終了",
    btnReport: "レポート表示",
    btnRegister: "インタビュー詳細登録",
    btnGenerateQuestions: "次の質問を生成",
    btnGenerating: "生成中...",
    btnSend: "送信",
    btnCancel: "キャンセル",
    btnSubmit: "登録",
    btnDownload: "ダウンロード",
    btnNewInterview: "新規インタビューを始める",

    // Placeholders
    transcriptPlaceholder: "文字起こしがここに表示されます",
    aiPlaceholder: "AIの提案がここに表示されます",
    chatInputPlaceholder: "質問を入力...",

    // Labels
    referencesTitle: "参照元リンク",
    intervieweeLabel: "対象者:",
    affiliationLabel: "所属:",
    relatedInfoTitle: "関連情報",
    suggestedQuestionsTitle: "次の質問案",
    questionTypeDeepdive: "深堀り",
    questionTypeBroaden: "トピック拡張",
    questionTypeChallenge: "挑戦的",
    chatCardTitle: "チャット",

    // Modal
    modalTitle: "インタビュー詳細登録",
    fieldName: "インタビュー対象者の名前",
    fieldAffiliation: "所属",
    fieldRelatedInfo: "関連情報",
    fieldDuration: "インタビュー時間（分）",
    fieldGoal: "ゴール",

    // Report modal
    reportModalTitle: "インタビューレポート",

    // Messages
    speechError: "音声認識エラー: ",
    startFailed: "開始に失敗しました: ",
  },
  en: {
    // Header
    appTitle: "Interview Assistant AI",

    // Buttons
    btnStart: "Start",
    btnStarting: "Starting...",
    btnStop: "Stop",
    btnReport: "View Report",
    btnRegister: "Register Interview Details",
    btnGenerateQuestions: "Generate Questions",
    btnGenerating: "Generating...",
    btnSend: "Send",
    btnCancel: "Cancel",
    btnSubmit: "Register",
    btnDownload: "Download",
    btnNewInterview: "Start New Interview",

    // Placeholders
    transcriptPlaceholder: "Transcriptions will appear here",
    aiPlaceholder: "AI suggestions will appear here",
    chatInputPlaceholder: "Enter a question...",

    // Labels
    referencesTitle: "Reference Links",
    intervieweeLabel: "Interviewee:",
    affiliationLabel: "Affiliation:",
    relatedInfoTitle: "Related Info",
    suggestedQuestionsTitle: "Suggested Questions",
    questionTypeDeepdive: "Deep Dive",
    questionTypeBroaden: "Broaden",
    questionTypeChallenge: "Challenge",
    chatCardTitle: "Chat",

    // Modal
    modalTitle: "Register Interview Details",
    fieldName: "Interviewee Name",
    fieldAffiliation: "Affiliation",
    fieldRelatedInfo: "Related Information",
    fieldDuration: "Interview Duration (min)",
    fieldGoal: "Goal",

    // Report modal
    reportModalTitle: "Interview Report",

    // Messages
    speechError: "Speech recognition error: ",
    startFailed: "Failed to start: ",
  },
};

const STORAGE_KEY = "interview-assistant-lang";

let _currentLang = localStorage.getItem(STORAGE_KEY) || "ja";
let _onChangeCallbacks = [];

/** Get the current language code ("ja" or "en"). */
export function getLang() {
  return _currentLang;
}

/** Switch the active language and notify all registered callbacks. */
export function setLang(lang) {
  if (lang !== "ja" && lang !== "en") return;
  _currentLang = lang;
  localStorage.setItem(STORAGE_KEY, lang);
  document.documentElement.lang = lang === "ja" ? "ja" : "en";
  for (const cb of _onChangeCallbacks) {
    cb(lang);
  }
}

/** Look up a translation key for the current language. */
export function t(key) {
  return translations[_currentLang]?.[key] || translations["ja"][key] || key;
}

/** Register a callback to be invoked when the language changes. */
export function onLangChange(callback) {
  _onChangeCallbacks.push(callback);
}

/**
 * Apply translations to static DOM elements.
 */
export function applyTranslations() {
  // Buttons
  const btnStart = document.getElementById("btn-start");
  if (btnStart && btnStart.textContent !== t("btnStarting")) {
    btnStart.textContent = t("btnStart");
  }
  const btnStop = document.getElementById("btn-stop");
  if (btnStop) btnStop.textContent = t("btnStop");

  const btnReport = document.getElementById("btn-report");
  if (btnReport) btnReport.textContent = t("btnReport");

  const btnRegister = document.getElementById("btn-register");
  if (btnRegister) btnRegister.textContent = t("btnRegister");

  const btnGenerateQuestions = document.getElementById("btn-generate-questions");
  if (btnGenerateQuestions && btnGenerateQuestions.textContent !== t("btnGenerating")) {
    btnGenerateQuestions.textContent = t("btnGenerateQuestions");
  }

  const btnSend = document.getElementById("btn-send");
  if (btnSend) btnSend.textContent = t("btnSend");

  const chatInput = document.getElementById("chat-input");
  if (chatInput) chatInput.placeholder = t("chatInputPlaceholder");

  // Section titles
  const refsTitle = document.querySelector(".pane-right h3");
  if (refsTitle) refsTitle.textContent = t("referencesTitle");

  // Placeholders (only if still showing placeholder)
  const transcriptArea = document.getElementById("transcript-area");
  const transcriptPlaceholder = transcriptArea?.querySelector(".placeholder");
  if (transcriptPlaceholder) transcriptPlaceholder.textContent = t("transcriptPlaceholder");

  const aiArea = document.getElementById("ai-area");
  const aiPlaceholder = aiArea?.querySelector(".placeholder");
  if (aiPlaceholder) aiPlaceholder.textContent = t("aiPlaceholder");

  // Modal
  const modalTitle = document.querySelector("#modal-overlay .modal h2");
  if (modalTitle) modalTitle.textContent = t("modalTitle");

  const labels = document.querySelectorAll("#interview-form label");
  const labelKeys = ["fieldName", "fieldAffiliation", "fieldRelatedInfo", "fieldDuration", "fieldGoal"];
  labels.forEach((label, i) => {
    if (i < labelKeys.length) {
      const input = label.querySelector("input, textarea");
      const required = label.querySelector(".required");
      label.textContent = "";
      label.append(t(labelKeys[i]) + " ");
      if (required) label.appendChild(required);
      if (input) {
        label.appendChild(document.createTextNode("\n"));
        label.appendChild(input);
      }
    }
  });

  const btnCancel = document.getElementById("btn-cancel-modal");
  if (btnCancel) btnCancel.textContent = t("btnCancel");

  const btnSubmit = document.querySelector("#interview-form button[type='submit']");
  if (btnSubmit) btnSubmit.textContent = t("btnSubmit");

  // Report modal
  const reportTitle = document.querySelector("#report-modal-overlay .modal-header h2");
  if (reportTitle) reportTitle.textContent = t("reportModalTitle");

  const btnDownload = document.getElementById("btn-download-report");
  if (btnDownload) btnDownload.textContent = t("btnDownload");

  // New interview button (if exists)
  const btnNew = document.getElementById("btn-new-interview");
  if (btnNew) btnNew.textContent = t("btnNewInterview");
}
