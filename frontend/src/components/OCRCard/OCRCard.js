import { useContext, useState } from "react";

import { useSnackbar } from "notistack";
import { Typography, Grid, CircularProgress } from "@mui/material";
import { useStyles } from "./styles";
import ButtonOutlined from "../StyledComponents/ButtonOutlined";
import httpRequest from "../../httpRequest";
import OCRContext from "../../context/ocr-context";
import { COLORS } from "../../styles/constants";

const OCRCard = () => {
  const classes = useStyles();
  const ocrCtx = useContext(OCRContext);
  const [loading, setLoading] = useState(false);
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

    try {
      const startTime = performance.now();
      const resp = await httpRequest.post(`${process.env.REACT_APP_BACKEND_URL}/${OCRmethod}`, formData);
      const endTime = performance.now(); 
      const duration = (endTime - startTime) / 1000;
      const time_other = duration - resp.data.time.recognition + resp.data.time.parsing;
      const time = resp["data"]["time"]; 
      time["other"] = time_other; 
      ocrCtx.setTextResult(resp["data"]["text"]); 
      const isInvoice = checkIfInvoice(resp["data"]);
      const extractedData = {  
        ...resp["data"]["parsed_data"],
        id: resp["data"]["invoice_id"], 
      };  
      ocrCtx.setExtractedData(extractedData);
      ocrCtx.setInvoiceId(resp["data"]["invoice_id"]);
      if (isInvoice) {
        saveTimeOther(resp["data"]["invoice_id"], time_other);
      }
    } catch (error) {
      console.log("Error");
      enqueueSnackbar("Error", { variant: "error" });
    }

    setLoading(false);
    ocrCtx.setActivePage(3);
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
    </>
  );
};

export default OCRCard;
