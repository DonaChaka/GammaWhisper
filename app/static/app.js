const status = document.getElementById("status");
const waveform = document.querySelector(".waveform");

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
}

function stopWaveform() {
  const wf = document.querySelector(".waveform");
  wf.classList.add("hidden")
  wf.querySelectorAll("div").forEach(div => div.style.animation = "none");
  // wf.style.opacity = "0.3";
}

function resetBubble() {
  // Hide waveform and clear status
  const wf = document.querySelector(".waveform");
  wf.classList.add("hidden");
  wf.style.opacity = "1";
  wf.querySelectorAll("div").forEach(div => div.style.animation = "none");
  status.textContent = "";
  // Hide bubble
  document.getElementById("bubble").classList.remove("show");
}

window.addEventListener("message", async (event) => {
  const { type } = event.data || {};
  if (type === "transcribing") {
    setStatus("Transcribing…");
    stopWaveform();
  } else if (type === "reset") {
    // Return to initial state
    resetBubble();
  }
});

