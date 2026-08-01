import { useContext, useState } from "react";

import { useSnackbar } from "notistack";
import { Typography, Grid, CircularProgress } from "@mui/material";
import { useStyles } from "./styles";
import ButtonOutlined from "../StyledComponents/ButtonOutlined";
import httpRequest from "../../httpRequest";
import OCRContext from "../../context/ocr-context";
import QualityWarningDialog from "../QualityWarningDialog/QualityWarningDialog";
import { COLORS } from "../../styles/constants";

const OCRCard = () => {
  const classes = useStyles();
  const ocrCtx = useContext(OCRContext);
  const [loading, setLoading] = useState(false);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const { enqueueSnackbar } = useSnackbar();

  const handleOCRmethod = async (OCRmethod) => {
    setLoading(true); 

    let formData = new FormData();
    formData.append("file", ocrCtx.actualImage);
    if (ocrCtx.file.type === "application/pdf") {
      formData.append("pdf", ocrCtx.file);
    } else if (ocrCtx.file.type === "image/jpeg") {
      formData.append("image", ocrCtx.file);
    } else if (ocrCtx.file.type === "image/png") {
      formData.append("image", ocrCtx.file);
    } else if (ocrCtx.file.type === "image/webp") {
      formData.append("image", ocrCtx.file);
    } else { 
      formData.append("image", ocrCtx.file); 
    }  
    
    if (ocrCtx.poNumber) {
      formData.append("po_number", ocrCtx.poNumber);
    }

    try {
      const startTime = performance.now();
      const resp = await httpRequest.post(`${process.env.REACT_APP_BACKEND_URL}/${OCRmethod}`, formData);

      // Low quality: pause here and let the vendor decide. Deliberately does
      // NOT advance to the summary page.
      if (resp?.data?.status === "quality_hold") {
        ocrCtx.setQualityHold(resp.data);
        ocrCtx.setQuality(resp.data.quality ?? null);
        setLoading(false);
        return;
      }

      const endTime = performance.now();
      applyOcrResult(resp.data, (endTime - startTime) / 1000);
      setLoading(false);
      ocrCtx.setActivePage(3);
    } catch (error) {
      console.log("Error", error);
      enqueueSnackbar(
        error?.response?.data?.error || "Extraction failed",
        { variant: "error" }
      );
      // Previously the page advanced regardless, landing the user on an empty
      // summary after a network error or a 500. Stay put instead.
      setLoading(false);
    }
  };

  const applyOcrResult = (data, duration) => {
    const time_other = duration - data.time.recognition + data.time.parsing;
    const invoiceId = data?.invoice_id ?? data?.existing_invoice_id ?? null;
    const time = data["time"];
    time["other"] = time_other;
    ocrCtx.setTextResult(data["text"]);
    const isInvoice = checkIfInvoice(data);
    const extractedData = {
      ...data["parsed_data"],
      id: invoiceId,
    };
    ocrCtx.setExtractedData(extractedData);
    ocrCtx.setInvoiceId(invoiceId);
    ocrCtx.setQuality(data.quality ?? null);
    ocrCtx.setQualityFlag(data.status ?? "ok");
    if (isInvoice && invoiceId != null && Number.isFinite(time_other)) {
      saveTimeOther(invoiceId, time_other);
    }
  };

  const resetToUpload = () => {
    ocrCtx.setQualityHold(null);
    ocrCtx.setQuality(null);
    ocrCtx.setQualityFlag("ok");
    ocrCtx.setExtractedData(null);
    ocrCtx.setTextResult(null);
    ocrCtx.setInvoiceId(null);
    ocrCtx.setFile(null);
    ocrCtx.setActualImage(null);
    ocrCtx.setOriginalImage(null);
    // Page 0 is the upload step, whose next button is disabled until a file
    // is chosen -- so clearing `file` parks the flow awaiting a new invoice.
    ocrCtx.setActivePage(0);
  };

  const handleQualityDecision = async (decision) => {
    const hold = ocrCtx.qualityHold;
    if (!hold) return;

    if (decision === "retry") {
      setDecisionLoading(true);
      try {
        await httpRequest.post(
          `${process.env.REACT_APP_BACKEND_URL}/paddleOCR/quality-decision`,
          { assessment_id: hold.assessment_id, decision: "retry" }
        );
      } catch (error) {
        // The vendor is going back to the upload step either way; a failure to
        // release the server-side cache is not worth blocking them on.
        console.log("quality retry cleanup failed", error);
      }
      setDecisionLoading(false);
      resetToUpload();
      return;
    }

    setDecisionLoading(true);
    try {
      const startTime = performance.now();
      const resp = await httpRequest.post(
        `${process.env.REACT_APP_BACKEND_URL}/paddleOCR/quality-decision`,
        { assessment_id: hold.assessment_id, decision: "proceed" }
      );
      const endTime = performance.now();
      applyOcrResult(resp.data, (endTime - startTime) / 1000);
      ocrCtx.setQualityHold(null);
      setDecisionLoading(false);
      ocrCtx.setActivePage(3);
    } catch (error) {
      setDecisionLoading(false);
      if (error?.response?.status === 410) {
        enqueueSnackbar(
          "This quality check expired. Please upload the invoice again.",
          { variant: "warning" }
        );
        resetToUpload();
        return;
      }
      enqueueSnackbar(
        error?.response?.data?.error || "Extraction failed",
        { variant: "error" }
      );
    }
  };

  const checkIfInvoice = (data) => {
    const pData = data?.parsed_data || {};
    if ( 
      !pData.invoice_number &&
      !pData.invoice_date &&
      !pData.total_amount &&
      !pData.due_date &&
      !pData?.financials?.total_amount &&
      !pData?.supplier?.name &&
      !pData?.buyer?.name
    ) {
      ocrCtx.setIsInvoice(false);
      return false;
    } else {
      ocrCtx.setIsInvoice(true);
      return true;
    }
  };

  const saveTimeOther = async (invoice_id, time_other) => {
    try {
      await httpRequest.post(`${process.env.REACT_APP_BACKEND_URL}/save-time-other`, {
        invoice_id: invoice_id,
        time_other: time_other,
      });
    } catch (error) {
      console.log("Error");
      enqueueSnackbar("Error", { variant: "error" });
    }
  };

  return (
    <>
      <div className={classes.rootContainer}>
        <Typography variant="h5" sx={{ pt: 2 }}>
          Extract Invoice
        </Typography>

        <Grid container spacing={0} sx={{ mt: "15px", justifyContent: "center" }}>
          <Grid item xs={8}>
            <ButtonOutlined
              variant="outlined"
              onClick={() => handleOCRmethod("paddleOCR")}
              style={{
                padding: "10px 24px",
                width: "100%",
              }}
              disabled={loading}
            >
              Run PaddleOCR
            </ButtonOutlined>
          </Grid>
        </Grid>

        {loading && <CircularProgress sx={{ color: COLORS.PRIMARY, mt: "15px" }} />}
      </div>

      <QualityWarningDialog
        open={!!ocrCtx.qualityHold}
        hold={ocrCtx.qualityHold}
        busy={decisionLoading}
        onRetry={() => handleQualityDecision("retry")}
        onProceed={() => handleQualityDecision("proceed")}
      />
    </>
  );
};

export default OCRCard;
