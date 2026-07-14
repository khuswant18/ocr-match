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

const OUTCOME_TEXT = {
  matched: "Extracted total matches the linked invoice record.",
  mismatch: "Linked to an invoice record, but the OCR'd total differs from its amount.",
  no_record: "No invoice record matched this document's invoice number or file name.",
  no_total_found:
    "Linked to an invoice record, but the total could not be read from the document.",
};

const PsrMatchPage = () => {
  const classes = useStyles();
  const fileInputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const onPick = (e) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setResult(null);
    setError(null);
  };

  // The backend runs OCR asynchronously: POST enqueues a job (202 + job_id),
  // then we poll GET /api/psr/job/<id> until it is completed/failed/cancelled.
  const pollJob = async (id) => {
    try {
      const res = await httpRequest.get(`${BACKEND_URL}/api/psr/job/${id}`);
      const status = res.data.status;
      if (status === "completed") {
        // ocr_data / raw_data / match_summary sit at the top level of the response.
        setResult(res.data);
        setLoading(false);
      } else if (status === "failed" || status === "cancelled") {
        setError(res.data.error || `Job ${status}`);
        setLoading(false);
      } else {
        setTimeout(() => pollJob(id), 1500); // pending / running
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message);
      setLoading(false);
    }
  };

  const runMatch = async () => {
    if (!file) return;
    setLoading(true);
    setResult(null);
    setError(null);
    setJobId(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await httpRequest.post(
        `${BACKEND_URL}/api/psr/extract-and-match`,
        formData,
      );
      setJobId(res.data.job_id);
      pollJob(res.data.job_id);
    } catch (err) {
      setError(err.response?.data?.error || err.message);
      setLoading(false);
    }
  };

  const ms = result?.match_summary || {};
  const ocr = result?.ocr_data || {};
  const rawd = result?.raw_data || null;
  const chip = result ? STATUS_CHIP[ms.outcome] : null;
  const linkedRows = result
    ? [
        ...(rawd
          ? [
              {
                invoice_num: rawd.invoice_num,
                reference_number: rawd.reference_number,
                invoice_amount: rawd.amount,
                invoice_date: rawd.invoice_date,
                file_name: rawd.pdf_name,
                difference: ms.amount_diff,
                within_tolerance: ms.amount_match,
              },
            ]
          : []),
        ...(result.additional_matches || []).map((m) => ({
          invoice_num: m.invoice_num,
          reference_number: m.reference_number,
          invoice_amount: m.invoice_amount,
          invoice_date: m.invoice_date,
          file_name: m.file_name,
          difference: m.difference,
          within_tolerance: m.within_tolerance,
        })),
      ]
    : [];

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
            reconcile it against the invoice record linked by its invoice
            number (file name as fallback).
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
            {jobId && (
              <Typography sx={{ color: "#666", ml: 2, alignSelf: "center" }}>
                Job #{jobId} processing…
              </Typography>
            )}
          </div>
        )}

        {result && !loading && (
          <>
            {ms.outcome === "matched" ? (
              <div className={classes.matchedBanner}>
                <CheckCircleIcon sx={{ color: "#2e7d32", fontSize: 40, mr: 2 }} />
                <Typography sx={{ color: "#2e7d32", fontWeight: 700, fontSize: "1.2rem" }}>
                  {OUTCOME_TEXT[ms.outcome]}
                </Typography>
              </div>
            ) : (
              <div className={classes.summaryHeader}>
                {chip && <Chip label={chip.label} color={chip.color} />}
                <Typography sx={{ color: "#666" }}>
                  {OUTCOME_TEXT[ms.outcome]}
                </Typography>
              </div>
            )}

            <div className={classes.summaryGrid}>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Invoice No.</Typography>
                <Typography variant="h4">
                  {rawd?.invoice_num || ocr.invoice_num || "—"}
                </Typography>
                {rawd &&
                  !ms.invoice_num_match &&
                  ocr.invoice_num &&
                  String(ocr.invoice_num) !== String(rawd.invoice_num) && (
                    <Typography sx={{ color: "#b26a00", fontSize: "0.72rem", mt: 0.5 }}>
                      OCR misread the No. stamp as {ocr.invoice_num}
                    </Typography>
                  )}
              </div>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Expected (invoice amount)</Typography>
                <Typography variant="h4">
                  {rawd ? fmt(rawd.amount) : "—"}
                </Typography>
                {rawd?.invoice_date && (
                  <Typography sx={{ color: "#888", fontSize: "0.78rem", mt: 0.5 }}>
                    dated {rawd.invoice_date}
                  </Typography>
                )}
              </div>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Extracted Total (OCR)</Typography>
                <Typography variant="h4">
                  {ocr.amount != null ? fmt(ocr.amount) : "—"}
                </Typography>
                {ocr.amount == null && ocr.amount_ocr_raw && (
                  <Typography sx={{ color: "#b26a00", fontSize: "0.78rem", mt: 0.5 }}>
                    OCR read “{ocr.amount_ocr_raw}” — unreadable/low confidence
                  </Typography>
                )}
              </div>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Difference</Typography>
                <Typography variant="h4">
                  {ms.amount_diff != null ? fmt(ms.amount_diff) : "—"}
                </Typography>
              </div>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>OCR Confidence</Typography>
                <Typography variant="h4">
                  {ocr.average_confidence != null ? `${ocr.average_confidence}%` : "—"}
                </Typography>
              </div>
            </div>

            {linkedRows.length > 0 && (
              <Paper className={classes.panel} elevation={2} sx={{ mt: 3, p: 2 }}>
                <Typography variant="h6" sx={{ mb: 1.5, fontWeight: 600, color: "#333" }}>
                  Linked Invoice Record{linkedRows.length > 1 ? "s" : ""}
                </Typography>
                {linkedRows.map((row, i) => (
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
          </>
        )}
      </div>
    </AppLayout>
  );
};

export default PsrMatchPage;
