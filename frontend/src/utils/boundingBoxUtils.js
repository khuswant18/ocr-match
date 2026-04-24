function toNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function isPoint(point) {
  return Array.isArray(point) && point.length === 2 && toNumber(point[0]) !== null && toNumber(point[1]) !== null;
}

function isValidOcrItem(item) {
  if (!Array.isArray(item) || item.length < 2) {
    return false;
  }

  const points = item[0];
  const textInfo = item[1];

  if (!Array.isArray(points) || points.length !== 4 || !points.every(isPoint)) {
    return false;
  }

  if (!Array.isArray(textInfo) || typeof textInfo[0] !== "string") {
    return false;
  }

  return true;
}

export function extractTextAndCoordinates(ocrOutput) {
  if (!Array.isArray(ocrOutput)) {
    return [];
  }

  return ocrOutput
    .filter(isValidOcrItem)
    .map((item, index) => {
      const points = item[0].map((p) => [Number(p[0]), Number(p[1])]);
      const text = item[1][0];
      const confidence = Number(item[1][1] ?? 0);

      const xs = points.map((p) => p[0]);
      const ys = points.map((p) => p[1]);
      const left = Math.min(...xs);
      const right = Math.max(...xs);
      const top = Math.min(...ys);
      const bottom = Math.max(...ys);

      return {
        id: index,
        text,
        confidence,
        points,
        left,
        right,
        top,
        bottom,
        centerX: (left + right) / 2,
        centerY: (top + bottom) / 2,
      };
    });
}

export function sortBoxesReadingOrder(boxes, yTolerance = 12) {
  if (!Array.isArray(boxes) || boxes.length === 0) {
    return [];
  }

  const sorted = [...boxes].sort((a, b) => {
    const rowA = Math.round(a.top / yTolerance);
    const rowB = Math.round(b.top / yTolerance);

    if (rowA !== rowB) {
      return rowA - rowB;
    }

    if (a.left !== b.left) {
      return a.left - b.left;
    }

    // deterministic tie-breaker
    return (a.id ?? 0) - (b.id ?? 0);
  });

  return sorted;
}

export function groupBoxesIntoRows(boxes, yTolerance = 12) {
  const sorted = sortBoxesReadingOrder(boxes, yTolerance);
  if (sorted.length === 0) {
    return [];
  }

  const rows = [];
  let currentRow = [sorted[0]];
  let rowY = sorted[0].centerY;

  for (let i = 1; i < sorted.length; i += 1) {
    const box = sorted[i];
    if (Math.abs(box.centerY - rowY) <= yTolerance) {
      currentRow.push(box);
      rowY = (rowY * (currentRow.length - 1) + box.centerY) / currentRow.length;
    } else {
      rows.push(sortBoxesReadingOrder(currentRow, yTolerance));
      currentRow = [box];
      rowY = box.centerY;
    }
  }

  rows.push(sortBoxesReadingOrder(currentRow, yTolerance));
  return rows;
}

export function findNearestRightBox(labelText, boxes, options = {}) {
  if (!labelText || !Array.isArray(boxes) || boxes.length === 0) {
    return null;
  }

  const maxVerticalDistance = options.maxVerticalDistance ?? 20;
  const normalizedLabel = labelText.trim().toLowerCase();

  const labelBox = boxes.find((box) => box.text.trim().toLowerCase() === normalizedLabel);
  if (!labelBox) {
    return null;
  }

  const candidates = boxes.filter((box) => {
    if ((box.id ?? -1) === (labelBox.id ?? -2)) {
      return false;
    }

    const isRight = box.left >= labelBox.right;
    const verticalDistance = Math.abs(box.centerY - labelBox.centerY);
    return isRight && verticalDistance <= maxVerticalDistance;
  });

  if (candidates.length === 0) {
    return null;
  }

  candidates.sort((a, b) => {
    const dxA = a.left - labelBox.right;
    const dxB = b.left - labelBox.right;

    if (dxA !== dxB) {
      return dxA - dxB;
    }

    return Math.abs(a.centerY - labelBox.centerY) - Math.abs(b.centerY - labelBox.centerY);
  });

  return candidates[0];
}

export function filterBoxesByRegion(boxes, region, pageWidth, pageHeight) {
  if (!Array.isArray(boxes) || boxes.length === 0) {
    return [];
  }

  if (!pageWidth || !pageHeight) {
    return [];
  }

  if (region === "top") {
    const threshold = pageHeight * 0.35;
    return boxes.filter((b) => b.centerY <= threshold);
  }

  if (region === "bottom") {
    const threshold = pageHeight * 0.65;
    return boxes.filter((b) => b.centerY >= threshold);
  }

  if (region === "right") {
    const threshold = pageWidth * 0.6;
    return boxes.filter((b) => b.centerX >= threshold);
  }

  return [];
}
