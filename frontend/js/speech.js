/**
 * Azure Speech SDK — continuous recognition for transcription.
 * Replaces Voice Live API with direct Azure AI Speech ASR.
 *
 * Noise suppression: The Speech SDK's Microsoft Audio Stack (MAS) is not
 * available in JavaScript/browser environments (C#/C++/Java only).
 * Browser-level noise suppression via getUserMedia (WebRTC) is used instead,
 * which is enabled by default in the Speech SDK's fromDefaultMicrophoneInput().
 */

let _recognizer = null;
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
  _recognizer = new sdk.SpeechRecognizer(speechConfig, audioConfig);

  // Final recognized result
  _recognizer.recognized = (_s, e) => {
    if (e.result.reason === sdk.ResultReason.RecognizedSpeech && e.result.text) {
      console.log("[Speech] Recognized:", e.result.text);
      if (_onTranscript) {
        _onTranscript(e.result.text);
      }
    }
  };

  // Intermediate (partial) results — log only
  _recognizer.recognizing = (_s, e) => {
    if (e.result.text) {
      console.log("[Speech] Recognizing:", e.result.text);
    }
  };

  _recognizer.canceled = (_s, e) => {
    console.error("[Speech] Canceled:", e.reason, e.errorDetails);
    if (e.reason === sdk.CancellationReason.Error) {
      console.error("[Speech] Error code:", e.errorCode);
    }
  };

  _recognizer.sessionStopped = () => {
    console.log("[Speech] Session stopped");
  };

  // Start continuous recognition
  return new Promise((resolve, reject) => {
    _recognizer.startContinuousRecognitionAsync(
      () => {
        console.log("[Speech] Continuous recognition started");
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
  if (_recognizer) {
    _recognizer.stopContinuousRecognitionAsync(
      () => {
        console.log("[Speech] Recognition stopped");
        _recognizer.close();
        _recognizer = null;
      },
      (err) => {
        console.error("[Speech] Stop error:", err);
        _recognizer.close();
        _recognizer = null;
      }
    );
  }
}
