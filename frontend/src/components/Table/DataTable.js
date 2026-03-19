import { useState, useEffect } from "react";
import { Paper, TextField } from "@mui/material";
import { useStyles } from "./styles";

function DataTable(props) {
  const classes = useStyles();
  const { data, gstin } = props;
  const [localData, setLocalData] = useState(data || {});

  useEffect(() => {
    setLocalData({ ...data, GSTIN: gstin !== undefined ? gstin : (data ? data.GSTIN : "") });
  }, [data, gstin]);

  const handleChange = (event, field) => {
    const newData = { ...localData, [field]: event.target.value };
    setLocalData(newData);
    props.onDataChange(newData);
  };

  const renderTextField = (field, label) => (
    <TextField
      label={label}
      value={localData[field] || ""}
      onChange={(event) => handleChange(event, field)}
      sx={{ mb: 1 }}
      variant="standard"
      className={classes.focused}
      fullWidth
      inputProps={{ style: { fontWeight: "bold" } }}
    />
  );

  return (
    <Paper elevation={3} sx={{ p: 2, borderRadius: 5 }}>
      {renderTextField("Name", "Name")}
      {renderTextField("Address", "Address")}
      {renderTextField("City", "City")}
      {renderTextField("State", "State")}
      {renderTextField("Pincode", "Pincode")}
      {renderTextField("GSTIN", "GSTIN")}
    </Paper>
  );
}

export default DataTable;
