import {
	extractTextAndCoordinates,
	sortBoxesReadingOrder,
	groupBoxesIntoRows,
	findNearestRightBox,
	filterBoxesByRegion,
} from "./utils/boundingBoxUtils";

const sampleOcrData = [
	[[[900, 200], [1080, 200], [1080, 250], [900, 250]], ["11/05/2025", 0.96]],
	[[[120, 82], [460, 82], [460, 140], [120, 140]], ["VIRGINIA FOOD,INC.", 0.94]],
	[[[120, 300], [520, 300], [520, 350], [120, 350]], ["Happy Booster Hotdog Regular", 0.92]],
	[[[600, 300], [670, 300], [670, 350], [600, 350]], ["2", 0.95]],
	[[[720, 300], [860, 300], [860, 350], [720, 350]], ["2333.28", 0.97]],
	[[[120, 200], [300, 200], [300, 250], [120, 250]], ["Invoice No", 0.99]],
	[[[1200, 82], [1550, 82], [1550, 140], [1200, 140]], ["SALES INVOICE", 0.93]],
	[[[330, 200], [500, 200], [500, 250], [330, 250]], ["163002", 0.98]],
	[[[120, 200], [300, 200], [300, 250], [120, 250]], ["Invoice No", 0.99]],
	[[[120, 860], [400, 860], [400, 900], [120, 900]], ["REMARKS", 0.9]],
	["bad-shape", ["oops", 0.1]],
];

describe("bounding box utilities", () => {
	test("extracts valid text and coordinates, ignoring malformed OCR items", () => {
		const boxes = extractTextAndCoordinates(sampleOcrData);

		expect(boxes.length).toBe(10);
		expect(boxes[0]).toMatchObject({ text: "11/05/2025" });
		expect(boxes[0].points).toEqual([
			[900, 200],
			[1080, 200],
			[1080, 250],
			[900, 250],
		]);
		expect(boxes[0].left).toBe(900);
		expect(boxes[0].top).toBe(200);
	});

	test("returns empty array on empty or invalid input", () => {
		expect(extractTextAndCoordinates([])).toEqual([]);
		expect(extractTextAndCoordinates(null)).toEqual([]);
		expect(extractTextAndCoordinates(undefined)).toEqual([]);
	});

	test("sorts boxes in reading order: top-to-bottom then left-to-right", () => {
		const boxes = extractTextAndCoordinates(sampleOcrData);
		const sorted = sortBoxesReadingOrder(boxes, 15);
		const sortedTexts = sorted.map((b) => b.text);

		const expectedSortedOutput = [
			"VIRGINIA FOOD,INC.",
			"SALES INVOICE",
			"Invoice No",
			"Invoice No",
			"163002",
			"11/05/2025",
			"Happy Booster Hotdog Regular",
			"2",
			"2333.28",
			"REMARKS",
		];

		expect(sortedTexts).toEqual(expectedSortedOutput);
	});

	test("sorting is deterministic for overlapping boxes", () => {
		const overlapping = extractTextAndCoordinates([
			[[[10, 10], [30, 10], [30, 30], [10, 30]], ["A", 1]],
			[[[10, 10], [30, 10], [30, 30], [10, 30]], ["B", 1]],
		]);

		const sorted1 = sortBoxesReadingOrder(overlapping).map((b) => b.text);
		const sorted2 = sortBoxesReadingOrder(overlapping).map((b) => b.text);
		expect(sorted1).toEqual(sorted2);
		expect(sorted1).toEqual(["A", "B"]);
	});

	test("groups boxes into rows based on Y proximity", () => {
		const boxes = extractTextAndCoordinates(sampleOcrData);
		const rows = groupBoxesIntoRows(boxes, 20);
		const groupedTexts = rows.map((row) => row.map((b) => b.text));

		const expectedGroupedRows = [
			["VIRGINIA FOOD,INC.", "SALES INVOICE"],
			["Invoice No", "Invoice No", "163002", "11/05/2025"],
			["Happy Booster Hotdog Regular", "2", "2333.28"],
			["REMARKS"],
		];

		expect(groupedTexts).toEqual(expectedGroupedRows);
	});

	test("finds nearest box to the right of label 'Invoice No'", () => {
		const boxes = sortBoxesReadingOrder(extractTextAndCoordinates(sampleOcrData), 15);
		const right = findNearestRightBox("Invoice No", boxes, { maxVerticalDistance: 30 });

		expect(right).not.toBeNull();
		expect(right.text).toBe("163002");
	});

	test("returns null when nearest-right candidate does not exist", () => {
		const boxes = extractTextAndCoordinates(sampleOcrData);
		const right = findNearestRightBox("UNKNOWN LABEL", boxes);
		expect(right).toBeNull();
	});

	test("filters boxes by top, bottom, and right regions", () => {
		const boxes = extractTextAndCoordinates(sampleOcrData);

		const top = filterBoxesByRegion(boxes, "top", 1600, 1000).map((b) => b.text);
		const bottom = filterBoxesByRegion(boxes, "bottom", 1600, 1000).map((b) => b.text);
		const right = filterBoxesByRegion(boxes, "right", 1600, 1000).map((b) => b.text);

		expect(top).toEqual(
			expect.arrayContaining([
				"VIRGINIA FOOD,INC.",
				"SALES INVOICE",
				"11/05/2025",
				"Invoice No",
				"163002",
			])
		);
		expect(top).not.toContain("REMARKS");
		expect(bottom).toEqual(["REMARKS"]);
		expect(right).toContain("SALES INVOICE");
		expect(right).toContain("11/05/2025");
	});
});
