const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const axios = require("axios");
const FormData = require("form-data");

const OCR_URL = process.env.OCR_URL || "http://localhost:5001/paddleOCR";
const INPUT_FILE = process.env.OCR_FILE || path.resolve(__dirname, "../../sample1.pdf");

function runCommand(cmd, args) {
  execFileSync(cmd, args, { stdio: "ignore" });
}

function ensureFileExists(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Input file not found: ${filePath}`);
  }
}

function toImageForOcr(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext !== ".pdf") {
    return { imagePath: filePath, originalIsPdf: false };
  }

  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "ocr-match-"));
  const outputBase = path.join(tempDir, "page1");
  const outputPng = `${outputBase}.png`;

  try {
    runCommand("pdftoppm", ["-png", "-f", "1", "-singlefile", filePath, outputBase]);
    if (fs.existsSync(outputPng)) {
      return { imagePath: outputPng, originalIsPdf: true };
    }
  } catch (err) {
    // Fallback below.
  }

  try {
    runCommand("sips", ["-s", "format", "png", filePath, "--out", outputPng]);
    if (fs.existsSync(outputPng)) {
      return { imagePath: outputPng, originalIsPdf: true };
    }
  } catch (err) {
    // handled below
  }

  throw new Error(
    "Failed to convert PDF to image. Install poppler (pdftoppm) or ensure sips can convert your PDF."
  );
}

async function callPaddleOcr() {
  ensureFileExists(INPUT_FILE);

  const { imagePath, originalIsPdf } = toImageForOcr(INPUT_FILE);
  const form = new FormData();

  form.append("file", fs.createReadStream(imagePath), path.basename(imagePath));

  if (originalIsPdf) {
    form.append("pdf", fs.createReadStream(INPUT_FILE), path.basename(INPUT_FILE));
  } else {
    form.append("image", fs.createReadStream(INPUT_FILE), path.basename(INPUT_FILE));
  }

  let data;
  try {
    const response = await axios.post(OCR_URL, form, {
      headers: form.getHeaders(),
      maxBodyLength: Infinity,
      timeout: 180000,
      validateStatus: () => true,
    });

    data = response.data;

    if (response.status < 200 || response.status >= 300) {
      throw new Error(`Request failed (${response.status}): ${JSON.stringify(data, null, 2)}`);
    }
  } catch (error) {
    if (error.response) {
      throw new Error(
        `Request failed (${error.response.status}): ${JSON.stringify(error.response.data, null, 2)}`
      );
    }
    throw new Error(`OCR request error: ${error.message}`);
  }

  if (!Array.isArray(data.paddle_boxes)) {
    throw new Error("Expected paddle_boxes array in OCR response.");
  }

  return data.paddle_boxes;
}

function toNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function extractBoxes(paddleBoxes) {
  if (!Array.isArray(paddleBoxes)) {
    return [];
  }

  return paddleBoxes
    .filter((item) => Array.isArray(item) && Array.isArray(item[0]) && Array.isArray(item[1]))
    .map((item, index) => {
      const points = item[0]
        .filter((p) => Array.isArray(p) && p.length === 2)
        .map((p) => [toNumber(p[0]), toNumber(p[1])]);

      const safePoints = points.filter((p) => p[0] !== null && p[1] !== null);
      const xs = safePoints.map((p) => p[0]);
      const ys = safePoints.map((p) => p[1]);

      const left = xs.length ? Math.min(...xs) : 0;
      const right = xs.length ? Math.max(...xs) : 0;
      const top = ys.length ? Math.min(...ys) : 0;
      const bottom = ys.length ? Math.max(...ys) : 0;

      return {
        id: index,
        value: String(item[1][0] ?? ""),
        confidence: toNumber(item[1][1]),
        box: safePoints,
        left,
        right,
        top,
        bottom,
        centerY: (top + bottom) / 2,
      };
    });
}

function findClosestInvoiceNumber(boxes) {
  const invoiceLabelRegex = /(invoice\s*(no|number|#)?|inv\.?\s*no|\bno\.?\b)/i;
  const hasDigits = /\d{3,}/;

  const labels = boxes
    .filter((b) => invoiceLabelRegex.test(b.value))
    .filter((b) => {
      if (/invoice|inv\.?/i.test(b.value)) {
        return true;
      }
      // For generic "No" labels, keep only likely header-region candidates.
      return b.top < 450;
    });
  if (labels.length === 0) {
    return null;
  }

  const rankedLabels = [...labels].sort((a, b) => {
    const scoreA = /invoice/i.test(a.value) ? 2 : 1;
    const scoreB = /invoice/i.test(b.value) ? 2 : 1;
    return scoreB - scoreA;
  });

  for (const label of rankedLabels) {
    const inlineMatch = label.value.match(/\d{3,}/);
    if (inlineMatch) {
      return {
        label,
        closest: {
          id: label.id,
          value: inlineMatch[0],
          confidence: label.confidence,
          box: label.box,
        },
        mode: "inline",
      };
    }

    const rightCandidates = boxes
      .filter((b) => b.id !== label.id)
      .filter((b) => b.left >= label.right - 2)
      .filter((b) => Math.abs(b.centerY - label.centerY) <= 80)
      .filter((b) => hasDigits.test(b.value))
      .sort((a, b) => {
        const dxA = a.left - label.right;
        const dxB = b.left - label.right;
        if (dxA !== dxB) {
          return dxA - dxB;
        }
        return Math.abs(a.centerY - label.centerY) - Math.abs(b.centerY - label.centerY);
      });

    if (rightCandidates.length > 0) {
      const candidateDigits = rightCandidates[0].value.match(/\d{3,}/);
      return {
        label,
        closest: {
          ...rightCandidates[0],
          value: candidateDigits ? candidateDigits[0] : rightCandidates[0].value,
        },
        mode: "right-neighbor",
      };
    }
  }

  return null;
}

function findClosestByLabel(boxes, config) {
  const {
    labelRegex,
    valueRegex,
    verticalThreshold = 90,
    headerTopLimit = null,
    preferInline = true,
  } = config;

  const labels = boxes.filter((b) => labelRegex.test(b.value));
  const filteredLabels =
    typeof headerTopLimit === "number"
      ? labels.filter((b) => b.top <= headerTopLimit)
      : labels;

  if (filteredLabels.length === 0) {
    return null;
  }

  for (const label of filteredLabels) {
    if (preferInline) {
      const inlineMatch = label.value.match(valueRegex);
      if (inlineMatch) {
        return {
          label,
          closest: {
            id: label.id,
            value: inlineMatch[0],
            confidence: label.confidence,
            box: label.box,
          },
          mode: "inline",
        };
      }
    }

    const rightCandidates = boxes
      .filter((b) => b.id !== label.id)
      .filter((b) => b.left >= label.right - 2)
      .filter((b) => Math.abs(b.centerY - label.centerY) <= verticalThreshold)
      .filter((b) => valueRegex.test(b.value))
      .sort((a, b) => {
        const dxA = a.left - label.right;
        const dxB = b.left - label.right;
        if (dxA !== dxB) {
          return dxA - dxB;
        }
        return Math.abs(a.centerY - label.centerY) - Math.abs(b.centerY - label.centerY);
      });

    if (rightCandidates.length > 0) {
      const match = rightCandidates[0].value.match(valueRegex);
      return {
        label,
        closest: {
          ...rightCandidates[0],
          value: match ? match[0] : rightCandidates[0].value,
        },
        mode: "right-neighbor",
      };
    }
  }

  return null;
}

function findClosestSoNumber(boxes) {
  return findClosestByLabel(boxes, {
    labelRegex: /(\bso\b|s\.o\.|sales\s*order)/i,
    valueRegex: /\d{6,}/,
    verticalThreshold: 45,
    headerTopLimit: 500,
    preferInline: false,
  });
}

function findClosestPoNumber(boxes) {
  return findClosestByLabel(boxes, {
    labelRegex: /(\bpo\b|p\.o\.|purchase\s*order)/i,
    valueRegex: /\d{6,}/,
    verticalThreshold: 45,
    headerTopLimit: 550,
    preferInline: false,
  });
}

function findClosestTin(boxes) {
  return findClosestByLabel(boxes, {
    labelRegex: /\btin\b|vat\s*reg\.?\s*tin/i,
    valueRegex: /\d{3}-\d{3}-\d{3}-\d{5}|\d{9,}/,
    verticalThreshold: 120,
    headerTopLimit: 700,
    preferInline: true,
  });
}

function printBoxes(boxes) {
  if (!boxes.length) {
    console.log("No paddle_boxes found in OCR response.");
    return;
  }

  console.log(`Total boxes: ${boxes.length}`);
  console.log("\nOutput: value, bounding_box, confidence_score\n");

  boxes.forEach((box, index) => {
    const confidenceText = box.confidence === null ? "N/A" : box.confidence.toFixed(4);
    console.log(
      `[${index + 1}] value="${box.value}" | bounding_box=${JSON.stringify(
        box.box
      )} | confidence_score=${confidenceText}`
    );
  });
}

function printInvoiceNumberMatch(result) {
  console.log("\nClosest match for label: \"invoice number\"");

  if (!result) {
    console.log("No invoice label/value pair found.");
    return;
  }

  const closestConfidence =
    result.closest.confidence === null ? "N/A" : result.closest.confidence.toFixed(4);

  console.log(`label_value="${result.label.value}"`);
  console.log(`label_bounding_box=${JSON.stringify(result.label.box)}`);
  console.log(
    `closest_value="${result.closest.value}" | bounding_box=${JSON.stringify(
      result.closest.box
    )} | confidence_score=${closestConfidence}`
  );
  console.log(`invoice_number="${result.closest.value}"`);
  console.log(`match_mode=${result.mode}`);
}

function printGenericFieldMatch(fieldLabel, outputKey, result) {
  console.log(`\nClosest match for label: "${fieldLabel}"`);

  if (!result) {
    console.log(`No ${fieldLabel} label/value pair found.`);
    return;
  }

  const closestConfidence =
    result.closest.confidence === null ? "N/A" : result.closest.confidence.toFixed(4);

  console.log(`label_value="${result.label.value}"`);
  console.log(`label_bounding_box=${JSON.stringify(result.label.box)}`);
  console.log(
    `closest_value="${result.closest.value}" | bounding_box=${JSON.stringify(
      result.closest.box
    )} | confidence_score=${closestConfidence}`
  );
  console.log(`${outputKey}="${result.closest.value}"`);
  console.log(`match_mode=${result.mode}`);
}

async function main() {
  try {
    const paddleBoxes = await callPaddleOcr();
    const boxes = extractBoxes(paddleBoxes);
    printBoxes(boxes);

    const invoiceMatch = findClosestInvoiceNumber(boxes);
    printInvoiceNumberMatch(invoiceMatch);

    const soMatch = findClosestSoNumber(boxes);
    printGenericFieldMatch("SO number", "so_number", soMatch);

    const poMatch = findClosestPoNumber(boxes);
    printGenericFieldMatch("PO number", "po_number", poMatch);

    const tinMatch = findClosestTin(boxes);
    printGenericFieldMatch("TIN", "tin", tinMatch);
  } catch (error) {
    console.error("Failed to fetch PaddleOCR data:", error.message);
    process.exit(1);
  }
}

main();
