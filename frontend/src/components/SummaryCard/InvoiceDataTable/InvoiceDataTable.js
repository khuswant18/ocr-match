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
    } else if (field === "supplier_name" || field === "supplier_tin" || field === "supplier_contact" || field === "vendor_number") {
       if (!newData.supplier) newData.supplier = {};
       const keyMap = { supplier_name: "name", supplier_tin: "tin", supplier_contact: "contact", vendor_number: "vendor_number" };
       newData.supplier[keyMap[field]] = e.target.value;
    } else if (field === "buyer_name" || field === "buyer_tin" || field === "buyer_address") {
       if (!newData.buyer) newData.buyer = {};
       const keyMap = { buyer_name: "name", buyer_tin: "tin", buyer_address: "address" };
       newData.buyer[keyMap[field]] = e.target.value;
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
    } else if (field === "supplier_contact") {
      rawValue = localData.supplier?.contact;
    } else if (field === "vendor_number") {
      rawValue = localData.supplier?.vendor_number;
    } else if (field === "buyer_name") {
      rawValue = localData.buyer?.name;
    } else if (field === "buyer_tin") {
      rawValue = localData.buyer?.tin;
    } else if (field === "buyer_address") {
      rawValue = localData.buyer?.address;
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
    { field: "so_number", label: "SO Number" },
    { field: "invoice_date", label: "Invoice Date" },
    { field: "terms", label: "Terms" },
    { field: "supplier_name", label: "Supplier" },
    { field: "supplier_tin", label: "Supplier TIN" },
    { field: "supplier_contact", label: "Supplier Contact" },
    { field: "vendor_number", label: "Vendor Number" },
    { field: "buyer_name", label: "Buyer / Store" },
    { field: "buyer_tin", label: "Buyer TIN" },
    { field: "buyer_address", label: "Buyer Address" },
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
