/**
 * Azure Speech SDK — continuous conversation transcription with speaker diarization.
 *
 * Uses ConversationTranscriber instead of SpeechRecognizer so that each final
 * transcription result carries a speakerId (e.g. "Guest-1", "Guest-2",
 * "Unknown"). Speaker IDs are assigned by the service via voice clustering
 * from a single microphone input.
 *
 * Noise suppression: The Speech SDK's Microsoft Audio Stack (MAS) is not
 * available in JavaScript/browser environments (C#/C++/Java only).
 * Browser-level noise suppression via getUserMedia (WebRTC) is used instead,
 * which is enabled by default in the Speech SDK's fromDefaultMicrophoneInput().
 */

let _transcriber = null;
let _onTranscript = null;

export async function startSpeechRecognition(onTranscript, lang) {
  _onTranscript = onTranscript;
  const speechLang = lang === "en" ? "en-US" : "ja-JP";

  // Get token from backend
  console.log("[Speech] Fetching token...");
  const res = await fetch("/api/speech/token");
  const { token, region, endpoint } = await res.json();
  console.log("[Speech] Token received. Region:", region, "Endpoint:", endpoint);

  const sdk = window.SpeechSDK;
  if (!sdk) {
    throw new Error("Speech SDK not loaded");
  }

  // For custom domain endpoints (AI Services), use fromEndpoint with a
  // TokenCredential object for Entra ID authentication.
  // The SDK source confirms fromEndpoint(URL, TokenCredential) is supported.
  // Note: services.ai.azure.com is the AI Foundry API domain;
  // Speech SDK requires cognitiveservices.azure.com for its WebSocket paths.
  let speechConfig;
  if (endpoint && (endpoint.includes(".cognitiveservices.azure.com") || endpoint.includes(".services.ai.azure.com"))) {
    // Convert services.ai.azure.com → cognitiveservices.azure.com for Speech SDK
    let speechHost = endpoint;
    if (speechHost.includes(".services.ai.azure.com")) {
      speechHost = speechHost.replace(".services.ai.azure.com", ".cognitiveservices.azure.com");
    }
    const endpointUrl = speechHost.endsWith("/") ? speechHost : speechHost + "/";
    console.log("[Speech] Using custom domain endpoint:", endpointUrl);
    // Create a TokenCredential that returns the Entra ID token from backend
    const tokenCredential = {
      getToken: () => Promise.resolve({ token: token, expiresOnTimestamp: Date.now() + 3600 * 1000 }),
    };
    speechConfig = sdk.SpeechConfig.fromEndpoint(new URL(endpointUrl), tokenCredential);
  } else {
    speechConfig = sdk.SpeechConfig.fromAuthorizationToken(token, region);
  }
  speechConfig.speechRecognitionLanguage = speechLang;

  // Set end-of-silence timeout (ms) — controls how long the service waits
  // after detecting silence before finalizing a recognition result.
  speechConfig.setProperty(
    sdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
    "500"
  );

  const audioConfig = sdk.AudioConfig.fromDefaultMicrophoneInput();
  _transcriber = new sdk.ConversationTranscriber(speechConfig, audioConfig);

  // Final transcription result with speaker identification.
  // speakerId is assigned by the service (e.g. "Guest-1", "Guest-2", "Unknown").
  _transcriber.transcribed = (_s, e) => {
    if (e.result.reason === sdk.ResultReason.RecognizedSpeech && e.result.text) {
      const speakerId = e.result.speakerId || "Unknown";
      console.log("[Speech] Transcribed:", speakerId, e.result.text);
      if (_onTranscript) {
        _onTranscript({ text: e.result.text, speakerId });
      }
    }
  };

  // Intermediate (partial) results — log only
  _transcriber.transcribing = (_s, e) => {
    if (e.result.text) {
      console.log("[Speech] Transcribing:", e.result.speakerId || "Unknown", e.result.text);
    }
  };

  _transcriber.canceled = (_s, e) => {
    console.error("[Speech] Canceled:", e.reason, e.errorDetails);
    if (e.reason === sdk.CancellationReason.Error) {
      console.error("[Speech] Error code:", e.errorCode);
    }
  };

  _transcriber.sessionStopped = () => {
    console.log("[Speech] Session stopped");
  };

  // Start continuous conversation transcription
  return new Promise((resolve, reject) => {
    _transcriber.startTranscribingAsync(
      () => {
        console.log("[Speech] Conversation transcription started");
        resolve();
      },
      (err) => {
        console.error("[Speech] Failed to start:", err);
        reject(new Error(err));
      }
    );
  });
}

export function stopSpeechRecognition() {
  if (_transcriber) {
    _transcriber.stopTranscribingAsync(
      () => {
        console.log("[Speech] Transcription stopped");
        _transcriber.close();
        _transcriber = null;
      },
      (err) => {
        console.error("[Speech] Stop error:", err);
        _transcriber.close();
        _transcriber = null;
      }
    );
  }
}
