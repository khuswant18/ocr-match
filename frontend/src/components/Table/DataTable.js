import { useState, useEffect } from "react";
import { Paper, TextField } from "@mui/material";
import { useStyles } from "./styles";

function DataTable(props) {
  const classes = useStyles();
  const { data, tin } = props;
  const [localData, setLocalData] = useState(data || {});

  useEffect(() => {
    setLocalData({ ...data, TIN: tin !== undefined ? tin : (data ? data.TIN : "") });
  }, [data, tin]);

  const handleChange = (event, field) => {
    const newData = { ...localData, [field]: event.target.value };
    setLocalData(newData);
    props.onDataChange(newData);
  };

  const renderTextField = (field, label, mappedField) => (
    <TextField
      label={label}
      value={localData[mappedField] || localData[field] || ""}
      onChange={(event) => handleChange(event, mappedField || field)}
      sx={{ mb: 1 }}
      variant="standard"
      className={classes.focused}
      fullWidth
      inputProps={{ style: { fontWeight: "bold" } }}
    />
  );

  return (
    <Paper elevation={3} sx={{ p: 2, borderRadius: 5 }}>
      {renderTextField("Name", "Name", "name")}
      {renderTextField("Address", "Address", "address")}
      {renderTextField("City", "City", "city")}
      {renderTextField("State", "State", "state")}
      {renderTextField("Pincode", "Pincode", "pincode")}
      {renderTextField("TIN", "Tin", "tin")}
    </Paper>
  );
}

export default DataTable;
