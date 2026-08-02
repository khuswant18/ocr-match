import {
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Typography,
} from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";

import ButtonContained from "../StyledComponents/ButtonContained";
import ButtonOutlined from "../StyledComponents/ButtonOutlined";

const TIER_CHIP = {
  low: { label: "Low quality", color: "error" },
  medium: { label: "Borderline quality", color: "warning" },
  high: { label: "Good quality", color: "success" },
};

const SEVERITY_COLOR = {
  critical: "#c62828",
  major: "#ed6c02",
  minor: "#666",
};

/**
 * Blocking prompt shown when an uploaded invoice scores below the quality
 * threshold. The vendor must choose one of the two server-declared actions;
 * the dialog is deliberately not dismissable by backdrop click or Escape.
 */
const QualityWarningDialog = ({ open, hold, busy, onRetry, onProceed }) => {
  if (!hold) return null;

  const quality = hold.quality || {};
  const warning = hold.warning || {};
  const issues = warning.issues || quality.issues || [];
  const chip = TIER_CHIP[quality.tier] || TIER_CHIP.low;

  // Labels come from the server so the API stays the source of truth.
  const actions = hold.actions || [];
  const retryAction = actions.find((a) => a.id === "retry");
  const proceedAction = actions.find((a) => a.id === "proceed");

  return (
    <Dialog
      open={!!open}
      disableEscapeKeyDown
      onClose={(event, reason) => {
        if (reason === "backdropClick") return;
      }}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <ErrorOutlineIcon sx={{ color: "#c62828" }} />
        <Typography variant="h6" component="span" sx={{ fontWeight: 600 }}>
          {warning.title || "This invoice may be too low quality to read reliably"}
        </Typography>
      </DialogTitle>

      <DialogContent dividers>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "1.5rem",
            marginBottom: "1rem",
          }}
        >
          <div>
            <Typography sx={{ color: "#666" }}>Invoice Quality Score</Typography>
            <Typography variant="h4">
              {quality.score != null ? quality.score : "—"}
            </Typography>
          </div>
          <Chip label={chip.label} color={chip.color} size="small" />
        </div>

        <Typography sx={{ mb: issues.length ? 2 : 0 }}>
          {warning.message ||
            "The invoice you uploaded may be blurry, incomplete, poorly scanned, cropped, or otherwise difficult to read. We recommend uploading a higher-quality version."}
        </Typography>

        {issues.length > 0 && (
          <>
            <Divider sx={{ mb: 1.5 }} />
            <Typography sx={{ color: "#666", fontSize: "0.8rem", mb: 1 }}>
              What we detected
            </Typography>
            {issues.map((issue) => (
              <div key={issue.code} style={{ marginBottom: "0.75rem" }}>
                <Typography
                  sx={{
                    fontWeight: 600,
                    fontSize: "0.9rem",
                    color: SEVERITY_COLOR[issue.severity] || "#242424",
                  }}
                >
                  {issue.message}
                </Typography>
                {issue.hint && (
                  <Typography sx={{ color: "#666", fontSize: "0.78rem", mt: 0.25 }}>
                    {issue.hint}
                  </Typography>
                )}
              </div>
            ))}
          </>
        )}
      </DialogContent>

      <DialogActions sx={{ p: 2, gap: 1 }}>
        <ButtonOutlined onClick={onProceed} disabled={busy}>
          {busy ? (
            <CircularProgress size={18} sx={{ mr: 1 }} />
          ) : null}
          {proceedAction?.label || "Proceed Anyway"}
        </ButtonOutlined>
        <ButtonContained onClick={onRetry} disabled={busy} autoFocus>
          {retryAction?.label || "Upload a Better Invoice"}
        </ButtonContained>
      </DialogActions>
    </Dialog>
  );
};

export default QualityWarningDialog;
