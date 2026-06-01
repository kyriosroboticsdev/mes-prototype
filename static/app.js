// Front-end logic: open camera, capture a frame, send it to the server,
// and display the inventory report that comes back.

const video = document.getElementById("camera");
const canvas = document.getElementById("canvas");
const captureBtn = document.getElementById("captureBtn");
const switchBtn = document.getElementById("switchBtn");
const statusEl = document.getElementById("status");

let currentStream = null;
let useBackCamera = true; // phones: start with the rear camera

// --- Start the camera ------------------------------------------------------
async function startCamera() {
  // Stop any existing stream before switching.
  if (currentStream) {
    currentStream.getTracks().forEach((t) => t.stop());
  }
  try {
    // "facingMode: environment" asks for the rear camera on phones.
    currentStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: useBackCamera ? "environment" : "user" },
      audio: false,
    });
    video.srcObject = currentStream;
  } catch (err) {
    statusEl.textContent =
      "⚠️ Could not access the camera. Please allow camera permission.";
    console.error(err);
  }
}

switchBtn.addEventListener("click", () => {
  useBackCamera = !useBackCamera;
  startCamera();
});

// --- Capture a frame and analyze it ---------------------------------------
captureBtn.addEventListener("click", async () => {
  if (!currentStream) {
    statusEl.textContent = "Camera not ready yet.";
    return;
  }

  // Draw the current video frame onto the hidden canvas, then export as JPEG.
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  const dataUrl = canvas.toDataURL("image/jpeg", 0.85);

  // Show the snapshot preview.
  const preview = document.getElementById("preview");
  preview.src = dataUrl;
  document.getElementById("previewCard").hidden = false;

  // Send to the server.
  captureBtn.disabled = true;
  statusEl.textContent = "🔍 Analyzing photo with AI…";

  try {
    const res = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: dataUrl }),
    });
    const data = await res.json();

    if (data.error) {
      statusEl.textContent = "❌ " + data.error;
    } else {
      statusEl.textContent = "✅ Done!";
      showDetected(data.detected);
      showReport(data.report);
    }
  } catch (err) {
    statusEl.textContent = "❌ Network error — is the server running?";
    console.error(err);
  } finally {
    captureBtn.disabled = false;
  }
});

// --- Render the raw "what the AI saw" list --------------------------------
function showDetected(detected) {
  const list = document.getElementById("detectedList");
  list.innerHTML = "";
  detected.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `${item.count} × ${item.name}`;
    list.appendChild(li);
  });
  document.getElementById("detectedCard").hidden = detected.length === 0;
}

// --- Render the inventory / order report ----------------------------------
function showReport(report) {
  const tbody = document.querySelector("#reportTable tbody");
  tbody.innerHTML = "";

  let needCount = 0;
  report.forEach((row) => {
    const tr = document.createElement("tr");
    if (row.needs_order) {
      tr.classList.add("order-needed");
      needCount++;
    }
    tr.innerHTML = `
      <td>${row.item}</td>
      <td>${row.minimum}</td>
      <td>${row.on_hand}</td>
      <td>${row.order_qty > 0 ? "➕ " + row.order_qty : "—"}</td>`;
    tbody.appendChild(tr);
  });

  const summary = document.getElementById("orderSummary");
  if (needCount === 0) {
    summary.className = "all-good";
    summary.textContent = "✅ All items are sufficiently stocked. No order needed.";
  } else {
    summary.className = "needs-order";
    summary.textContent = `⚠️ ${needCount} item(s) below minimum — order generated.`;
  }

  document.getElementById("reportCard").hidden = false;
}

// Kick things off.
startCamera();
