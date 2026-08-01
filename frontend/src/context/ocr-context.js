import React, { useState } from "react";

const OCRContext = React.createContext({
  activePage: 0,
  originalImage: null,
  actualImage: null,
  textResult: null,
  extractedData: null,
  file: null,
  invoiceId: null,
  isInvoice: true,
  poNumber: "",
  quality: null,
  qualityHold: null,
  qualityFlag: "ok",
  setActivePage: (activePage) => {},
  setOriginalImage: (image) => {},
  setActualImage: (image) => {},
  setTextResult: (text) => {},
  setExtractedData: (data) => {},
  setFile: (file) => {},
  setInvoiceId: (invoice_id) => {},
  setIsInvoice: (isInvoice) => {},
  setPoNumber: (poNumber) => {},
  setQuality: (quality) => {},
  setQualityHold: (hold) => {},
  setQualityFlag: (flag) => {},
});

export const OCRContextProvider = (props) => {
  const [activePage, setActivePage] = useState(0);
  const [originalImage, setOriginalImage] = useState(null);
  const [actualImage, setActualImage] = useState(null);
  const [textResult, setTextResult] = useState(null);
  const [extractedData, setExtractedData] = useState(null);
  const [file, setFile] = useState(null);
  const [invoiceId, setInvoiceId] = useState(null);
  const [isInvoice, setIsInvoice] = useState(true);
  const [poNumber, setPoNumber] = useState("");
  // Quality assessment state: `quality` is the full report for the last
  // extraction, `qualityHold` is set only while a low-quality upload is
  // waiting on a vendor decision, `qualityFlag` is ok | caution |
  // proceeded_low_quality.
  const [quality, setQuality] = useState(null);
  const [qualityHold, setQualityHold] = useState(null);
  const [qualityFlag, setQualityFlag] = useState("ok");

  const pageHandler = (activePage) => {
    setActivePage(activePage);
  };

  const contextValue = {
    activePage: activePage,
    originalImage: originalImage,
    actualImage: actualImage,
    textResult: textResult,
    extractedData: extractedData,
    file: file,
    invoiceId: invoiceId,
    isInvoice: isInvoice,
    poNumber: poNumber,
    quality: quality,
    qualityHold: qualityHold,
    qualityFlag: qualityFlag,
    setActivePage: pageHandler,
    setOriginalImage: setOriginalImage,
    setActualImage: setActualImage,
    setTextResult: setTextResult,
    setExtractedData: setExtractedData,
    setFile: setFile,
    setInvoiceId: setInvoiceId,
    setIsInvoice: setIsInvoice,
    setPoNumber: setPoNumber,
    setQuality: setQuality,
    setQualityHold: setQualityHold,
    setQualityFlag: setQualityFlag,
  };

  return <OCRContext.Provider value={contextValue}>{props.children}</OCRContext.Provider>;
};

export default OCRContext;
