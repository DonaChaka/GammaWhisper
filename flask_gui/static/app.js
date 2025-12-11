const status = document.getElementById("status");
const waveform = document.querySelector(".waveform");
const bubble = document.getElementById("bubble");

function setStatus(text) {
  status.textContent = text;
}

function startWaveform() {
  const wf = document.querySelector(".waveform");
  wf.classList.remove("hidden");
  wf.style.opacity = "1";
  wf.querySelectorAll("div").forEach(div => {
    div.style.animation = "pulse 1s infinite ease-in-out";
  });

  // Show bubble + add listening glow
  bubble.classList.add("show", "listening");
  bubble.classList.remove("transcribing");
  setStatus("Listening…");
}

function stopWaveform() {
  const wf = document.querySelector(".waveform");
  wf.classList.add("hidden");
  wf.querySelectorAll("div").forEach(div => div.style.animation = "none");

  // Remove listening glow
  bubble.classList.remove("listening");
}

function resetBubble() {
  // Hide waveform and clear status
  const wf = document.querySelector(".waveform");
  wf.classList.add("hidden");
  wf.style.opacity = "1";
  wf.querySelectorAll("div").forEach(div => div.style.animation = "none");
  status.textContent = "";

  // Hide bubble completely
  bubble.classList.remove("show", "listening", "transcribing");
}

window.addEventListener("message", async (event) => {
  const { type } = event.data || {};
  if (type === "transcribing") {
    setStatus("Transcribing…");
    stopWaveform(); // disables glow
    bubble.classList.add("show", "transcribing"); // amber border
    bubble.classList.remove("listening");
  } else if (type === "reset") {
    resetBubble();
  }
});

