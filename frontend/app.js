const form = document.querySelector("#storyForm");
const tweetText = document.querySelector("#tweetText");
const authorHandle = document.querySelector("#authorHandle");
const postUrl = document.querySelector("#postUrl");
const storyLength = document.querySelector("#storyLength");
const generateButton = document.querySelector("#generateButton");
const sampleButton = document.querySelector("#sampleButton");
const statusMessage = document.querySelector("#statusMessage");
const previewTitle = document.querySelector("#previewTitle");
const storyPreview = document.querySelector("#storyPreview");
const downloadMarkdown = document.querySelector("#downloadMarkdown");
const downloadDocx = document.querySelector("#downloadDocx");

let currentStory = null;

const demoText =
  "Pakistan has launched a new digital skills initiative to train 100,000 young people in cloud computing, artificial intelligence, cybersecurity, and software development, aiming to strengthen the country's technology workforce and boost IT exports.";
const demoAuthorHandle = "@MoitOfficial";
const demoPostUrl = "https://x.com/MoitOfficial/status/2085985308718563602";

function setStatus(message, isError = false) {
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", isError);
}

function setLoading(isLoading) {
  generateButton.disabled = isLoading;
  generateButton.textContent = isLoading ? "Generating..." : "Generate Story";
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function markdownToHtml(markdown) {
  return markdown
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      if (line.startsWith("### ")) return `<h3>${escapeHtml(line.slice(4))}</h3>`;
      if (line.startsWith("## ")) return `<h2>${escapeHtml(line.slice(3))}</h2>`;
      if (line.startsWith("# ")) return `<h2>${escapeHtml(line.slice(2))}</h2>`;
      if (line.startsWith("- ") || line.startsWith("* ")) {
        return `<p>&bull; ${escapeHtml(line.slice(2))}</p>`;
      }
      return `<p>${escapeHtml(line)}</p>`;
    })
    .join("");
}

function renderStory(story) {
  previewTitle.textContent = story.title;
  storyPreview.classList.remove("empty");

  const rows = story.summary_table
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.pillar)}</td>
          <td>${escapeHtml(item.metric)}</td>
          <td>${escapeHtml(item.purpose)}</td>
        </tr>
      `
    )
    .join("");

  const factsTable = rows
    ? `
      <h2>Key Facts</h2>
      <table class="facts">
        <thead>
          <tr>
            <th>Pillar</th>
            <th>Metric</th>
            <th>Purpose</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `
    : "";

  const lengthLabel = story.story_length === "short" ? "Short brief" : "Full feature";

  const coverImage =
    story.cover_image_base64 && story.cover_image_mime_type
      ? `<img class="cover-image" src="data:${story.cover_image_mime_type};base64,${story.cover_image_base64}" alt="Cover image for: ${escapeHtml(story.title)}" />`
      : "";

  storyPreview.innerHTML = `
    <h1>${escapeHtml(story.title)}</h1>
    <p><strong>${escapeHtml(story.subtitle)}</strong></p>
    ${coverImage}
    <div class="story-meta">
      <p><strong>Source:</strong> ${escapeHtml(story.source_context)}</p>
      <p><strong>Length:</strong> ${escapeHtml(lengthLabel)}</p>
      <p><strong>Word count:</strong> ${escapeHtml(String(story.word_count))}</p>
    </div>
    ${factsTable}
    <h2>Story</h2>
    ${markdownToHtml(story.story_markdown)}
  `;

  downloadMarkdown.disabled = false;
  downloadDocx.disabled = false;
}

function buildPayload() {
  return {
    tweet_text: tweetText.value.trim(),
    author_handle: authorHandle.value.trim(),
    post_url: postUrl.value.trim(),
    output_format: "markdown",
    story_length: storyLength.value || null,
  };
}

async function requestJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "The request failed.");
  }
  return data;
}

async function downloadFile(url, story) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(story),
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || "The download failed.");
  }

  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match ? match[1] : "generated-story";
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

sampleButton.addEventListener("click", () => {
  tweetText.value = demoText;
  authorHandle.value = demoAuthorHandle;
  postUrl.value = demoPostUrl;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setLoading(true);
  setStatus("Generating story and cover image...");

  try {
    const result = await requestJson("/api/v1/generate-story", buildPayload());
    currentStory = result.data;
    renderStory(currentStory);
    setStatus(
      currentStory.cover_image_base64
        ? "Story and cover image generated. Download options are ready."
        : "Story generated. Cover image wasn't available this time, but the story is ready."
    );
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setLoading(false);
  }
});

downloadMarkdown.addEventListener("click", async () => {
  if (!currentStory) return;
  setStatus("Preparing Markdown download...");
  try {
    await downloadFile("/api/v1/export-story-markdown", currentStory);
    setStatus("Markdown file downloaded.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

downloadDocx.addEventListener("click", async () => {
  if (!currentStory) return;
  setStatus("Preparing Word document...");
  try {
    await downloadFile("/api/v1/export-story-docx", currentStory);
    setStatus("Word document downloaded.");
  } catch (error) {
    setStatus(error.message, true);
  }
});
