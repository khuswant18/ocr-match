import { useStyles } from "./styles";
import DataTable from "../../Table/DataTable";

const SellerTable = (props) => {
  const classes = useStyles();

  return (
    <div className={classes.table}>
      <DataTable
        data={props.data ? props.data.supplier : {}}
        tin={props.data && props.data.supplier ? props.data.supplier.tin : ""}
        onDataChange={props.onDataChange}
      />
    </div>
  );
};

export default SellerTable;
