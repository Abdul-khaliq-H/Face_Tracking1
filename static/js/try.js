const uploadBtn = document.getElementById('uploadBtn');
const fileInput = document.getElementById('videoFile');
const statusText = document.getElementById('statusText');
const progressBar = document.getElementById('progressBar');
const resultSection = document.getElementById('resultSection');
const resultVideo = document.getElementById('resultVideo');
const downloadLink = document.getElementById('downloadLink');

let pollTimer = null;

function setProgress(value) {
  progressBar.style.width = `${Math.max(0, Math.min(100, value))}%`;
}

async function pollJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  const data = await response.json();

  setProgress(data.progress || 0);
  statusText.textContent = `${data.stage || data.status} (${data.progress || 0}%)`;

  if (data.status === 'completed') {
    clearInterval(pollTimer);
    const resultUrl = `/api/jobs/${jobId}/result`;
    resultVideo.src = resultUrl;
    downloadLink.href = resultUrl;
    resultSection.hidden = false;
    statusText.textContent = 'Completed successfully!';
  }

  if (data.status === 'failed') {
    clearInterval(pollTimer);
    statusText.textContent = `Failed: ${data.error || 'Unknown error'}`;
  }
}

uploadBtn.addEventListener('click', async () => {
  const file = fileInput.files?.[0];

  if (!file) {
    alert('Please choose a video file first.');
    return;
  }

  uploadBtn.disabled = true;
  resultSection.hidden = true;
  setProgress(0);
  statusText.textContent = 'Uploading...';

  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetch('/api/jobs', {
      method: 'POST',
      body: formData,
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || 'Unable to create job');
    }

    statusText.textContent = 'Queued...';
    pollTimer = setInterval(() => pollJob(data.job_id), 1500);
    await pollJob(data.job_id);
  } catch (error) {
    statusText.textContent = `Error: ${error.message}`;
  } finally {
    uploadBtn.disabled = false;
  }
});
