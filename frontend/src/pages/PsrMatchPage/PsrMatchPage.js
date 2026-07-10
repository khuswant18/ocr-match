import { useRef, useState } from "react";
import {
  Button,
  CircularProgress,
  Paper,
  Typography,
  Chip,
} from "@mui/material";
import ReceiptLongIcon from "@mui/icons-material/ReceiptLong";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import AppLayout from "../../components/AppLayout/AppLayout";
import httpRequest from "../../httpRequest";
import { useStyles } from "./styles";

const BACKEND_URL =
  process.env.REACT_APP_BACKEND_URL || "http://localhost:4333";

const fmt = (v) =>
  v === null || v === undefined || v === ""
    ? "—"
    : Number(v).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 4,
      });

const STATUS_CHIP = {
  matched: { label: "Amount matched", color: "success" },
  mismatch: { label: "Amount mismatch", color: "error" },
  no_record: { label: "No linked record", color: "warning" },
  no_total_found: { label: "Total unreadable", color: "warning" },
};

const METHOD_LABEL = {
  invoice_num: "invoice number",
  file_name: "file name",
};

const PsrMatchPage = () => {
  const classes = useStyles();
  const fileInputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [showText, setShowText] = useState(false);

  const onPick = (e) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setResult(null);
    setError(null);
  };

  const runMatch = async () => {
    if (!file) return;
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await httpRequest.post(
        `${BACKEND_URL}/api/psr/extract-and-match`,
        formData,
      );
      if (res.data.error) setError(res.data.error);
      else setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  };

  const chip = result ? STATUS_CHIP[result.status] : null;

  return (
    <AppLayout userName="Demo User">
      <div className={classes.content}>
        <div className={classes.header}>
          <Typography className={classes.title}>
            <ReceiptLongIcon
              sx={{ fontSize: 32, verticalAlign: "middle", mr: 1, color: "#854de0" }}
            />
            PSR Amount Match
          </Typography>
          <Typography className={classes.subtitle}>
            Extract the TOTAL from a Payment Summary Report (PaddleOCR) and
            reconcile it against the invoice record linked by filename.
          </Typography>
        </div>

        <div className={classes.selectorRow}>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,application/pdf"
            style={{ display: "none" }}
            onChange={onPick}
          />
          <Button
            variant="outlined"
            className={classes.pickButton}
            startIcon={<UploadFileIcon />}
            onClick={() => fileInputRef.current?.click()}
          >
            {file ? file.name : "Choose PSR (image / PDF)"}
          </Button>

          <Button
            variant="contained"
            className={classes.matchButton}
            onClick={runMatch}
            disabled={!file || loading}
            startIcon={
              loading ? (
                <CircularProgress size={20} color="inherit" />
              ) : (
                <PlayArrowIcon />
              )
            }
          >
            {loading ? "Processing..." : "Extract & Match"}
          </Button>
        </div>

        {error && (
          <div className={classes.errorBanner}>
            <ErrorOutlineIcon sx={{ color: "#c62828", fontSize: 32, mr: 1 }} />
            <Typography sx={{ color: "#c62828", fontWeight: 600 }}>
              {error}
            </Typography>
          </div>
        )}

        {loading && (
          <div className={classes.loader}>
            <CircularProgress size={48} sx={{ color: "#854de0" }} />
          </div>
        )}

        {result && !loading && (
          <>
            {result.status === "matched" ? (
              <div className={classes.matchedBanner}>
                <CheckCircleIcon sx={{ color: "#2e7d32", fontSize: 40, mr: 2 }} />
                <Typography sx={{ color: "#2e7d32", fontWeight: 700, fontSize: "1.2rem" }}>
                  Extracted total matches the invoice record.
                </Typography>
              </div>
            ) : (
              <div className={classes.summaryHeader}>
                {chip && <Chip label={chip.label} color={chip.color} />}
                <Typography sx={{ color: "#666" }}>
                  {result.status === "mismatch" &&
                    "Linked to an invoice record, but the OCR'd total differs from its amount (handwritten totals read unreliably — check the OCR text)."}
                  {result.status === "no_record" &&
                    "No invoice record matched this document's invoice number or file name."}
                  {result.status === "no_total_found" &&
                    "Linked to an invoice record, but the handwritten total could not be read. Verify against the expected amount below."}
                </Typography>
              </div>
            )}

            <div className={classes.summaryGrid}>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Invoice No.</Typography>
                <Typography variant="h4">
                  {result.linked?.[0]?.invoice_num ||
                    result.extracted_invoice_number ||
                    "—"}
                </Typography>
                <Typography sx={{ color: "#888", fontSize: "0.78rem", mt: 0.5 }}>
                  {result.match_method
                    ? `linked via ${METHOD_LABEL[result.match_method] || result.match_method}`
                    : "no record linked"}
                </Typography>
                {result.match_method === "file_name" &&
                  result.extracted_invoice_number &&
                  String(result.extracted_invoice_number) !==
                    String(result.linked?.[0]?.invoice_num) && (
                    <Typography sx={{ color: "#b26a00", fontSize: "0.72rem", mt: 0.3 }}>
                      OCR misread the No. stamp as {result.extracted_invoice_number}
                    </Typography>
                  )}
              </div>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Expected (invoice_amount)</Typography>
                <Typography variant="h4">
                  {result.linked?.length ? fmt(result.linked[0].invoice_amount) : "—"}
                </Typography>
              </div>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Extracted Total (OCR)</Typography>
                <Typography variant="h4">
                  {result.extracted_total != null ? fmt(result.extracted_total) : "—"}
                </Typography>
                {result.extracted_total == null && result.total_raw && (
                  <Typography sx={{ color: "#b26a00", fontSize: "0.78rem", mt: 0.5 }}>
                    OCR read “{result.total_raw}” — unreadable/low confidence
                  </Typography>
                )}
                {result.extracted_total != null && result.total_confidence != null && (
                  <Typography sx={{ color: "#888", fontSize: "0.78rem", mt: 0.5 }}>
                    confidence {Math.round(result.total_confidence * 100)}%
                  </Typography>
                )}
              </div>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Difference</Typography>
                <Typography variant="h4">
                  {result.linked?.length ? fmt(result.linked[0].difference) : "—"}
                </Typography>
              </div>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>OCR Confidence</Typography>
                <Typography variant="h4">{result.average_confidence}%</Typography>
              </div>
            </div>

            {result.linked?.length > 0 && (
              <Paper className={classes.panel} elevation={2} sx={{ mt: 3, p: 2 }}>
                <Typography variant="h6" sx={{ mb: 1.5, fontWeight: 600, color: "#333" }}>
                  Linked Invoice Record{result.linked.length > 1 ? "s" : ""}
                </Typography>
                {result.linked.map((row, i) => (
                  <div key={i} className={classes.linkRow}>
                    <Chip
                      size="small"
                      label={row.within_tolerance ? "match" : "no match"}
                      color={row.within_tolerance ? "success" : "error"}
                    />
                    <span>
                      <b>{row.reference_number || row.invoice_num || row.file_name}</b>
                      {" — invoice_amount "}
                      {fmt(row.invoice_amount)}
                      {" · Δ "}
                      {fmt(row.difference)}
                    </span>
                  </div>
                ))}
              </Paper>
            )}

            <Paper className={classes.panel} elevation={2} sx={{ mt: 3, p: 2 }}>
              <div className={classes.candidateRow}>
                <Typography sx={{ fontWeight: 600, color: "#333" }}>
                  Numeric candidates found:
                </Typography>
                {(result.candidates || []).slice(0, 12).map((c, i) => (
                  <Chip key={i} size="small" variant="outlined" label={fmt(c)} />
                ))}
                {(!result.candidates || result.candidates.length === 0) && (
                  <Typography sx={{ color: "#888" }}>none</Typography>
                )}
              </div>
              <Button
                size="small"
                sx={{ mt: 1, textTransform: "none" }}
                onClick={() => setShowText((s) => !s)}
              >
                {showText ? "Hide" : "Show"} raw OCR text
              </Button>
              {showText && <pre className={classes.ocrText}>{result.ocr_text}</pre>}
            </Paper>
          </>
        )}
      </div>
    </AppLayout>
  );
};

export default PsrMatchPage;
