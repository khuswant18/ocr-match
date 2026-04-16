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
    if (["subtotal", "vat", "discount", "total_amount"].includes(field)) {
       if (!newData.financials) newData.financials = {};
       newData.financials[field] = e.target.value;
    } else if (field === "supplier_name" || field === "supplier_tin") {
       if (!newData.supplier) newData.supplier = {};
       newData.supplier[field === "supplier_name" ? "name" : "tin"] = e.target.value;
    } else if (field === "buyer_name" || field === "buyer_tin") {
       if (!newData.buyer) newData.buyer = {};
       newData.buyer[field === "buyer_name" ? "name" : "tin"] = e.target.value;
    } else {
       newData[field] = e.target.value;
    }
    setLocalData(newData);
    props.onDataChange(newData);
  };

  const renderTextField = (field, label, index) => {
    let rawValue = localData[field];

    if (["subtotal", "vat", "discount", "total_amount"].includes(field)) {
      if (localData.financials && localData.financials[field] !== undefined) {
         rawValue = localData.financials[field];
      }
    } else if (field === "supplier_name") {
      rawValue = localData.supplier?.name;
    } else if (field === "supplier_tin") {
      rawValue = localData.supplier?.tin;
    } else if (field === "buyer_name") {
      rawValue = localData.buyer?.name;
    } else if (field === "buyer_tin") {
      rawValue = localData.buyer?.tin;
    }

    let displayValue = rawValue ?? "";
    if (typeof displayValue === "number") displayValue = String(displayValue);

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
    { field: "invoice_number", label: "Invoice Number" },
    { field: "po_number", label: "PO Number" },
    { field: "invoice_date", label: "Invoice Date" },
    { field: "due_date", label: "Due Date" },
    { field: "supplier_name", label: "Supplier" },
    { field: "supplier_tin", label: "Supplier TIN" },
    { field: "buyer_name", label: "Buyer / Store" },
    { field: "buyer_tin", label: "Buyer TIN" },
    { field: "store_code", label: "Store Code" },
    { field: "subtotal", label: "Subtotal" },
    { field: "vat", label: "VAT" },
    { field: "discount", label: "Discount" },
    { field: "total_amount", label: "Total Amount" },
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
