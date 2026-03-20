import { useStyles } from "./styles";
import DataTable from "../../Table/DataTable";

const BuyerTable = (props) => {
  const classes = useStyles();

  return (
    <div className={classes.table}>
      <DataTable
        data={props.data ? props.data.buyer : {}}
        tin={props.data && props.data.buyer ? props.data.buyer.tin : ""}
        onDataChange={props.onDataChange}
      />
    </div>
  );
};

export default BuyerTable;
