import { useState, useEffect, useMemo } from "react";
import { Paper, TextField, Grid } from "@mui/material";
import { useStyles } from "./styles";

const InvoiceTable = (props) => {
  const classes = useStyles();
  const invoiceData = useMemo(() => props.data || {}, [props.data]);
  const [localData, setLocalData] = useState(invoiceData);

  useEffect(() => {
    setLocalData(invoiceData);
  }, [invoiceData]);

  const handleChange = (e, field) => {
    let newData = { ...localData };
    if (field === "cgst" || field === "sgst" || field === "igst" || field === "subtotal" || field === "total_amount") {
       if (!newData.financials) newData.financials = {};
       newData.financials[field] = e.target.value;
    } else if (field === "bank" || field === "ifsc" || field === "account_number") {
       const bankFieldMap = {"bank": "bank_name", "ifsc": "ifsc", "account_number": "account_number"};
       if (!newData.bank_details) newData.bank_details = {};
       newData.bank_details[bankFieldMap[field]] = e.target.value;
    } else {
       newData[field] = e.target.value;
    }
    setLocalData(newData);
    props.onDataChange(newData);
  };

  const renderTextField = (field, label, index) => {
    // Check nested structures primarily from Gemini (like financial dict or bank details)
    let rawValue = localData[field];
    
    if (field === "cgst" || field === "sgst" || field === "igst" || field === "subtotal" || field === "total_amount") {
      if (localData.financials && localData.financials[field] !== undefined) {
         rawValue = localData.financials[field];
      }
    } else if (field === "bank" || field === "ifsc" || field === "account_number") {
      const bankFieldMap = {"bank": "bank_name", "ifsc": "ifsc", "account_number": "account_number"};
      if (localData.bank_details && localData.bank_details[bankFieldMap[field]] !== undefined) {
         rawValue = localData.bank_details[bankFieldMap[field]];
      }
    }

    let displayValue = rawValue || "";

    return (
      <Grid item xs={6} key={index}>
        <TextField
          label={label}
          value={displayValue}
          onChange={(event) => handleChange(event, field)}
          variant="standard"
          className={classes.focused}
          fullWidth
          inputProps={{ style: { fontWeight: "bold" } }}
        />
      </Grid>
    );
  };

  const fields = [
    { field: "invoice_number", label: "Invoice number" },
    { field: "po_number", label: "PO Number" },
    { field: "invoice_date", label: "Invoice Date" },
    { field: "due_date", label: "Due Date" },
    { field: "bank", label: "Bank" },
    { field: "ifsc", label: "IFSC" },
    { field: "account_number", label: "Account Number" },
    { field: "payment_method", label: "Payment method" },
    { field: "subtotal", label: "Subtotal" },
    { field: "cgst", label: "CGST" },
    { field: "sgst", label: "SGST" },
    { field: "igst", label: "IGST" },
    { field: "total_amount", label: "Total amount" },
  ];

  return (
    <div className={classes.table}>
      <Paper elevation={3} sx={{ p: 2, borderRadius: 5 }}>
        <Grid container spacing={1}>
          {fields.map((field, index) => renderTextField(field.field, field.label, index))}
        </Grid>
      </Paper>
    </div>
  );
};

export default InvoiceTable;
