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

  const handleChange = (event, field) => {
    const newData = { ...localData, [field]: event.target.value };
    setLocalData(newData);
    props.onDataChange(newData);
  };

  const renderTextField = (field, label, index) => {
    // Determine the value to display; some fields may prepend/append symbols
    let displayValue = localData[field] || "";
    if (field === "total_amount" && displayValue) {
      displayValue = `₹ ${displayValue}`;
    }

    return (
      <Grid item xs={6} key={index}>
        <TextField
          label={label}
          value={field === "total_amount" && localData[field] ? localData[field] : (localData[field] || "")}
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
