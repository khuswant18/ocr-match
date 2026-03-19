import { useEffect, useRef } from "react";
import { useStyles } from "./styles";
import DataTable from "../../Table/DataTable";

const BuyerTable = (props) => {
  const classes = useStyles();

  return (
    <div className={classes.table}>
      <DataTable
        data={props.data ? props.data.buyer_data : ""}
        gstin={props.data ? props.data.buyer_gstin : ""}
        onDataChange={props.onDataChange}
      />
    </div>
  );
};

export default BuyerTable;
