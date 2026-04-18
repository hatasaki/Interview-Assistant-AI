/**
 * Voice Live API connection and transcription.
 * Uses direct WebSocket because the SDK does not serialize
 * input_audio_transcription in session.update events.
 */

let _ws = null;
let _audioContext = null;
let _mediaStream = null;
let _onTranscript = null;

/** Connect to Voice Live API and start transcription via WebSocket. */
export async function startVoiceLive(onTranscript, lang) {
  _onTranscript = onTranscript;
  const speechLang = lang === "en" ? "en" : "ja";

  // Get token from backend
  console.log("[VL] Fetching token...");
  const res = await fetch("/api/voicelive/token");
  const { token, endpoint, model } = await res.json();
  console.log("[VL] Token received. Endpoint:", endpoint, "Model:", model);

  // Build WebSocket URL with Bearer token as 'authorization' query parameter
  // Browser WebSocket API cannot set custom headers. The Voice Live API accepts
  // the Authorization header value as a query parameter named 'authorization'.
  const host = new URL(endpoint).host;
  const wsUrl = `wss://${host}/voice-live/realtime?api-version=2025-10-01&model=${encodeURIComponent(model)}&authorization=${encodeURIComponent("Bearer " + token)}`;
  console.log("[VL] Connecting WebSocket to:", `wss://${host}/voice-live/realtime?api-version=2025-10-01&model=${model}&authorization=Bearer+<redacted>`);

  return new Promise((resolve, reject) => {
    _ws = new WebSocket(wsUrl);

    _ws.onopen = () => {
      console.log("[VL] WebSocket connected");

      // Send session.update with input_audio_transcription
      const sessionUpdate = {
        type: "session.update",
        session: {
          modalities: ["text"],
          input_audio_format: "pcm16",
          input_audio_transcription: {
            model: "azure-speech",
            language: speechLang,
          },
          turn_detection: {
            type: "azure_semantic_vad_multilingual",
            create_response: false,
            silence_duration_ms: 500,
            threshold: 0.5,
            languages: [speechLang],
          },
          input_audio_noise_reduction: {
            type: "azure_deep_noise_suppression",
          },
        },
      };
      _ws.send(JSON.stringify(sessionUpdate));
      console.log("[VL] Session update sent (with input_audio_transcription)");
    };

    _ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      switch (msg.type) {
        case "session.created":
          console.log("[VL] session.created");
          break;

        case "session.updated":
          console.log("[VL] session.updated", JSON.stringify(msg.session?.input_audio_transcription));
          console.log("[VL] turn_detection:", JSON.stringify(msg.session?.turn_detection));
          _startMicrophoneCapture();
          resolve();
          break;

        case "conversation.item.input_audio_transcription.completed":
          console.log("[VL] Transcription:", msg.transcript);
          if (msg.transcript && _onTranscript) {
            _onTranscript(msg.transcript);
          }
          break;

        case "error":
          console.error("[VL] Server error:", msg.error);
          break;

        default:
          if (msg.type?.startsWith("response.")) {
            console.log("[VL] Response event:", msg.type);
          }
          break;
      }
    };

    _ws.onerror = (err) => {
      console.error("[VL] WebSocket error:", err);
      reject(new Error("WebSocket connection failed"));
    };

    _ws.onclose = (event) => {
      console.log("[VL] WebSocket closed:", event.code, event.reason);
    };
  });
}

/** Stop microphone capture and close the Voice Live WebSocket. */
export function stopVoiceLive() {
  if (_mediaStream) {
    _mediaStream.getTracks().forEach((t) => t.stop());
    _mediaStream = null;
  }
  if (_audioContext) {
    _audioContext.close();
    _audioContext = null;
  }
  if (_ws) {
    _ws.close();
    _ws = null;
  }
}

/** Capture microphone audio, convert to PCM16, and stream to the WebSocket. */
async function _startMicrophoneCapture() {
  console.log("[VL] Requesting microphone access...");
  _mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: { sampleRate: 24000, channelCount: 1 },
  });
  console.log("[VL] Microphone access granted.");

  _audioContext = new AudioContext({ sampleRate: 24000 });
  console.log("[VL] AudioContext sampleRate:", _audioContext.sampleRate);
  const source = _audioContext.createMediaStreamSource(_mediaStream);

  await _audioContext.audioWorklet.addModule("/js/pcm-processor.js");
  const workletNode = new AudioWorkletNode(_audioContext, "pcm-processor");

  let audioChunkCount = 0;
  workletNode.port.onmessage = (event) => {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      // Convert PCM16 ArrayBuffer to base64 and send as input_audio_buffer.append
      const base64 = _arrayBufferToBase64(event.data);
      _ws.send(JSON.stringify({
        type: "input_audio_buffer.append",
        audio: base64,
      }));
      audioChunkCount++;
      if (audioChunkCount % 200 === 1) {
        console.log(`[VL] Audio chunks sent: ${audioChunkCount}`);
      }
    }
  };

  source.connect(workletNode);
  workletNode.connect(_audioContext.destination);
  console.log("[VL] Microphone capture pipeline active.");
}

/** Convert an ArrayBuffer of PCM16 audio to a base64 string. */
function _arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}
